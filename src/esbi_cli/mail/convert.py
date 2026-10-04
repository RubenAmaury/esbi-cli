"""Turn a raw email (RFC 5322 bytes) into a Web Clipper-style note for the vault's inbox."""

import email
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

import lxml.html
import trafilatura

from esbi_cli import lang
from esbi_cli.vault import Page, safe_title


@dataclass
class ClipNote:
    filename: str
    content: str  # empty when the mail is only attachments
    source: str  # stable id of the mail (`mail:<message-id>`), used to spot duplicates
    pdfs: list[tuple[str, bytes]] = field(default_factory=list)  # (file name, bytes) attached


# Newsletters pad the preview text with these (zero-width and joiner characters, soft hyphens)
INVISIBLE = re.compile("[\u034f\u200b-\u200f\u2060\u00ad\ufeff]")


def _clean(text: str) -> str:
    """Drop the invisible padding, then the blank lines it leaves behind."""
    text = INVISIBLE.sub("", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _html_to_text(html: str) -> str:
    """Article extraction when the email looks like one, else the page's visible text."""
    extracted = trafilatura.extract(html, output_format="markdown", favor_recall=True)
    if extracted and len(extracted.strip()) > 40:
        return extracted.strip()
    tree = lxml.html.fromstring(html)
    for junk in tree.xpath("//script | //style | //head"):
        junk.drop_tree()
    return re.sub(r"\n{3,}", "\n\n", tree.text_content()).strip()


MIN_PLAIN_CHARS = 100  # shorter plain parts are usually a "view in browser" stub


def _body(msg: EmailMessage) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    plain_text = plain.get_content().strip() if plain else ""
    if plain_text and (len(plain_text) >= MIN_PLAIN_CHARS or html is None):
        return plain_text
    return _html_to_text(html.get_content()) if html else plain_text


def _sent_date(msg: EmailMessage) -> date:
    try:
        return parsedate_to_datetime(str(msg["Date"])).date()
    except (TypeError, ValueError):
        return date.today()


def email_to_clip(raw: bytes, language: str = lang.DEFAULT) -> ClipNote:
    msg = email.message_from_bytes(raw, policy=policy.default)
    subject = str(msg["Subject"] or lang.t(language, "no_subject")).strip()
    body = _clean(_body(msg))
    pdfs = [
        (part.get_filename() or "attachment.pdf", part.get_content())
        for part in msg.iter_attachments()
        if part.get_content_type() == "application/pdf"
    ]
    if not body and not pdfs:
        raise ValueError("the email has no readable text")
    sent = _sent_date(msg).isoformat()
    # an id is used as a source name and written into notes: letters, digits and . @ + = _ - only
    message_id = (
        re.sub(r"[^\w.@+=-]", "", str(msg["Message-ID"] or ""))[:150]
        or hashlib.sha256(raw).hexdigest()[:16]
    )
    meta = {
        "title": subject,
        "source": f"mail:{message_id}",
        "kind": "email",
        "from": str(msg["From"] or ""),
        "date": sent,
    }
    content = Page(Path("clip.md"), meta, body).render() if body else ""
    return ClipNote(
        filename=f"{sent} {safe_title(subject, 60)}.md",
        content=content,
        source=meta["source"],
        pdfs=pdfs,
    )
