"""Deterministic wiki health checks. They only report: nothing is ever fixed silently."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import combinations

from esbi_cli.links import link_targets
from esbi_cli.vault import Vault, fold


@dataclass
class Issue:
    kind: str  # orphan | broken-link | missing-field | unlinked-mention | near-duplicate | missing-concept
    page: str
    detail: str


@dataclass
class LintReport:
    issues: list[Issue] = field(default_factory=list)


def _orphans(vault: Vault) -> list[Issue]:
    pages = list(vault.iter_pages())
    linked: set[str] = set()
    for page in pages:
        linked |= {fold(t) for t in link_targets(page.body)} - {fold(page.title)}
    return [
        Issue("orphan", p.title, "no page links here")
        for p in pages
        if fold(p.title) not in linked and not any(fold(a) in linked for a in p.aliases)
    ]


def _resolvable_names(vault: Vault) -> set[str]:
    """Everything a [[link]] can point at: any note in the vault (Home, daily, review...) or an alias."""
    notes = [*vault.root.glob("*.md"), *vault.wiki.rglob("*.md")]
    names = {fold(n.stem) for n in notes}
    for page in vault.iter_pages():
        names |= {fold(a) for a in page.aliases}
    return names


def _broken_links(vault: Vault) -> list[Issue]:
    known = _resolvable_names(vault)
    issues = []
    for page in vault.iter_pages():
        for target in dict.fromkeys(link_targets(page.body)):
            if (
                fold(target) not in known and not (vault.root / target).is_file()
            ):  # an embedded file
                issues.append(Issue("broken-link", page.title, f"[[{target}]]"))
    return issues


def _missing_fields(vault: Vault) -> list[Issue]:
    return [
        Issue("missing-field", page.title, field_name)
        for page in vault.iter_pages()
        for field_name in ("title", "summary")
        if not page.meta.get(field_name)
    ]


MIN_MENTION_CHARS = 4  # shorter names ("IA") match far too much to be a useful suggestion


def _mentions(names: list[str], body: str, folded_body: str) -> bool:
    """Is any of `names` written in the text?

    Multi-word names match ignoring case and accents. A single word matches only exactly as
    written: common words ("enfoque") appear lowercase everywhere and would flood the report.
    """
    for name in names:
        if " " in name:
            found = re.search(rf"(?<!\w){re.escape(fold(name))}(?!\w)", folded_body)
        else:
            found = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", body)
        if found:
            return True
    return False


def _unlinked_mentions(vault: Vault) -> list[Issue]:
    """A concept/entity is named in another page's text but that page never links to it."""
    pages = list(vault.iter_pages())
    folded = {p.path: fold(p.body) for p in pages}
    vault.index.sync()  # once, not for each of the thousands of names below
    by_path = {str(p.path.resolve()): p for p in pages}
    linked = {p.path: {fold(t) for t in link_targets(p.body)} for p in pages}  # once per page
    issues = []
    for target in (p for p in pages if p.kind in ("concepts", "entities")):
        names = [
            n.strip() for n in (target.title, *target.aliases) if len(fold(n)) >= MIN_MENTION_CHARS
        ]
        if not names:
            continue
        own_names = {fold(target.title)} | {fold(a) for a in target.aliases}
        paths = vault.index.body_matches(names, sync=False)  # only these can mention it
        hosts = pages if paths is None else [by_path[x] for x in sorted(paths) if x in by_path]
        for host in hosts:
            if host.path == target.path:
                continue
            if linked[host.path] & own_names:
                continue
            if _mentions(names, host.body, folded[host.path]):
                issues.append(Issue("unlinked-mention", host.title, target.title))
    return issues


SIMILAR_TITLES = 0.88  # "agente"/"agentes" ~ 0.92; "harness interface"/"harness mechanisms" ~ 0.6


def _near_duplicates(vault: Vault) -> list[Issue]:
    """Concept/entity pairs that look like the same idea: similar titles, or a shared name/alias.

    Similar titles differ by at most 3 characters in length, so each page is compared only with
    those in that length window, and shared names come from a name -> pages table: no all-pairs scan.
    """
    pages = sorted(
        vault.iter_pages(("concepts", "entities")), key=lambda p: (fold(p.title), p.title)
    )
    names = {p.path: {fold(n) for n in (p.title, *p.aliases)} for p in pages}
    pairs: set[tuple[int, int]] = set()
    by_name: dict[str, list[int]] = {}
    for i, page in enumerate(pages):
        for name in names[page.path]:
            by_name.setdefault(name, []).append(i)
    for owners in by_name.values():
        pairs.update(combinations(sorted(owners), 2))
    by_length = sorted(range(len(pages)), key=lambda i: len(fold(pages[i].title)))
    folded = [fold(p.title) for p in pages]
    for n, i in enumerate(by_length):
        for j in by_length[n + 1 :]:
            if len(folded[j]) - len(folded[i]) > 3:
                break
            matcher = SequenceMatcher(None, folded[i], folded[j])
            # the two cheap bounds never rule out a true match, so the answer is the same
            if (
                matcher.real_quick_ratio() >= SIMILAR_TITLES
                and matcher.quick_ratio() >= SIMILAR_TITLES
                and matcher.ratio() >= SIMILAR_TITLES
            ):
                pairs.add((min(i, j), max(i, j)))
    return [Issue("near-duplicate", pages[a].title, pages[b].title) for a, b in sorted(pairs)]


_GLOSSARY_TERM = re.compile(
    r"^- \*\*([^\[\]*]+)\*\*:", re.M
)  # an unlinked term: it has no page yet


def _missing_concepts(vault: Vault) -> list[Issue]:
    """Glossary terms two or more sources define, with no concept or entity page of their own."""
    users: dict[str, tuple[str, list[str]]] = {}
    for source in vault.iter_pages(("sources",)):
        for term in {t.strip() for t in _GLOSSARY_TERM.findall(source.body)}:
            name, titles = users.setdefault(fold(term), (term, []))
            titles.append(source.title)
    return [
        Issue("missing-concept", name, ", ".join(titles))
        for key, (name, titles) in sorted(users.items())
        if len(titles) >= 2 and vault.find_page(name, ("concepts", "entities")) is None
    ]


def lint_vault(vault: Vault) -> LintReport:
    return LintReport(
        issues=[
            *_orphans(vault),
            *_broken_links(vault),
            *_missing_fields(vault),
            *_unlinked_mentions(vault),
            *_near_duplicates(vault),
            *_missing_concepts(vault),
        ]
    )
