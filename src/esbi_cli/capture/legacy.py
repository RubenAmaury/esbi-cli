"""One-time import of an older notes folder: Links/DD-MM-YYYY.md files (one [url] per line) and PDFs/."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from esbi_cli.queue import Queue

_URL = re.compile(r"https?://[^\s\]\)>]+")


@dataclass
class ImportResult:
    added: int = 0
    duplicates: int = 0


def _file_date(path: Path) -> date | None:
    """The day a legacy links file stands for, from its DD-MM-YYYY name."""
    try:
        return datetime.strptime(path.stem, "%d-%m-%Y").date()
    except ValueError:
        return None


def _link_file_order(path: Path) -> tuple[int, date | str]:
    """Chronological by file name; oddly named files go last."""
    day = _file_date(path)
    return (0, day) if day else (1, path.stem)


def import_legacy(legacy_vault: Path, queue: Queue) -> ImportResult:
    """Queue every URL and PDF of the legacy vault. Read-only: never touches the old files."""
    result = ImportResult()

    def add(target: str, **details) -> None:
        if queue.add(target, origin="legacy", **details):
            result.added += 1
        else:
            result.duplicates += 1

    for links_file in sorted((legacy_vault / "Links").glob("*.md"), key=_link_file_order):
        saved_on = _file_date(links_file)
        for url in _URL.findall(links_file.read_text(encoding="utf-8")):
            add(url, captured=saved_on)  # oldest file first, so the first save date wins
    for pdf in sorted((legacy_vault / "PDFs").glob("*.pdf")):
        add(str(pdf.resolve()), label=pdf.stem)
    return result
