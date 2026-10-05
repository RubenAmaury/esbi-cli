"""Validate and apply an EditPlan to the vault. Only this module writes wiki pages."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path

from esbi_cli import lang
from esbi_cli.extract import ExtractedDoc
from esbi_cli.llm.schemas import ConceptEdit, Connection, EditPlan
from esbi_cli.privacy import private_sources
from esbi_cli.vault import Page, Vault, fold, safe_title, slugify


@dataclass
class ApplyResult:
    source_title: str
    source_path: Path
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    reviews: list[Path] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # LLM references to pages that don't exist
    unsupported_entities: list[str] = field(default_factory=list)  # named, but not in the source
    unsupported_terms: list[str] = field(default_factory=list)  # glossary terms not in the source
    trivial_terms: list[str] = field(
        default_factory=list
    )  # duplicates, generic words, no definition
    dropped_edges: int = 0  # diagram relations with an end that is not in the source or the note
    touched_paths: list[Path] = field(default_factory=list)


NOTE_FORMAT = 2  # 1 = the short summaries of milestones 1-8; 2 = the rich note (`sb reingest`)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _text(text: str) -> str:
    """Model-written text as plain text in a note: no HTML, and no image syntax. A remote image
    loads when the note is opened, and its address could carry other notes' text out; a prompt
    injected into a source can make the model write one."""
    return text.replace("<", "&lt;").replace("![", "[")


def _one_line(text: str, max_chars: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= max_chars else flat[: max_chars - 1].rstrip() + "…"


def _link(title: str) -> str:
    return f"[[{title}]]"


def save_raw(vault: Vault, doc: ExtractedDoc, title: str, today: date) -> Path:
    """Write the immutable raw snapshot(s) and return the markdown snapshot path."""
    # the content hash keeps two different sources from sharing (or overwriting) a raw file
    stem = f"{today.isoformat()}-{slugify(title)}-{content_hash(doc.text)[:8]}"
    raw_dir = vault.root / "raw"
    raw_dir.mkdir(exist_ok=True)
    if doc.pdf_bytes is not None:
        (raw_dir / f"{stem}.pdf").write_bytes(doc.pdf_bytes)
    if doc.image_bytes is not None:
        (raw_dir / f"{stem}{doc.image_suffix}").write_bytes(doc.image_bytes)
    md_path = vault._inside(raw_dir / f"{stem}.md")
    if md_path.exists():  # raw is immutable: never overwrite an earlier snapshot
        return md_path
    header = Page(
        md_path,
        {"title": title, "url": doc.url, "captured": today.isoformat(), "kind": doc.kind},
        doc.text,
    )
    vault.write_page(header)
    return md_path


_RESERVED = {"home", "index", "log", "lint", "schema"}
_DAILY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _unique_source_path(vault: Vault, title: str, url: str | None) -> Path:
    # a source called "Home" or "2026-10-03" would shadow the real page of that name in [[links]]
    reserved = fold(title) in _RESERVED or _DAILY.fullmatch(title.strip())
    if reserved or vault.find_page(title, ("concepts", "entities", "syntheses")):
        title = f"{title} {lang.t(vault.language, 'source_suffix')}"
    path = vault.page_path("sources", title)
    n = 2
    while path.exists():
        existing = vault.read_page(path)
        if url and existing.meta.get("url") == url:
            return path
        path = vault.page_path("sources", f"{title} ({n})")
        n += 1
    return path


def _upsert_concept(
    vault: Vault,
    edit: ConceptEdit,
    kind: str,
    source_title: str,
    today: date,
    result: ApplyResult,
    from_email: set[str] = frozenset(),
    public: bool = True,
) -> str | None:
    """Create the concept/entity page or append this source's contribution.

    Returns its title, or None if the edit was skipped (name clash with a source).
    """
    name = safe_title(edit.title)
    # Obsidian resolves [[links]] by filename across folders: a concept sharing a name with a
    # source would make every link to it ambiguous, so skip it.
    if not name or fold(name) == fold(source_title) or vault.find_page(name, ("sources",)):
        result.dropped.append(edit.title)
        return None
    existing = vault.find_page(edit.title, ("concepts", "entities", "syntheses"))
    section = f"## {lang.t(vault.language, 'from_source')} {_link(source_title)}\n{_text(edit.description.strip())}"
    if existing is None:
        title = name
        page = Page(
            vault.page_path(kind, title),
            {
                "type": "concept" if kind == "concepts" else "entity",
                "title": title,
                "aliases": sorted({a for a in edit.aliases if a and a != title}),
                "tags": [],
                "sources": [_link(source_title)],
                "updated": today.isoformat(),
                "summary": _text(_one_line(edit.description)),
            },
            f"# {title}\n\n{section}",
        )
        vault.write_page(page)
        result.created.append(title)
        result.touched_paths.append(page.path)
        return title

    sources_before = list(existing.meta.get("sources") or [])
    if public and sources_before and all(s in from_email for s in sources_before):
        # the page was born from email and its one-line summary is email text: a public source now
        # shares it, so the summary becomes the public source's description
        existing.meta["summary"] = _text(_one_line(edit.description))
    if _link(source_title) not in existing.body:
        existing.body = f"{existing.body}\n\n{section}"
    sources = list(existing.meta.get("sources") or [])
    if _link(source_title) not in sources:
        sources.append(_link(source_title))
    existing.meta["sources"] = sources
    aliases = set(existing.aliases) | {a for a in edit.aliases if a and a != existing.title}
    existing.meta["aliases"] = sorted(aliases)
    existing.meta["updated"] = today.isoformat()
    existing.meta.setdefault("summary", _text(_one_line(edit.description)))
    vault.write_page(existing)
    result.updated.append(existing.title)
    result.touched_paths.append(existing.path)
    return existing.title


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def _flat(text: str) -> str:
    """Case, accents and line breaks ignored: how quotes and terms are looked up in the source."""
    return " ".join(fold(text).split())


def _quotes(quotes: list[str], source_text: str) -> list[str]:
    """Only quotes that really are in the source: small models paraphrase and call it a quote."""
    haystack, kept = _flat(source_text), []
    for quote in quotes:
        q = quote.strip().strip('"«»“”').strip()
        heading = q.startswith(("_", "*", "#"))  # emphasis or a heading, not a sentence of the text
        if 25 <= len(q) <= 300 and not heading and _flat(q) in haystack and q not in kept:
            kept.append(q)
    return kept[:5]


_TRANSCRIPT_LINE = re.compile(r"^\*\*(\d+(?::\d{2}){1,2})\*\* · (.*)$", re.M)


def _at(doc: ExtractedDoc, needle: str) -> str:
    """For a video: ` ([m:ss](url&t=Ns))`, the moment its transcript says `needle`; else nothing."""
    if doc.kind != "video" or not (doc.url or "").startswith("http"):
        return ""
    wanted = _flat(needle)
    for stamp, line in _TRANSCRIPT_LINE.findall(doc.text):
        if wanted in _flat(line):
            parts = [int(p) for p in stamp.split(":")]
            seconds = sum(p * 60**i for i, p in enumerate(reversed(parts)))
            joiner = "&" if "?" in doc.url else "?"
            return f" ([{stamp}]({doc.url}{joiner}t={seconds}s))"
    return ""


def _label(text: str) -> str:
    """A diagram label that cannot break Mermaid: no quotes, brackets or line breaks."""
    flat = re.sub(r"[\[\]{}<>|]|-{2,}", " ", text.replace('"', "'"))
    return " ".join(flat.split())[:40].strip()


_STOPWORDS = {w for entry in lang.LANGUAGES.values() for w in entry["stopwords"].split()}


def _stems(name: str) -> set[str]:
    """The content words of a name cut to five letters, so "modelos" and "modelo" are one."""
    return {w[:5] for w in re.findall(r"\w{3,}", fold(name)) if w not in _STOPWORDS}


def _supported_by(names: list[str], source_text: str) -> Callable[[str], bool]:
    """Is an end of a relation real? It is when the source says it (whole words), or when it is a
    name of the note (a concept, entity, term or alias), even translated or inflected: all its
    content words are among that name's. Anything else is the model's invention."""
    known = [(fold(n), _stems(n)) for n in names]

    def supported(end: str) -> bool:
        folded, stems = fold(end), _stems(end)
        return bool(
            re.search(rf"(?<!\w){re.escape(folded)}(?!\w)", source_text)
            or any(folded == f or (stems and stems <= s) for f, s in known)
        )

    return supported


def _mermaid(relations, supported: Callable[[str], bool]) -> tuple[str, int]:
    """The concept map, drawn by code from the extracted relations so it is always valid, and the
    number of relations dropped because an end is not `supported` (small models invent them)."""
    ids: dict[str, str] = {}
    edges, dropped = [], 0
    for r in relations:
        a, b, rel = _label(r.a), _label(r.b), _label(r.relation)
        if not (a and b and rel) or fold(a) == fold(b):
            continue
        if not (supported(a) and supported(b)):
            dropped += 1
            continue
        ends = []
        for name in (a, b):
            if name in ids:
                ends.append(ids[name])
            else:
                ids[name] = f"n{len(ids) + 1}"
                ends.append(f'{ids[name]}["{name}"]')  # defined where it first appears
        edges.append(f'  {ends[0]} -- "{rel}" --> {ends[1]}')
    if len(edges) < 2:
        return "", dropped
    return "```mermaid\ngraph LR\n" + "\n".join(edges) + "\n```", dropped


def _figures_md(vault: Vault, doc: ExtractedDoc, source_title: str) -> list[str]:
    """PDF figures are copied into attachments/<source>/ and embedded; web images are linked."""
    blocks, folder = [], vault.root / "attachments" / slugify(source_title)
    for n, fig in enumerate(doc.figures, 1):
        path = vault._inside(folder / f"fig-{n}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fig.data)
        fallback = lang.t(vault.language, "figure" if fig.page else "image")  # page 0: a picture
        caption = " ".join((fig.caption or fallback).split())
        rel = path.relative_to(vault.root).as_posix()
        # a dropped image has no page
        where = f" ({lang.t(vault.language, 'page_abbr')} {fig.page})" if fig.page else ""
        blocks.append(f"![[{rel}|600]]\n*{caption}{where}*")
    for alt, url in doc.image_links:  # page text: it must not break out of the Markdown into HTML
        alt = re.sub(r"[\[\]<>\n]", " ", alt).strip() or lang.t(vault.language, "image")
        url = url.strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29")
        if re.match(r"https?://[^<>\"\s]+$", url):
            blocks.append(f"![{alt}]({url})")
    return ["\n\n".join(blocks)] if blocks else []


def _complete(text: str) -> str:
    """A model cut off by its token limit leaves half a sentence: end at the last whole one."""
    text = text.rstrip()
    if not text or text[-1] in '.!?…"»)':
        return text
    cut = max(text.rfind(c) for c in ".!?…")
    return text[: cut + 1] if cut >= len(text) * 0.5 else text


def _term_key(term: str) -> str:
    """Two spellings of one glossary entry share a key: case, accents and punctuation do not count,
    and neither does the letter order of an acronym ("IA" and "AI" are one term in two languages)."""
    words = re.sub(r"\W+", " ", fold(term)).strip()
    return "".join(sorted(words)) if term.isupper() and len(words) <= 5 else words


def _glossary(
    vault: Vault, terms, doc: ExtractedDoc, result: ApplyResult
) -> tuple[list[str], list[str]]:
    """Terms as they appear in the source, linked to their concept page when there is one; and the
    names kept. Dropped: terms that are not in the source, duplicates, generic words, and entries
    whose definition says it has none."""
    entry = lang.get(vault.language)
    disclaimer, generic = (
        re.compile(entry["disclaimers"], re.I),
        set(entry["generic_terms"].split()),
    )
    folded, lines, kept, seen = fold(doc.text), [], [], set()
    for t in terms:
        term = t.term.strip(" *_`#")  # a PDF or Markdown source leaves its markup around a term
        if fold(term) not in folded or lang.wrong_language(t.definition, vault.language, 2):
            result.unsupported_terms.append(t.term)
            continue
        key = _term_key(term)
        if (
            key in seen
            or len(term) < 2  # a lone letter is a symbol of a formula, not a term
            or fold(term) in generic
            or disclaimer.search(t.definition)
        ):
            result.trivial_terms.append(t.term)
            continue
        seen.add(key)
        kept.append(term)
        page = vault.find_page(term, ("concepts", "entities"))
        name = f"[[{page.title}]]" if page else term
        lines.append(f"- **{_text(name)}**{_at(doc, term)}: {_text(t.definition.strip())}")
    return lines, kept


def apply_plan(
    vault: Vault,
    plan: EditPlan,
    doc: ExtractedDoc,
    raw_path: Path,
    today: date,
    file_hash: str,
    captured: date | None = None,
    flag_contradictions: bool = False,
    connections: list[Connection] | None = None,
    coverage_note: str | None = None,  # a line saying which part of the source was not read
) -> ApplyResult:
    L = partial(lang.t, vault.language)
    title = safe_title(plan.title) or safe_title(doc.title) or L("untitled")
    source_path = _unique_source_path(vault, title, doc.url)
    source_title = source_path.stem
    result = ApplyResult(source_title=source_title, source_path=source_path)
    from_email = {_link(t) for t in private_sources(vault)}

    concept_titles = [
        t
        for e in plan.concepts
        if (
            t := _upsert_concept(
                vault, e, "concepts", source_title, today, result, from_email, doc.kind != "email"
            )
        )
    ]
    # Proper nouns must appear in the source: small models copy names from the "existing pages"
    # context into unrelated sources. (Concepts may be abstractions the text never spells out.)
    folded_text = fold(doc.text)
    entities = []
    for e in plan.entities:
        names = {fold(n) for n in (e.title, *e.aliases) if n}
        if any(n in folded_text for n in names):
            entities.append(e)
        else:
            result.unsupported_entities.append(e.title)
    entity_titles = [
        t
        for e in entities
        if (
            t := _upsert_concept(
                vault, e, "entities", source_title, today, result, from_email, doc.kind != "email"
            )
        )
    ]

    related: list[str] = []
    for name in plan.related_pages:
        page = vault.resolve_page(name)
        if page is None:
            result.dropped.append(name)
        elif page.title != source_title and _link(page.title) not in related:
            related.append(_link(page.title))

    warnings: list[str] = []
    for c in plan.contradictions if flag_contradictions else []:
        target = vault.resolve_page(c.page)
        if target is None:
            result.dropped.append(c.page)
            continue
        callout = "> [!warning] " + L(
            "contradiction_callout",
            date=today.isoformat(),
            link=_link(source_title),
            note=c.note.strip(),
        )
        target.body = f"{target.body}\n\n{callout}"
        vault.write_page(target)
        result.touched_paths.append(target.path)
        warnings.append(f"{_link(target.title)}: {c.note.strip()}")
    if warnings:
        review = Page(
            vault.page_path(
                "review",
                L("contradiction_review_name", date=today.isoformat(), source=source_title),
            ),
            {"type": "review", "kind": "contradiction", "source": _link(source_title)},
            f"# {L('contradiction_review_title', link=_link(source_title))}\n\n"
            f"{_bullets(warnings)}\n\n{L('contradiction_review_footer')}",
        )
        vault.write_page(review)
        result.reviews.append(review.path)
        result.touched_paths.append(review.path)

    connection_lines, connected = [], set(concept_titles) | set(entity_titles)
    for c in connections or []:
        page = vault.resolve_page(c.page)
        if page is None or page.title == source_title:
            result.dropped.append(c.page)
            continue
        if page.title in connected:  # listed once; and a page this note extends is under Conceptos
            continue
        connected.add(page.title)
        related = [r for r in related if r != _link(page.title)]  # shown once, with its reason
        connection_lines.append(
            f"- {_link(page.title)}: **{_text(c.relation.strip())}**. {_text(c.why.strip())}"
        )

    body = [f"# {source_title}"]
    if doc.url:
        body += ["", f"> {L('original_source')}: {doc.url}"]
    if coverage_note:
        body += ["", f"> [!warning] {_text(coverage_note)}"]

    def add(heading: str, content: str | list[str]) -> None:
        """One `## heading` section; empty ones are left out."""
        text = content if isinstance(content, str) else "\n".join(content)
        if text.strip():
            body.extend(["", f"## {heading}", text.strip()])

    add(L("summary"), _text(plan.summary))
    add(L("abstract"), _text(_complete(plan.abstract)))
    if plan.insights:
        add(
            L("insights"),
            [f"- **{_text(i.idea.strip())}** {_text(i.why.strip())}" for i in plan.insights],
        )
    else:
        add(L("key_points"), _bullets([_text(p) for p in plan.key_points]))
    glossary, kept_terms = _glossary(vault, plan.terms, doc, result)
    add(L("terms"), glossary)
    add(
        L("quotes"),
        "\n\n".join(f'> "{_text(q)}"{_at(doc, q)}' for q in _quotes(plan.quotes, doc.text)),
    )
    names = [*concept_titles, *entity_titles, *kept_terms]
    names += [a for e in (*plan.concepts, *plan.entities) for a in e.aliases]
    diagram, result.dropped_edges = _mermaid(plan.relations, _supported_by(names, folded_text))
    add(L("diagram"), diagram)
    add(L("figures"), _figures_md(vault, doc, source_title))
    add(L("connections"), connection_lines)
    add(L("open_questions"), _bullets([_text(q) for q in plan.open_questions]))
    add(L("concepts"), _bullets([_link(t) for t in concept_titles]))
    add(L("entities"), _bullets([_link(t) for t in entity_titles]))
    add(L("related"), _bullets(related))
    add(L("contradictions"), _bullets(warnings))

    meta = {
        "type": "source",
        "title": source_title,
        "url": doc.url,
        "kind": doc.kind,
        "status": "processed",
        "captured": (captured or today).isoformat(),
        "processed": today.isoformat(),
        "read": None,
        "tags": [t.lstrip("#") for t in plan.tags],
        "summary": _one_line(plan.one_liner),
        "raw": raw_path.relative_to(vault.root).as_posix(),
        "content_hash": file_hash,
        "format": NOTE_FORMAT,
    }
    if doc.stripped_lines:
        meta["stripped_lines"] = doc.stripped_lines  # audit: page chrome removed before reading
    vault.write_page(Page(source_path, meta, "\n".join(body)))
    result.created.insert(0, source_title)
    result.touched_paths.append(source_path)
    return result
