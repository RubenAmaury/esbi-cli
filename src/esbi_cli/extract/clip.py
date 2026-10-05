"""Markdown notes, typically Obsidian Web Clipper output: the clipped body is the content."""

import re
from pathlib import Path

from esbi_cli.extract import ExtractedDoc, ExtractError, plain_address
from esbi_cli.vault import parse_page

KINDS = ("article", "paper", "email", "video")
MIN_CHARS = 40  # social posts are short; anything below this is an empty clip


def extract_clip(path: Path) -> ExtractedDoc:
    page = parse_page(path, path.read_text(encoding="utf-8"))
    text = page.body.strip()
    if len(text) < MIN_CHARS:
        raise ExtractError(f"{path.name} has almost no text ({len(text)} chars)")
    claimed = page.meta.get("source") or page.meta.get("url")
    url = plain_address(claimed)
    warnings = [] if url or not claimed else ["Ignored the source address: it is not a plain URL."]
    title = str(page.meta.get("title") or path.stem).strip()
    kind = page.meta.get("kind")
    if (
        kind == "video"
    ):  # the Clipper writes one transcript line per row: make each its own paragraph
        text = re.sub(r"\n(?=\*\*\d+(?::\d{2}){1,2}\*\* · )", "\n\n", text)
    return ExtractedDoc(
        title=title,
        text=text,
        kind=kind if kind in KINDS else "article",
        url=url,
        warnings=warnings,
    )
