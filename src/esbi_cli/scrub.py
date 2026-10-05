"""What the worker lets through of text a model wrote. A source can tell the model to write
anything, and a small model often obeys, so the worker treats the text as plain prose: nothing in
it may make a viewer fetch or follow an address, run HTML, or point at a page that is not there.

An address is allowed only when the source itself contains it (so a link the source really made
survives, and data the model added to it, such as the titles of other pages, cannot ride along)."""

import re

from esbi_cli.links import WIKILINK_FULL

_MD_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\n]*)\)")
_ADDRESS = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.I)


def scrub(text: str, known_text: str, vault, hidden=frozenset()) -> tuple[str, int]:
    """`text` as plain prose, and how many addresses were cut from it.

    - no HTML (`<` becomes `&lt;`) and no image syntax (`![` becomes `[`: a remote image loads when
      the note is opened, and its address can carry other notes' text out);
    - a Markdown link or a bare address stays only if `known_text` contains that address;
    - a `[[link]]` stays only if it names a page that exists and is not in `hidden` (pages a
      public note must not point at); otherwise only its words stay."""
    text = text.replace("<", "&lt;").replace("![", "[")
    cut = 0

    def link(match: re.Match) -> str:
        nonlocal cut
        target = match[2].split(" ")[0]
        if target and target in known_text:
            return match[0]
        cut += 1
        return match[1]

    def address(match: re.Match) -> str:
        nonlocal cut
        url = match[0].rstrip(".,;:!?")
        if url in known_text:
            return match[0]
        cut += 1
        return ""

    def wikilink(match: re.Match) -> str:
        target = match[1].split("|")[0].split("#")[0].strip()
        page = vault.resolve_page(target)
        return match[0] if page and page.title not in hidden else (match[2] or target)

    text = _MD_LINK.sub(link, text)
    text = WIKILINK_FULL.sub(wikilink, text)
    return _ADDRESS.sub(address, text), cut
