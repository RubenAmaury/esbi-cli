"""Pick up files dropped in the vault's inbox/ and queue them for ingestion."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from esbi_cli.extract.image import IMAGE_SUFFIXES
from esbi_cli.mail.convert import urls_in
from esbi_cli.mail.fetch import queue_links
from esbi_cli.queue import Queue
from esbi_cli.vault import Vault, free_path, parse_page

CAPTURABLE_SUFFIXES = (".pdf", ".md")
LINK_FILE_SUFFIX = ".txt"  # a link file: what the iPhone Shortcut saves; its links are queued


@dataclass
class ScanResult:
    enqueued: int = 0
    duplicates: int = 0
    unsupported: list[str] = field(default_factory=list)  # left in inbox/: nothing can read them


def _already_kept(folder: Path, path: Path) -> bool:
    """Is a byte-identical file already in `folder`? (Same size first: cheap for big PDFs.)"""
    size = path.stat().st_size
    return (
        any(
            f.is_file() and f.stat().st_size == size and f.read_bytes() == path.read_bytes()
            for f in folder.iterdir()
        )
        if folder.is_dir()
        else False
    )


def _suffixes(images: bool) -> tuple[str, ...]:
    return CAPTURABLE_SUFFIXES + (IMAGE_SUFFIXES if images else ())


def _links(path: Path) -> list[str]:
    return urls_in(path.read_text(encoding="utf-8", errors="replace"))


def _takes(path: Path, suffixes: tuple[str, ...]) -> bool:
    """Would a scan take this file? A link file only when there is a link in it."""
    suffix = path.suffix.lower()
    return suffix in suffixes or (suffix == LINK_FILE_SUFFIX and bool(_links(path)))


def waiting(vault: Vault, images: bool = False) -> int:
    """How many files in inbox/ the next run would take: what nothing can read is not counted."""
    inbox, suffixes = vault.root / "inbox", _suffixes(images)
    if not inbox.is_dir():
        return 0
    return sum(
        1
        for path in inbox.iterdir()
        if not path.name.startswith(".") and path.is_file() and _takes(path, suffixes)
    )


def scan_inbox(vault: Vault, queue: Queue, images: bool = False) -> ScanResult:
    """Move each dropped file to raw/inbox/ (its permanent home) and queue it from there; a link
    file has the links in it queued instead (every one: the run limits pace them). Images are
    taken only when `images` (an OCR model is configured); what cannot be read at all, a link file
    with no link included, is left in place and listed, never ignored silently."""
    result = ScanResult()
    inbox = vault.root / "inbox"
    dest_dir = vault.root / "raw" / "inbox"
    suffixes = _suffixes(images)
    for path in sorted(inbox.iterdir()):
        if path.name.startswith(".") or path.is_dir():
            continue
        if not _takes(path, suffixes):
            result.unsupported.append(path.name)
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        if _already_kept(dest_dir, path):
            path.unlink()  # the very same file again, under any name: nothing to keep
            result.duplicates += 1
            continue
        dest = free_path(dest_dir, path.name)  # a different file with the same name: keep both
        shutil.move(path, dest)
        if path.suffix.lower() == LINK_FILE_SUFFIX:
            result.enqueued += queue_links(vault, queue, _links(dest), origin="inbox")
            continue
        label = path.stem
        if path.suffix.lower() == ".md":
            label = str(
                parse_page(dest, dest.read_text(encoding="utf-8")).meta.get("title") or path.stem
            )
        if queue.add(str(dest), origin="inbox", label=label):
            result.enqueued += 1
    return result


def keep_original_clip(vault: Vault, target: str) -> Path | None:
    """A clip read from outside the vault's inbox is ingested as chrome-stripped text, so its
    original is copied unchanged into raw/inbox/ (a name that is taken gets `(2)`: raw is never
    overwritten). Not for what is already in raw/ or still waiting in inbox/, nor for a URL."""
    path = Path(target).expanduser()
    if path.suffix.lower() != ".md" or not path.is_file():
        return None
    resolved = path.resolve()
    if any(resolved.is_relative_to(vault.root / folder) for folder in ("raw", "inbox")):
        return None
    dest_dir = vault.root / "raw" / "inbox"
    if _already_kept(dest_dir, resolved):
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = free_path(dest_dir, path.name)
    shutil.copyfile(resolved, dest)
    return dest
