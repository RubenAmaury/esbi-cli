"""IMAP access to the dedicated mailbox (a Gmail label works as a mailbox name)."""

import imaplib
import ssl
from collections.abc import Callable
from datetime import date, timedelta

MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)  # IMAP wants English


class MailError(RuntimeError):
    pass


def _verified_ssl(host: str) -> imaplib.IMAP4:
    """imaplib's own default context does not check the certificate: the app password would go to
    whoever answers. This one verifies the chain and the host name."""
    return imaplib.IMAP4_SSL(host, ssl_context=ssl.create_default_context())


class ImapMailClient:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        mailbox: str,
        factory: Callable[[str], imaplib.IMAP4] = _verified_ssl,
    ):
        self.host, self.user, self.mailbox = host, user, mailbox
        self._password = password
        self._factory = factory
        self._imap: imaplib.IMAP4 | None = None

    def _connect(self) -> imaplib.IMAP4:
        if self._imap is None:
            try:
                imap = self._factory(self.host)
                imap.login(self.user, self._password)
                quoted = '"' + self.mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'
                status, _ = imap.select(quoted, readonly=False)
            except (imaplib.IMAP4.error, OSError) as exc:
                raise MailError(
                    f"IMAP login/select failed for {self.user}@{self.host}: {exc}"
                ) from None
            if status != "OK":
                raise MailError(f"Mailbox {self.mailbox!r} not found on {self.host}")
            self._imap = imap
        return self._imap

    @property
    def uidvalidity(self) -> str | None:
        """The mailbox generation: UIDs only mean something while it stays the same."""
        _, data = self._connect().response("UIDVALIDITY")
        return data[-1].decode() if data and data[-1] else None

    def recent(
        self, days: int = 14, today: date | None = None, after_uid: int | None = None
    ) -> list[tuple[str, bytes]]:
        """Every message of the last `days` (opened in Gmail or not), plus every one not taken yet
        (unseen, however old) and every one added to the label after `after_uid`: the window counts
        the day a mail was RECEIVED, not the day it was labelled, so a mail tagged yesterday that
        arrived last month would otherwise never be seen. The worker dedupes by Message-ID."""
        imap = self._connect()
        since = (today or date.today()) - timedelta(days=days)
        searches: list[tuple[str, ...]] = [
            ("SINCE", f"{since.day:02d}-{MONTHS[since.month - 1]}-{since.year}"),
            ("UNSEEN",),
        ]
        if after_uid is not None:
            searches.append(("UID", f"{after_uid + 1}:*"))
        try:
            wanted: set[int] = set()
            for criteria in searches:
                _, data = imap.uid("SEARCH", None, *criteria)
                found = {int(u) for u in data[0].decode().split()}
                if criteria[0] == "UID":  # `n:*` always includes the last message, even if older
                    found = {u for u in found if u > (after_uid or 0)}
                wanted |= found
            mails = []
            for uid in sorted(wanted):
                # BODY.PEEK[] reads the message without setting \Seen: only the worker does that,
                # after the note is safely written
                _, parts = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
                mails.append((str(uid), parts[0][1]))
            return mails
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailError(f"Reading mail failed: {exc}") from None

    def mark_seen(self, uid: str) -> bool:
        """True when the server accepted the flag (a refusal is a reply, not an exception)."""
        status, _ = self._connect().uid("STORE", uid, "+FLAGS", "(\\Seen)")
        return status == "OK"

    def close(self) -> None:
        if self._imap is not None:
            try:
                self._imap.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
            self._imap = None
