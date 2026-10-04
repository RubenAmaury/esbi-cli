"""`sb reingest`: rebuild source notes from the saved raw files, keeping what the user did to them."""

import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from esbi_cli.config import Config
from esbi_cli.extract import ExtractedDoc, ExtractError
from esbi_cli.extract.image import IMAGE_SUFFIXES, image_figure, to_png
from esbi_cli.extract.pdf import extract_pdf_bytes
from esbi_cli.gitops import commit_vault
from esbi_cli.ingest.apply import NOTE_FORMAT
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.llm.adapter import LLM, LLMError, LLMTimeout
from esbi_cli.privacy import section_pattern
from esbi_cli.vault import Page, Vault, fold, slugify

KEPT = ("status", "read", "content_hash")  # what the user (or dedupe) owns: never rebuilt


@dataclass
class ReingestResult:
    done: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (title, why)
    failed: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)  # (title, what went wrong)
    stopped: bool = False  # the model went away; run again to resume
    tag: str | None = None


def _raw_doc(vault: Vault, note: Page) -> ExtractedDoc:
    """The source as it was saved: the PDF (re-extracted, so figures come back) or the snapshot."""
    raw = vault.root / str(note.meta.get("raw") or "")
    if not note.meta.get("raw") or not raw.is_file():
        raise ExtractError(f"the file is missing from raw/ ({note.meta.get('raw')})")
    snap = vault.read_page(raw)
    doc = ExtractedDoc(
        note.title, snap.body, note.meta.get("kind") or "article", note.meta.get("url")
    )
    pdf = raw.with_suffix(".pdf")
    if pdf.is_file():
        data = pdf.read_bytes()
        try:
            doc = extract_pdf_bytes(data, note.title)
            doc.url = note.meta.get("url")
        except ExtractError:  # a scanned PDF: the snapshot holds the text the OCR model read
            doc.pdf_bytes = data  # still tells the privacy rules whether it came from a mail
    for suffix in IMAGE_SUFFIXES:  # a picture note: show the original again, no new OCR
        if (image := raw.with_suffix(suffix)).is_file():
            doc.figures = [image_figure(to_png(image.read_bytes(), image.name))]
    return doc


def _forget(vault: Vault, note: Page) -> None:
    """Remove what this source added elsewhere; concept pages nobody else cites are deleted."""
    link = f"[[{note.title}]]"
    section = section_pattern(note.title)
    for page in vault.iter_pages(("concepts", "entities", "syntheses")):
        sources = list(page.meta.get("sources") or [])
        if link not in sources:
            continue
        sources.remove(link)
        if not sources and page.meta.get("type") in ("concept", "entity"):
            page.path.unlink()
            continue
        page.meta["sources"] = sources
        page.body = section.sub("", page.body).strip()
        vault.write_page(page)
    note.path.unlink()
    shutil.rmtree(vault.root / "attachments" / slugify(note.title), ignore_errors=True)


def _tag_before(vault: Vault, today: date) -> str:
    """One command to undo the whole rebuild: `git reset --hard <tag>` in the vault."""
    commit_vault(vault.root, "chore: state before reingest")
    tag = f"pre-reingest-{today.isoformat()}"
    # an existing tag means this is a resumed run: the first tag is the true "before"
    subprocess.run(["git", "tag", tag], cwd=vault.root, capture_output=True)
    return tag


def reingest_all(
    vault: Vault,
    llm: LLM,
    synth_llm: LLM | None,
    cfg: Config,
    *,
    today: date | None = None,
    all_sources: bool = False,
    private_llm: LLM | None = None,
    only: list[str] | None = None,
    on_progress: Callable[[str], None] = lambda _: None,
) -> ReingestResult:
    """Rebuild every note that is not yet in the current format (or all of them), one commit each.

    Notes carry `format: 2` once rebuilt, so an interrupted run resumes where it stopped.
    """
    today = today or date.today()
    result = ReingestResult()
    wanted = [fold(t) for t in only or []]  # naming notes means "these, whatever their format"

    def selected(note: Page) -> bool:
        if wanted:
            return any(w in fold(note.title) for w in wanted)
        return all_sources or note.meta.get("format") != NOTE_FORMAT

    todo = [n for n in vault.iter_pages(("sources",)) if selected(n)]
    if not todo:
        return result
    result.tag = _tag_before(vault, today)
    started = time.monotonic()
    for n, note in enumerate(todo, 1):
        left = ""
        if n > 1:  # the pace of the notes done so far is the best guess for the rest
            minutes = (time.monotonic() - started) / (n - 1) * (len(todo) - n + 1) / 60
            left = f" (~{minutes:.0f} min left)"
        on_progress(f"[{n}/{len(todo)}] {note.title}{left}")
        try:
            doc = _raw_doc(vault, note)
        except ExtractError as exc:
            result.skipped.append((note.title, str(exc)))
            continue
        try:
            done = ingest(
                note.title,
                vault=vault,
                llm=llm,
                synth_llm=synth_llm,
                private_llm=private_llm,
                cfg=cfg,
                force=True,
                extractor=lambda _, d=doc: d,
                today=today,
                on_step=lambda step: on_progress(f"    ... {step}"),
                keep_title=note.title,
                raw_path=vault.root / note.meta["raw"],
                before_write=lambda note=note: _forget(vault, note),
            )
        except Exception as exc:  # one bad source must not stop the rebuild
            if isinstance(exc, LLMError) and not isinstance(exc, LLMTimeout):
                result.stopped = True  # the model is the problem, not this source: resume later
                break
            result.failed.append((note.title, f"{type(exc).__name__}: {exc}"))
            continue
        result.warnings += [(note.title, w) for w in done.warnings]
        rebuilt = vault.read_page(done.applied.source_path)
        for key in KEPT:
            rebuilt.meta[key] = note.meta.get(key)
        rebuilt.meta["captured"] = note.meta.get("captured", rebuilt.meta["captured"])
        rebuilt.meta["tags"] = sorted({*(note.meta.get("tags") or []), *rebuilt.meta["tags"]})
        vault.write_page(rebuilt)
        commit_vault(vault.root, f"reingest: {done.applied.source_title}")
        result.done.append(done.applied.source_title)
    return result
