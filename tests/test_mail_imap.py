import imaplib
from datetime import date

import pytest

from esbi_cli.mail.imap import MONTHS, ImapMailClient, MailError


class FakeImap:
    """The slice of imaplib.IMAP4_SSL the client uses, with Gmail-shaped responses."""

    def __init__(
        self,
        messages: dict[bytes, bytes],
        login_error: str | None = None,
        received: dict[bytes, date] | None = None,
        unseen: set[bytes] | None = None,
        store_status: str = "OK",
        uidvalidity: bytes = b"777",
    ):
        self.messages, self.login_error = messages, login_error
        self.received, self.unseen = received or {}, unseen or set()
        self.store_status, self.uidvalidity = store_status, uidvalidity
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
            criteria = args[1:]
            if criteria[0] == "SINCE":  # received date, like Gmail: not when the label was added
                day = date(
                    int(criteria[1][-4:]), MONTHS.index(criteria[1][3:6]) + 1, int(criteria[1][:2])
                )
                found = [u for u in self.messages if self.received.get(u, day) >= day]
            elif criteria[0] == "UNSEEN":
                found = [u for u in self.messages if u in self.unseen]
            elif criteria[0] == "UID":  # "n:*" always includes the highest message, as IMAP does
                low = int(criteria[1].split(":")[0])
                top = max(self.messages, key=int, default=None)
                found = [u for u in self.messages if int(u) >= low or u == top]
            else:
                found = list(self.messages)
            return "OK", [b" ".join(found)]
        if command == "FETCH":
            raw = self.messages[args[0].encode()]
            return "OK", [(b"1 (UID %s BODY[] {%d}" % (args[0].encode(), len(raw)), raw), b")"]
        if command == "STORE":
            return self.store_status, [b"stored"]
        return "OK", [b"stored"]

    def response(self, code):
        return code, [self.uidvalidity]

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


def test_mail_that_was_not_taken_yet_comes_back_however_old_it_is():
    fake = FakeImap(
        {b"5": b"old unseen", b"7": b"recent"},
        received={b"5": date(2026, 9, 1), b"7": date(2026, 9, 30)},
        unseen={b"5"},
    )

    got = make_client(fake).recent(days=14, today=date(2026, 10, 1))

    assert [uid for uid, _ in got] == ["5", "7"]  # the worker marks what it took as seen


def test_mail_labelled_after_the_last_one_taken_comes_back_even_if_it_is_old_and_was_read():
    fake = FakeImap(
        {b"5": b"taken", b"6": b"taken", b"9": b"labelled later, old, already read"},
        received={b"5": date(2026, 8, 1), b"6": date(2026, 8, 2), b"9": date(2026, 8, 3)},
    )

    got = make_client(fake).recent(days=14, today=date(2026, 10, 1), after_uid=6)

    assert [uid for uid, _ in got] == ["9"]


def test_the_highest_message_is_not_returned_again_when_it_is_not_newer_than_the_last_taken():
    fake = FakeImap(
        {b"5": b"a", b"6": b"b"}, received={b"5": date(2026, 8, 1), b"6": date(2026, 8, 1)}
    )

    assert make_client(fake).recent(days=14, today=date(2026, 10, 1), after_uid=6) == []


def test_marking_seen_says_whether_the_server_accepted_it():
    assert make_client(FakeImap({b"5": b"x"})).mark_seen("5") is True
    assert make_client(FakeImap({b"5": b"x"}, store_status="NO")).mark_seen("5") is False


def test_the_mailbox_generation_is_read_from_the_select_reply():
    client = make_client(FakeImap({b"5": b"x"}, uidvalidity=b"4242"))

    assert client.uidvalidity == "4242"
