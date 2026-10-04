"""Find existing wiki pages likely related to a new source (SQLite FTS5, built in memory)."""

import re
from collections import Counter
from dataclasses import dataclass

from esbi_cli.vault import Vault, fold

STOPWORDS = frozenset(
    """
    that this with from have they their there which would about into than then them these those
    were will been being also more most other some such only over very when what where while who
    para como pero esta este estos estas esto entre sobre desde hasta cuando donde porque tambien
    son sus los las del una uno unos unas por con que mas muy sin ser han hay fue era sido
    the and for are was not but you your can has had its our out all any how why
    """.split()
)


@dataclass
class Candidate:
    title: str
    kind: str
    one_liner: str


def _clean(words) -> list[str]:
    """Search words from the model: letters and digits only, 3 characters or more."""
    cleaned = (re.sub(r"[^a-z0-9]", "", fold(w)) for w in words)
    return [w for w in cleaned if len(w) >= 3]


def keywords(text: str, n: int = 20) -> list[str]:
    tokens = re.findall(r"[a-z]{4,}", fold(text))
    counts = Counter(t for t in tokens if t not in STOPWORDS)
    return [word for word, _ in counts.most_common(n)]


def find_candidates(
    vault: Vault,
    text: str,
    max_results: int = 8,
    exclude: frozenset[str] | set[str] = frozenset(),
    extra: list[str] = (),
    private: bool = False,
) -> list[Candidate]:
    """Pages related to `text`: keyword matches (`extra` are search words added to the ones taken
    from the text: a rewritten question brings the other language's words), fused with the pages
    closest in meaning when the vault has an embedder. `private`: `text` is email, so a remote
    embedder is not asked about it."""
    words = list(dict.fromkeys([*keywords(text), *_clean(extra)]))
    if not words and vault.embedder is None:
        return []
    return [
        Candidate(title, kind, summary)
        for title, kind, summary in vault.index.search(
            words, max_results, exclude, query=text, private=private
        )
    ]
