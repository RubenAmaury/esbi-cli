"""Turn a raw email (RFC 5322 bytes) into a Web Clipper-style note for the vault's inbox."""

import email
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from email import policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import lxml.html
import trafilatura
from PIL import Image

from esbi_cli import lang
from esbi_cli.vault import Page, safe_title


@dataclass
class ClipNote:
    filename: str
    content: str  # empty when the mail is only attachments
    source: str  # stable id of the mail (`mail:<message-id>`), used to spot duplicates
    pdfs: list[tuple[str, bytes]] = field(default_factory=list)  # (file name, bytes) attached
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (safe file name, bytes) kept
    links: list[str] = field(default_factory=list)  # http(s) links worth following, in order


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


# Image attachments: what the bytes are decides, never the declared type or the file name.
IMAGE_FORMATS = {  # declared content type -> (format Pillow must find in the bytes, extension)
    "image/png": ("PNG", ".png"),
    "image/jpeg": ("JPEG", ".jpg"),
    "image/webp": ("WEBP", ".webp"),
    "image/tiff": ("TIFF", ".tiff"),
}
MIN_IMAGE_SIDE_PX = 200  # signature logos, icons and tracking pixels are smaller
MIN_IMAGE_BYTES = 5_000  # ...or flat: a screenshot or a photo is never this light
MAX_IMAGE_BYTES = 5_000_000
MAX_MAIL_IMAGE_BYTES = 15_000_000
MAX_IMAGE_PIXELS = 50_000_000  # the decoder allocates width x height: refuse absurd sizes


def _image_name(data: bytes, declared: str, filename: str | None) -> str | None:
    """`<safe stem><extension>` for an image worth keeping, else None."""
    if declared not in IMAGE_FORMATS or not MIN_IMAGE_BYTES <= len(data) <= MAX_IMAGE_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt, (width, height) = img.format, img.size
    except Exception:  # Pillow raises several unrelated error types for bytes that are no image
        return None
    expected, suffix = IMAGE_FORMATS[declared]
    if (
        fmt != expected
        or min(width, height) < MIN_IMAGE_SIDE_PX
        or width * height > MAX_IMAGE_PIXELS
    ):
        return None
    stem = Path((filename or "").replace("\\", "/")).stem  # never a path: only the last part
    return f"{safe_title(stem, 40) or 'image'}{suffix}"


def _images(msg: EmailMessage) -> list[tuple[str, bytes]]:
    kept, total = [], 0
    for part in msg.walk():
        if part.is_multipart() or not part.get_content_type().startswith("image/"):
            continue
        data = part.get_content()
        name = _image_name(data, part.get_content_type(), part.get_filename())
        if name and total + len(data) <= MAX_MAIL_IMAGE_BYTES:
            kept.append((name, data))
            total += len(data)
    return kept


_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_NOT_AN_ARTICLE = re.compile(
    r"unsubscri|opt-?out|preferences|view-?in-?browser|view_in_browser|web-?version|"
    r"manage[-_]?subscription|confirm|verif|reset|log-?in|sign-?in|magic|activat|password|token=|"
    r"\.(?:gif|png|jpe?g|svg|webp|css|js|ico)(?:\?|$)",
    re.IGNORECASE,
)
_REDIRECT_HOSTS = (
    "click",
    "clicks",
    "track",
    "tracking",
    "links",
    "trk",
    "email",
    "em",
)  # click.news.test
MAX_LINK_CHARS = 500


def _links(text: str) -> list[str]:
    """http(s) links in the mail's text, in order and without repeats, minus tracking redirects,
    unsubscribe/preferences/view-in-browser housekeeping and pictures. ponytail: only links that
    show in the text; a link hidden behind anchor text in an HTML-only mail is not found."""
    found: list[str] = []
    for url in (u.rstrip(".,;:!?") for u in _URL.findall(text)):
        host = urlparse(url).hostname or ""
        if (
            len(url) <= MAX_LINK_CHARS
            and host
            and not _NOT_AN_ARTICLE.search(url)
            and not (host.count(".") >= 2 and host.partition(".")[0] in _REDIRECT_HOSTS)
            and host != "list-manage.com"
            and not host.endswith(".list-manage.com")
            and url not in found
        ):
            found.append(url)
    return found


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
    images = _images(msg)
    if not body and not pdfs and not images:
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
        images=images,
        links=_links(body),
    )
