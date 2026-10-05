"""Is what the answer says in the pages it was given? A lexical check, no second model call.

Each sentence with facts in it must find its numbers, its proper names and most of its key words
in the text of the pages (accents, case, plurals and endings do not matter). A model can cite a real
page and still say what the page does not say: that is what this catches. It cannot tell a wrong
relation between words that are all present (the pages say A beat B, the answer says B beat A), so
a sentence that passes is "not contradicted by vocabulary", not "proven"."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from esbi_cli.ingest.retrieve import STOPWORDS
from esbi_cli.vault import fold

# Tuned on real llama3.2 answers over a scratch vault: see the pull request.
MISSING_SHARE = 0.5  # a sentence fails when this share of its key words is nowhere in the pages
MIN_MISSING = 2  # one unknown ordinary word is a synonym; names and numbers carry the strong signal
MIN_KEY_LENGTH = 5  # shorter lower-case words are mostly function words ("sobre", "with")
FUNCTION_WORDS = frozenset(
    """
    embargo after before between during through however because although according while there their
    sobre ademas aunque segun durante tiene tienen puede pueden tambien cada otro otra otros
    """.split()
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\[\"“¿¡(]*[A-ZÁÉÍÓÚÑ\d])|\n+")
_BULLET = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s+")
_LINK = re.compile(r"\[\[.*?\]\]")
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")
_ENDINGS = tuple(
    sorted(
        "ations ation ciones cion ments ment mente ings ing edly ed ies es s ly ions ion "
        "ado ada ados adas ido ida idos idas ando iendo aron ieron as os a o e".split(),
        key=len,
        reverse=True,
    )
)


@dataclass
class Unsupported:
    sentence: str
    missing: list[str]  # the numbers and words of the sentence found in none of the pages
    end: int = field(default=0, repr=False, compare=False)  # offset in the text just after it


def _stem(word: str) -> str:
    """A light stem on a folded word: one ending off, so `investigación` and `investigaciones`
    (or `constructed` and `construction`) meet. (Also cutting every word to 6 letters let
    unrelated words meet and missed a real unsupported claim in the measurement.)"""
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


def _number(token: str) -> str:
    """`1,200` and `1.200` are 1200; `3,5` is 3.5."""
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return re.sub(r"[.,]", "", token)
    return token.replace(",", ".")


def _words(text: str) -> tuple[set[str], set[str]]:
    """The numbers and the word stems of a text."""
    tokens = _TOKEN.findall(text)
    numbers = {_number(t) for t in tokens if t[0].isdigit()}
    return numbers, {_stem(fold(t)) for t in tokens if not t[0].isdigit()}


def _checked(sentence: str) -> list[tuple[str, str, bool]]:
    """(surface, stem or number, is_proper_or_number) for what a sentence claims: its numbers, its
    proper names (capitalised, not first) and its key words."""
    sentence = _LINK.sub(" ", _BULLET.sub("", sentence))
    claims = []
    for index, token in enumerate(_TOKEN.findall(sentence)):
        if token[0].isdigit():
            claims.append((_number(token), _number(token), True))
            continue
        plain = fold(token)
        proper = index > 0 and token[0].isupper() and len(plain) >= 3
        if plain in STOPWORDS or plain in FUNCTION_WORDS:
            continue
        if proper or len(plain) >= MIN_KEY_LENGTH:
            claims.append((token, _stem(plain), proper))
    return claims


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Where each sentence (or list item) of `text` starts and ends."""
    bounds, begin = [], 0
    for match in _SENTENCE_END.finditer(text):
        if not re.fullmatch(r"\s*\d+[.)]", text[begin : match.start()]):  # "1." heads its item
            bounds.append((begin, match.start()))
            begin = match.end()
    bounds.append((begin, len(text)))
    return bounds


def check_answer(
    text: str, evidence: Iterable[str], disclaimer: re.Pattern | None = None
) -> tuple[list[Unsupported], int]:
    """The sentences of `text` whose numbers, names or key words are not in the `evidence` texts,
    and how many sentences had something to check. A sentence that says the pages do not have the
    answer (`disclaimer` matches it) claims nothing about the world and is not checked."""
    found_numbers, found_stems = set(), set()
    for page in evidence:
        numbers, stems = _words(page)
        found_numbers |= numbers
        found_stems |= stems
    result, checked = [], 0
    for begin, end in sentence_spans(text):
        claims = _checked(text[begin:end])
        if not claims or (disclaimer and disclaimer.search(text[begin:end])):
            continue
        checked += 1
        missing = [
            (surface, key, strong)
            for surface, key, strong in claims
            if key not in (found_numbers if key[0].isdigit() else found_stems)
        ]
        loose = [c for c in claims if not c[2]]
        loose_missing = [c for c in missing if not c[2]]
        strong_missing = any(c[2] for c in missing)
        if strong_missing or (
            len(loose_missing) >= MIN_MISSING and len(loose_missing) / len(loose) >= MISSING_SHARE
        ):
            piece = text[begin:end]
            result.append(
                Unsupported(piece.strip(), [c[0] for c in missing], end=begin + len(piece.rstrip()))
            )
    return result, checked
