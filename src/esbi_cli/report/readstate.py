"""Read tracking: ticked checkboxes in the daily index notes mark sources as read, unticked ones undo it."""

import re
from datetime import date

from esbi_cli.vault import Vault, fold

_TICKED = re.compile(r"^\s*- \[[xX]\] \[\[([^\]|#]+)", re.MULTILINE)
_UNTICKED = re.compile(r"^\s*- \[ \] \[\[([^\]|#]+)", re.MULTILINE)


def sync_read_state(vault: Vault, today: date) -> list[str]:
    """Flip ticked sources from processed to read. Returns the titles newly marked read."""
    ticked: list[str] = []
    for note in sorted((vault.wiki / "daily").glob("*.md")):
        ticked += _TICKED.findall(note.read_text(encoding="utf-8"))

    newly_read: list[str] = []
    for title in dict.fromkeys(t.strip() for t in ticked):
        page = vault.find_page(title, ("sources",))
        if page is None or page.meta.get("status") != "processed":
            continue
        page.meta["status"] = "read"
        page.meta["read"] = today.isoformat()
        vault.write_page(page)
        newly_read.append(page.title)
    return newly_read


def sync_unread_state(vault: Vault) -> list[str]:
    """Put a read source back to processed when its checkbox is unticked in its own day's note.

    The checkbox of a source lives in the daily note of the day it was processed, and that note is
    a view of the state: a source marked read shows up ticked when it is regenerated, so an
    unticked box is the user's doing. A source with no box there (no note, or not listed) is left
    alone, and so is one that is ticked anywhere in that note. Call it after `sync_read_state`.
    Returns the titles put back."""
    put_back: list[str] = []
    for page in vault.iter_pages(("sources",)):
        note = vault.wiki / "daily" / f"{page.meta.get('processed')}.md"
        if page.meta.get("status") != "read" or not note.is_file():
            continue
        text = note.read_text(encoding="utf-8")
        ticked = {fold(t) for t in _TICKED.findall(text)}
        unticked = {fold(t) for t in _UNTICKED.findall(text)}
        if fold(page.title) in unticked and fold(page.title) not in ticked:
            page.meta["status"], page.meta["read"] = "processed", None
            vault.write_page(page)
            put_back.append(page.title)
    return put_back
