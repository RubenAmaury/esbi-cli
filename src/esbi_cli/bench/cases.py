"""Benchmark inputs taken from the user's own vault, so results reflect their real material."""

from dataclasses import dataclass

from esbi_cli import lang
from esbi_cli.extract import ExtractedDoc
from esbi_cli.privacy import private_titles
from esbi_cli.vault import Vault, parse_page

MIN_SOURCE_CHARS = 500  # shorter snapshots say too little to compare models on


@dataclass
class IngestCase:
    name: str
    doc: ExtractedDoc


@dataclass
class AskCase:
    name: str
    question: str
    expected: str  # the page a good answer must cite


def _spread(items: list, n: int) -> list:
    """n items evenly spaced over the list (first and last included), deterministic."""
    if n >= len(items):
        return items
    if n == 1:
        return items[:1]
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def load_cases(vault: Vault, n: int) -> tuple[list[IngestCase], list[AskCase]]:
    snapshots = []
    for path in sorted((vault.root / "raw").glob("*.md")):
        page = parse_page(path, path.read_text(encoding="utf-8"))
        if (
            len(page.body) >= MIN_SOURCE_CHARS and page.meta.get("kind") != "email"
        ):  # email stays local
            doc = ExtractedDoc(
                title=str(page.meta.get("title") or path.stem),
                text=page.body,
                kind=str(page.meta.get("kind") or "article"),
                url=page.meta.get("url"),
            )
            snapshots.append(IngestCase(path.stem, doc))
    hidden = private_titles(vault)  # a benchmark may send these pages to a cloud model
    concepts = sorted(
        (p for p in vault.iter_pages(("concepts",)) if p.title not in hidden), key=lambda p: p.title
    )
    asks = [
        AskCase(p.title, lang.t(vault.language, "bench_question", title=p.title), p.title)
        for p in concepts
    ]
    return _spread(snapshots, n), _spread(asks, n)
