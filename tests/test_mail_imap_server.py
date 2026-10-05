"""The real IMAP client against a real (throwaway) IMAP server. Opt-in: the fake `imaplib` in
test_mail_imap.py covers the logic; this checks what a fake cannot, namely the TLS verification,
the real SEARCH/FETCH syntax, and that BODY.PEEK really leaves a message unseen.

    scripts/imap-test-certs.sh && docker compose --profile imap up -d imap
    ESBI_IMAP_TEST=localhost uv run pytest tests/test_mail_imap_server.py
    docker compose --profile imap down

ESBI_IMAP_TEST is the server's host name (`imap` from inside the dev container). The server
presents a certificate from a throwaway CA; the production client is not touched: the test only
points SSL_CERT_FILE (read by OpenSSL when the client builds its default, verifying context) at
that CA's file, for the one test."""

import imaplib
import os
import ssl
import time
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import pytest

from esbi_cli.mail.convert import email_to_clip
from esbi_cli.mail.imap import ImapMailClient, MailError

HOST = os.environ.get("ESBI_IMAP_TEST", "")
CA = Path(__file__).parent.parent / ".imap-test" / "ca.pem"
PORT = 3993  # the server's IMAPS port (the client's own default is 993)
REAL_IMAP4_SSL = imaplib.IMAP4_SSL

pytestmark = [
    pytest.mark.imap,
    pytest.mark.skipif(not HOST, reason="set ESBI_IMAP_TEST=<host> (see this file's docstring)"),
]


class AtTestPort(REAL_IMAP4_SSL):
    """The production factory builds IMAP4_SSL(host, ssl_context=...); only the port differs."""

    def __init__(self, host, **kwargs):
        super().__init__(host, PORT, **kwargs)


@pytest.fixture
def trusting(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(CA))
    monkeypatch.setattr(imaplib, "IMAP4_SSL", AtTestPort)


@pytest.fixture
def admin():
    """A separate session of the test's own, to seed the mailbox and to look at flags."""
    imap = REAL_IMAP4_SSL(HOST, PORT, ssl_context=ssl.create_default_context(cafile=str(CA)))
    imap.login("me", "secret")
    imap.select("INBOX")
    _, data = imap.search(None, "ALL")
    for number in data[0].split():
        imap.store(number, "+FLAGS", "\\Deleted")
    imap.expunge()
    yield imap
    imap.logout()


def _mail(subject, pdf: bytes | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"] = "sender@example.test", "me@localhost"
    msg["Subject"], msg["Message-ID"] = subject, make_msgid(domain="example.test")
    msg.set_content("Un cuerpo de texto lo bastante largo para no parecer un aviso. " * 4)
    if pdf:
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="informe.pdf")
    return msg.as_bytes()


def _flags(admin, uid) -> bytes:
    _, data = admin.uid("FETCH", uid, "(FLAGS)")
    return data[0]


def _deliver(admin, raw: bytes) -> None:
    admin.append("INBOX", "", imaplib.Time2Internaldate(time.time()), raw)


def test_it_reads_mail_with_the_production_tls_context_and_leaves_it_unseen_until_told(
    trusting, admin
):
    _deliver(admin, _mail("Uno"))
    client = ImapMailClient(HOST, "me", "secret", "INBOX")  # the default, verifying factory

    mails = client.recent()

    assert len(mails) == 1 and b"Subject: Uno" in mails[0][1]
    uid = mails[0][0]
    assert b"\\Seen" not in _flags(admin, uid)  # BODY.PEEK did not set it
    client.mark_seen(uid)
    assert b"\\Seen" in _flags(admin, uid)
    client.close()


def test_search_since_keeps_only_the_window(trusting, admin):
    _deliver(admin, _mail("Hoy"))
    client = ImapMailClient(HOST, "me", "secret", "INBOX")

    assert len(client.recent(days=14)) == 1
    assert client.recent(days=14, today=date.today() + timedelta(days=60)) == []
    client.close()


def test_a_pdf_attachment_survives_the_real_fetch_and_becomes_a_pdf_to_save(trusting, admin):
    pdf = b"%PDF-1.4\n" + bytes(range(256)) * 4  # binary: any newline or charset mangling shows
    _deliver(admin, _mail("Con PDF", pdf))
    client = ImapMailClient(HOST, "me", "secret", "INBOX")

    ((_, raw),) = client.recent()

    assert email_to_clip(raw).pdfs == [("informe.pdf", pdf)]
    client.close()


def test_a_server_whose_certificate_the_system_does_not_trust_is_refused(monkeypatch):
    """No SSL_CERT_FILE: the throwaway CA is unknown, and the app password must not be sent."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", AtTestPort)

    with pytest.raises(MailError, match="CERTIFICATE_VERIFY_FAILED"):
        ImapMailClient(HOST, "me", "secret", "INBOX").recent()


def test_a_wrong_password_and_a_missing_mailbox_are_clear_errors(trusting, admin):
    with pytest.raises(MailError, match="login/select failed"):
        ImapMailClient(HOST, "me", "wrong", "INBOX").recent()
    with pytest.raises(MailError, match="not found|failed"):
        ImapMailClient(HOST, "me", "secret", "No existe").recent()
