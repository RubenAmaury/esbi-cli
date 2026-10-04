"""Read tracking: ticked checkboxes in the daily index notes mark sources as read."""

import re
from datetime import date

from esbi_cli.vault import Vault

_TICKED = re.compile(r"^\s*- \[[xX]\] \[\[([^\]|#]+)", re.MULTILINE)


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
