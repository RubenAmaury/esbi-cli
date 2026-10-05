"""Single-source ingest, end to end."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import partial
from pathlib import Path

from esbi_cli import lang
from esbi_cli.config import Config
from esbi_cli.extract import ExtractedDoc, extract_source
from esbi_cli.ingest.apply import ApplyResult, apply_plan, content_hash, save_raw
from esbi_cli.ingest.chunks import split_chunks
from esbi_cli.ingest.connect import connect
from esbi_cli.ingest.digest import aggregate, make_digest
from esbi_cli.ingest.plan import build_prompt, make_plan
from esbi_cli.ingest.read import read_chunks
from esbi_cli.ingest.retrieve import find_candidates
from esbi_cli.interrupts import deferred
from esbi_cli.llm.adapter import LLM
from esbi_cli.llm.schemas import EditPlan
from esbi_cli.mail.fetch import is_mail_file
from esbi_cli.privacy import PrivacyError, email_touched, private_titles, sends_text_out
from esbi_cli.report.index_md import rebuild_index
from esbi_cli.vault import Vault


@dataclass
class IngestResult:
    status: str  # ingested | skipped | dry-run
    doc: ExtractedDoc
    plan: EditPlan | None = None
    applied: ApplyResult | None = None
    existing_title: str | None = None  # set when skipped as duplicate
    warnings: list[str] = field(default_factory=list)


def ingest(
    target: str,
    *,
    vault: Vault,
    llm: LLM,
    cfg: Config,
    force: bool = False,
    dry_run: bool = False,
    extractor: Callable[[str], ExtractedDoc] = extract_source,
    today: date | None = None,
    captured: date | None = None,
    synth_llm: LLM | None = None,
    private_llm: LLM | None = None,
    on_step: Callable[[str], None] | None = None,
    keep_title: str | None = None,
    raw_path: Path | None = None,
    before_write: Callable[[], None] | None = None,
    from_email: bool = False,
) -> IngestResult:
    """`keep_title`, `raw_path` and `before_write` serve `sb reingest`: the rebuilt note keeps its
    title (links to it stay valid) and its raw snapshot, and the old note is cleared only once the
    new plan exists, so a model failure leaves the old note untouched. `from_email` marks a source
    reached through a link in a mail: it is email to every privacy rule, whatever its page is."""
    today = today or date.today()
    vault.validate()
    doc = extractor(target)
    file_hash = content_hash(doc.text)

    if not force:
        dup = (doc.url and vault.find_source("url", doc.url)) or vault.find_source(
            "content_hash", file_hash
        )
        if dup:
            return IngestResult("skipped", doc, existing_title=dup.title)

    synth_llm = synth_llm or llm  # the stronger model, if configured, writes the synthesis
    attachment = doc.pdf_bytes or doc.image_bytes
    if from_email or (attachment and is_mail_file(vault, attachment)):
        doc.kind = "email"  # what came with or through a mail is email to the privacy rules
    hidden: set[str] = set()  # pages a cloud model must not be told about
    blank: set[str] = set()  # pages it may be told about by title only
    # a public note is never connected to email, even by a local model: the connection text could
    # quote email, and public notes are what a cloud model later reads
    no_connect: set[str] = set()
    if doc.kind == "email":
        if private_llm is not None:
            if sends_text_out(private_llm):
                raise PrivacyError(
                    "[llm.private] must be a model that runs on this machine, not one that sends text away"
                )
            llm = synth_llm = private_llm  # email never leaves the machine
        elif sends_text_out(llm) or sends_text_out(synth_llm):
            raise PrivacyError(
                "an email cannot be written by a model that sends text away: add a local model "
                "as [llm.private] in config.toml"
            )
    else:
        no_connect = private_titles(vault)
        if sends_text_out(llm) or sends_text_out(synth_llm):
            hidden = no_connect  # nor may the cloud model be told what email pages exist
            blank = email_touched(vault)
    notes, read_warnings = None, []
    if len(doc.text) > cfg.max_source_chars:  # too long to read in one go: notes per chunk first
        chunks = split_chunks(doc.text, cfg.chunk_chars, cfg.max_chunks)
        notes, read_warnings = read_chunks(llm, doc.title, chunks, on_step, language=vault.language)
    candidates = find_candidates(
        vault,
        f"{doc.title}\n{doc.text[: cfg.max_source_chars]}",
        exclude=hidden,
        private=doc.kind == "email",
    )
    system, user = build_prompt(
        vault.schema_text(),
        doc,
        candidates,
        cfg.max_source_chars,
        cfg.flag_contradictions,
        notes,
        language=vault.language,
    )
    if on_step:
        on_step("synthesis")
    plan, warnings = make_plan(synth_llm, system, user, vault.language)
    if keep_title:
        plan.title = keep_title
    warnings = [*doc.warnings, *read_warnings, *warnings]
    if notes:  # long source: merge what the chunks yielded, then one focused call for the abstract
        plan.terms, plan.quotes, plan.relations = aggregate(notes)
        if on_step:
            on_step("detailed summary")
        digest, digest_warnings = make_digest(synth_llm, doc, plan, notes, vault.language)
        warnings += digest_warnings
        if digest:
            plan.abstract, plan.insights = digest.abstract, digest.insights
            plan.open_questions = digest.open_questions
    if dry_run:
        return IngestResult("dry-run", doc, plan=plan, warnings=warnings)
    connections = []
    if cfg.find_connections:
        if on_step:
            on_step("connections")
        connections, connect_warnings = connect(
            synth_llm,
            vault,
            plan,
            rebuilding=bool(keep_title),
            exclude=no_connect,
            blank=blank,
            private=doc.kind == "email",
        )
        warnings += connect_warnings

    with deferred():  # a signal waits: the note, its pages and the log are written together
        if before_write:
            before_write()
        raw_path = raw_path or save_raw(vault, doc, plan.title, today)
        applied = apply_plan(
            vault,
            plan,
            doc,
            raw_path,
            today,
            file_hash,
            captured,
            cfg.flag_contradictions,
            connections,
        )
        if applied.dropped_edges:
            edges = f"{applied.dropped_edges} diagram {'edge' if applied.dropped_edges == 1 else 'edges'}"
            warnings.append(f"Dropped {edges}: an end was not in the source or the note.")
        if applied.stripped_addresses:
            warnings.append(
                f"Removed {applied.stripped_addresses} link or image address(es) the model wrote "
                "that the source does not contain."
            )
        rebuild_index(vault)
        L = partial(lang.t, vault.language)
        details = [L("log_created", names=", ".join(applied.created))] if applied.created else []
        if applied.updated:
            details.append(L("log_updated", names=", ".join(applied.updated)))
        if applied.reviews:
            details.append(L("log_review", n=len(applied.reviews)))
        vault.append_log(f"ingest | {applied.source_title}", details, day=today)
    return IngestResult("ingested", doc, plan=plan, applied=applied, warnings=warnings)
