import imaplib
from datetime import date

import pytest

from esbi_cli.mail.imap import ImapMailClient, MailError


class FakeImap:
    """The slice of imaplib.IMAP4_SSL the client uses, with Gmail-shaped responses."""

    def __init__(self, messages: dict[bytes, bytes], login_error: str | None = None):
        self.messages, self.login_error = messages, login_error
        self.calls: list[tuple] = []

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if self.login_error:
            raise imaplib.IMAP4.error(self.login_error)
        return "OK", [b"logged in"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b" ".join(self.messages)]
        if command == "FETCH":
            raw = self.messages[args[0].encode()]
            return "OK", [(b"1 (UID %s BODY[] {%d}" % (args[0].encode(), len(raw)), raw), b")"]
        return "OK", [b"stored"]

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b"bye"]


def make_client(fake: FakeImap) -> ImapMailClient:
    return ImapMailClient(
        host="imap.example.test",
        user="me@example.test",
        password="app-password",
        mailbox="esbi-cli",
        factory=lambda host: fake,
    )


def test_recent_mail_is_read_by_date_whether_seen_or_not_and_without_marking_it():
    fake = FakeImap({b"5": b"raw five", b"7": b"raw seven"})
    client = make_client(fake)

    assert client.recent(days=14, today=date(2026, 10, 1)) == [
        ("5", b"raw five"),
        ("7", b"raw seven"),
    ]
    client.mark_seen("5")
    client.close()

    assert ("login", "me@example.test", "app-password") in fake.calls
    assert ("select", '"esbi-cli"', False) in fake.calls
    assert ("SEARCH", None, "SINCE", "17-Sep-2026") in fake.calls  # not UNSEEN: opened mail counts
    assert ("FETCH", "5", "(BODY.PEEK[])") in fake.calls  # PEEK: reading must not set \Seen
    assert ("STORE", "5", "+FLAGS", "(\\Seen)") in fake.calls
    assert fake.calls[-1] == ("logout",)


def test_a_rejected_login_is_reported_without_echoing_the_password():
    fake = FakeImap({}, login_error="AUTHENTICATIONFAILED Invalid credentials")

    with pytest.raises(MailError) as error:
        make_client(fake).recent()

    assert "login" in str(error.value).lower() and "app-password" not in str(error.value)
