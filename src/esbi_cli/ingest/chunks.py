"""Split a long source into chunks a small model can read, so it sees the whole document
and not just its first few pages."""

import re

_REFERENCES = re.compile(
    r"^[#*\s]*(references|referencias|bibliography|bibliografía)[\s*:]*$", re.I | re.M
)
HEAD, TAIL = 3, 2  # sampling keeps the start (abstract, intro) and the end (conclusions)


def _cut_references(text: str) -> str:
    """Drop a trailing bibliography: it is long, useless to summarize, and eats chunks."""
    for match in reversed(list(_REFERENCES.finditer(text))):
        if match.start() > len(text) * 0.5:
            return text[: match.start()].rstrip()
    return text


def _sample(chunks: list[str], n: int) -> list[str]:
    if len(chunks) <= n:
        return chunks
    middle, k = chunks[HEAD:-TAIL], n - HEAD - TAIL
    step = (len(middle) - 1) / (k - 1) if k > 1 else 0
    return chunks[:HEAD] + [middle[round(i * step)] for i in range(k)] + chunks[-TAIL:]


def split_chunks(text: str, size: int = 8000, max_chunks: int = 16) -> list[str]:
    """Chunks of at most `size` characters cut between paragraphs; at most `max_chunks` of them
    (a huge source is sampled: first, last, and evenly spread in between)."""
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", _cut_references(text)):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:  # a single monster paragraph: cut it hard
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:size])
            para = para[size:]
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return _sample(chunks, max_chunks)
