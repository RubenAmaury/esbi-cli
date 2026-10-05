"""Split a long source into chunks a small model can read, so it sees the whole document
and not just its first few pages."""

import re

_REFERENCES = re.compile(
    r"^[#*\s]*(references|referencias|bibliography|bibliografía)[\s*:]*$", re.I | re.M
)


def _cut_references(text: str) -> str:
    """Drop a trailing bibliography: it is long, useless to summarize, and eats chunks."""
    for match in reversed(list(_REFERENCES.finditer(text))):
        if match.start() > len(text) * 0.5:
            return text[: match.start()].rstrip()
    return text


def split_chunks(text: str, size_chars: int = 8000) -> list[str]:
    """Chunks of at most `size_chars` characters cut between paragraphs, all of the source."""
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", _cut_references(text)):
        para = para.strip()
        if not para:
            continue
        while len(para) > size_chars:  # a single monster paragraph: cut it hard
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:size_chars])
            para = para[size_chars:]
        if current and len(current) + len(para) + 2 > size_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks
