"""Pull unseen mail from the dedicated mailbox into the vault's inbox/ as clip notes."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from esbi_cli.mail.convert import email_to_clip
from esbi_cli.queue import Queue, normalize_target
from esbi_cli.vault import Vault, free_path, safe_title

MAIL_LINK_ORIGIN = "mail-link"  # queue origin of a link found in a mail: its page is email


class MailClient(Protocol):
    def recent(self, days: int = 14) -> list[tuple[str, bytes]]:
        """(uid, raw RFC 5322 message) for every message of the last `days`, seen or not."""
        ...

    def mark_seen(self, uid: str) -> None: ...

    def close(self) -> None: ...


@dataclass
class FetchResult:
    saved: int = 0
    duplicates: int = 0
    failed: int = 0
    images: int = 0  # image attachments kept
    links: int = 0  # links found in mail and queued


def _known_sources(vault: Vault) -> set[str]:
    """`mail:<id>` sources already saved: waiting in inbox/, moved to raw/inbox/, or ingested."""
    known = set()
    for folder in (vault.root / "inbox", vault.root / "raw" / "inbox"):
        for path in folder.glob("*.md") if folder.is_dir() else ():
            known.add(str(vault.read_page(path).meta.get("source")))
    known |= {str(p.meta.get("url")) for p in vault.iter_pages(("sources",))}
    return known


def _kept_file(vault: Vault, data: bytes, suffix: str) -> bool:
    """Is this very file already waiting in inbox/ or kept in raw/inbox/?"""
    return any(
        f.stat().st_size == len(data) and f.read_bytes() == data
        for folder in (vault.root / "inbox", vault.root / "raw" / "inbox")
        if folder.is_dir()
        for f in folder.iterdir()
        if f.suffix.lower() == suffix
    )


def _save(vault: Vault, inbox: Path, clip) -> int:
    """Write the note and its attachments; returns how many images were new."""
    if clip.content:
        free_path(inbox, clip.filename).write_text(clip.content, encoding="utf-8")
    stem, images = clip.filename.removesuffix(".md"), 0
    for name, data in clip.pdfs:
        _remember_mail_file(vault, data)
        if not _kept_file(vault, data, ".pdf"):
            free_path(inbox, f"{stem} - {safe_title(Path(name).stem, 40)}.pdf").write_bytes(data)
    for name, data in clip.images:  # `name` is already safe: stem and extension from the bytes
        _remember_mail_file(vault, data)
        if not _kept_file(vault, data, Path(name).suffix):
            free_path(inbox, f"{stem} - {name}").write_bytes(data)
            images += 1
    return images


def _queue_links(vault: Vault, queue: Queue, links: list[str], max_links: int) -> int:
    """Queue links not already known (queued, done or a source) as email-derived items. Never
    fetches: the nightly run reads them, with its limits and the private model."""
    queued = 0
    for url in links:
        if queued == max_links:
            break
        if not vault.find_source("url", normalize_target(url)) and queue.add(
            url, origin=MAIL_LINK_ORIGIN
        ):
            queued += 1
    return queued


def fetch_mail(
    client: MailClient,
    vault: Vault,
    queue: Queue | None = None,
    follow_links: bool = False,
    max_links: int = 3,
) -> FetchResult:
    """Save each recent mail as inbox/<date> <subject>.md (and its PDF and image attachments), mark
    it seen. With `follow_links` and a queue, the links in a newly saved mail are queued.

    Never deletes mail. Mail already captured is skipped by Message-ID, so the window can overlap
    runs. A mail that cannot be converted is reported once: its id is remembered in
    `.esbi/mail-failed.txt` and skipped from then on.
    """
    result = FetchResult()
    inbox = vault.root / "inbox"
    inbox.mkdir(exist_ok=True)
    known = _known_sources(vault)
    failed_file = vault.root / ".esbi" / "mail-failed.txt"
    failed_before = set(failed_file.read_text().split()) if failed_file.exists() else set()
    for uid, raw in client.recent():
        key = hashlib.sha256(raw).hexdigest()[:16]  # the uid is not stable across mailboxes
        if key in failed_before:
            continue
        try:
            clip = email_to_clip(raw, vault.language)
        except Exception:  # one unreadable mail must not block the rest
            result.failed += 1
            failed_file.parent.mkdir(exist_ok=True)
            with failed_file.open("a") as fh:
                fh.write(key + "\n")
            continue
        if clip.source in known:
            result.duplicates += 1
        else:
            try:
                result.images += _save(vault, inbox, clip)
                if follow_links and queue is not None:
                    result.links += _queue_links(vault, queue, clip.links, max_links)
            except OSError:  # a name the disk refuses: report it once, not on every run
                result.failed += 1
                failed_file.parent.mkdir(exist_ok=True)
                with failed_file.open("a") as fh:
                    fh.write(key + "\n")
                continue
            known.add(clip.source)
            result.saved += 1
        client.mark_seen(uid)
    return result


def _hashes_path(vault: Vault) -> Path:
    return vault.root / ".esbi" / "mail-pdfs.txt"


def _remember_mail_file(vault: Vault, data: bytes) -> None:
    """A PDF or image saved from a mail is email: its hash is kept so the privacy rules still know
    that once it sits in inbox/ as a plain file."""
    path, digest = _hashes_path(vault), hashlib.sha256(data).hexdigest()
    path.parent.mkdir(exist_ok=True)
    known = set(path.read_text().split()) if path.exists() else set()
    if digest not in known:
        with path.open("a") as fh:
            fh.write(digest + "\n")


def is_mail_file(vault: Vault, data: bytes) -> bool:
    path = _hashes_path(vault)
    return path.exists() and hashlib.sha256(data).hexdigest() in path.read_text().split()
