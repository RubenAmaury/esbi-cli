"""Wikilink parsing shared by the daily index and lint."""

import re

WIKILINK = re.compile(r"\[\[([^\]|#]+)")
WIKILINK_FULL = re.compile(r"\[\[([^\]]+?)(?:\|([^\]]+))?\]\]")  # group 2: the shown text


def link_targets(text: str) -> list[str]:
    """Page names linked from text: `[[Title]]`, `[[Title|alias]]` and `[[Title#Heading]]` all give Title."""
    return [t.strip() for t in WIKILINK.findall(text)]
