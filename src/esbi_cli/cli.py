import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from functools import partial
from pathlib import Path
from urllib.parse import quote, urlparse

import typer

from esbi_cli import __version__, lang
from esbi_cli import schedule as launchd
from esbi_cli.ask.answer import answer_question, save_answer
from esbi_cli.bench.cases import load_cases
from esbi_cli.bench.report import render_report, save_report, suggest_routing, summarize
from esbi_cli.bench.runner import run_benchmark
from esbi_cli.capture.inbox import scan_inbox
from esbi_cli.capture.legacy import import_legacy
from esbi_cli.config import Config, find_config, load_config, parse_time
from esbi_cli.doctor import run_checks
from esbi_cli.evaluate import evaluate, load_golden
from esbi_cli.export import export_site
from esbi_cli.extract import ExtractError, extract_source, is_url
from esbi_cli.extract.image import IMAGE_SUFFIXES, NO_OCR
from esbi_cli.gitops import GitError, commit_vault, has_git, push_vault
from esbi_cli.ingest.pipeline import ingest as run_ingest
from esbi_cli.init import (
    MODELS,
    OCR_MODEL,
    RUNTIMES,
    connect_remote,
    init_vault,
    local_model,
    set_email_block,
    write_config,
)
from esbi_cli.lint.checks import LintReport, lint_vault
from esbi_cli.lint.report import write_lint_report
from esbi_cli.llm.adapter import LLMError, make_embedder, make_llm, make_ocr
from esbi_cli.mail.credentials import CredentialError, get_password, save_password
from esbi_cli.mail.fetch import fetch_mail
from esbi_cli.mail.imap import ImapMailClient, MailError
from esbi_cli.privacy import remote_host, remote_warning
from esbi_cli.queue import Queue, normalize_target
from esbi_cli.reingest import reingest_all
from esbi_cli.report.daily_index import build_daily_index
from esbi_cli.report.readstate import sync_read_state
from esbi_cli.run import RunLimits, run_queue
from esbi_cli.runlock import LockBusy, RunLock
from esbi_cli.runlog import RunLog, RunRecord, is_due, trim_log
from esbi_cli.vault import Vault

# Rich markup would eat `[notes]`, `[llm.ocr]`, `[run]` in help texts: they are config sections.
Typer = partial(typer.Typer, rich_markup_mode="markdown")
app = Typer(help="esbi-cli: maintain an Obsidian wiki from your saved sources.")


# (label, arguments for the real command; may prompt for input)
MENU = [
    ("Queue status", lambda: ["status"]),
    ("Run now (ingest what is queued)", lambda: ["run"]),
    ("Ask the wiki a question", lambda: ["ask", typer.prompt("Question")]),
    (
        "Add links or files to the queue",
        lambda: ["add", *typer.prompt("URLs or file paths, separated by spaces").split()],
    ),
    ("Open today's note in Obsidian", lambda: ["today"]),
    ("Check the wiki's health (lint)", lambda: ["lint"]),
    ("Check my setup (doctor)", lambda: ["doctor"]),
]


def _menu() -> None:
    while True:
        typer.echo("\nesbi-cli")
        for n, (label, _) in enumerate(MENU, 1):
            typer.echo(f"  {n}. {label}")
        choice = typer.prompt("Choose (q to quit)", default="q").strip().lower()
        if choice == "q":
            return
        if not (choice.isdigit() and 1 <= int(choice) <= len(MENU)):
            typer.echo("Not an option.")
            continue
        try:
            app(MENU[int(choice) - 1][1]())  # the real command, same code
        except SystemExit:  # it printed its own error or result; keep the menu going
            pass


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """esbi-cli. Run without a command for a menu."""
    if ctx.invoked_subcommand is None:
        _menu()


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def _open_queue(cfg: Config) -> Queue:
    return Queue(cfg.vault / ".esbi" / "queue.sqlite3")


def _load(config: Path | None) -> Config:
    try:
        return load_config(config)
    except (FileNotFoundError, ValueError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


def _config_path(config: Path | None) -> Path:
    """Which config file applies, or an error line and exit 1."""
    try:
        return find_config(config)
    except FileNotFoundError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


def _vault(cfg: Config) -> Vault:
    """The vault, with the dense side of search when [llm.embed] is configured (off by default)."""
    if "embed" not in cfg.llm:
        return Vault(cfg.vault, language=cfg.language)
    try:
        return Vault(cfg.vault, embedder=make_embedder(cfg.llm["embed"]), language=cfg.language)
    except ValueError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml.")


@app.command()
def status(config: Path | None = CONFIG_OPTION) -> None:
    """Show how many sources are queued, done or failed."""
    queue = _open_queue(_load(config))
    counts = queue.counts()
    for state in ("queued", "processing", "done", "failed"):
        typer.echo(f"{state}: {counts.get(state, 0)}")
    for item in queue.items("failed"):
        typer.echo(f"  failed: {item.target} ({item.error})")


def _is_source(target: str, images: bool = False) -> bool:
    suffixes = (".pdf", ".md", *(IMAGE_SUFFIXES if images else ()))
    return is_url(target) or (
        Path(target).expanduser().is_file() and Path(target).suffix.lower() in suffixes
    )


def _ocr(cfg: Config):
    """The model that reads images and scanned PDFs, or None when [llm.ocr] is not configured."""
    return make_ocr(cfg.llm["ocr"]) if "ocr" in cfg.llm else None


def _extractor(cfg: Config, ocr):
    return partial(extract_source, ocr=ocr, max_ocr_pages=cfg.ocr_max_pages)


def _report_unsupported(names: list[str]) -> None:
    """Files in inbox/ that nothing can read: said out loud, never ignored."""
    if not names:
        return
    typer.echo(f"Not read, esbi-cli cannot read these files in inbox/: {', '.join(names)}")
    if any(Path(n).suffix.lower() in IMAGE_SUFFIXES for n in names):
        typer.echo(f"  Images: {NO_OCR}")


@app.command()
def add(
    targets: list[str] = typer.Argument(
        ..., help="URLs, or paths to .pdf / .md files (and images, with an [llm.ocr] model)."
    ),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Queue sources to be ingested by the next `sb run` (nothing is fetched now)."""
    cfg = _load(config)
    images = "ocr" in cfg.llm
    bad = [t for t in targets if not _is_source(t, images)]
    if bad:
        typer.secho(
            f"error: not an http(s) URL or an existing .pdf/.md{'/image' if images else ''} file:",
            fg="red",
            err=True,
        )
        for t in bad:
            typer.secho(f"  {t}", fg="red", err=True)
        if not images and any(Path(t).suffix.lower() in IMAGE_SUFFIXES for t in bad):
            typer.secho(f"  Images: {NO_OCR}", fg="red", err=True)
        raise typer.Exit(1)
    queue = _open_queue(cfg)
    in_wiki = {
        normalize_target(str(p.meta["url"])): p.title
        for p in _vault(cfg).iter_pages(("sources",))
        if p.meta.get("url")
    }
    added = known = 0
    for t in targets:
        if title := (in_wiki.get(normalize_target(t)) if is_url(t) else None):
            typer.echo(f"Skipped {t}: already in the wiki as [[{title}]]")
        elif queue.add(t, "cli", label=None if is_url(t) else Path(t).stem):
            added += 1
        else:
            known += 1
    typer.echo(f"Queued {added} ({known} already known). `sb run` processes them.")


def open_uri(uri: str) -> None:
    try:
        subprocess.run(["open", uri], check=False)  # macOS
    except FileNotFoundError:
        typer.echo("(no `open` command here: open the link above yourself)")


@app.command()
def today(config: Path | None = CONFIG_OPTION) -> None:
    """Open today's daily note in Obsidian, or print its path if [notes].viewer is "none"."""
    cfg = _load(config)
    vault, day = _vault(cfg), date.today().isoformat()
    if not (vault.wiki / "daily" / f"{day}.md").exists():
        _refresh_index(vault, _open_queue(cfg))
    if cfg.viewer == "none":  # no Obsidian: any Markdown editor opens this file
        typer.echo(str(vault.wiki / "daily" / f"{day}.md"))
        return
    uri = (
        f"obsidian://open?vault={quote(vault.root.name)}&file={quote(f'wiki/daily/{day}', safe='')}"
    )
    typer.echo(uri)
    open_uri(uri)


@app.command()
def doctor(config: Path | None = CONFIG_OPTION) -> None:
    """Check config, vault, Obsidian, model, mailbox, nightly job and install; say what to fix."""
    checks = run_checks(config)
    for c in checks:
        typer.echo(f"  {c.level:<4} {c.name}: {c.text}")
        if c.fix:
            typer.echo(f"         fix: {c.fix}")
    if any(c.level == "FAIL" for c in checks):
        raise typer.Exit(1)


@app.command()
def retry(
    target: str | None = typer.Argument(
        None, help="One source to retry; default: all parked ones."
    ),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Put sources that failed for good back in the queue with a fresh attempt count."""
    count = _open_queue(_load(config)).requeue_failed(target)
    typer.echo(
        f"Requeued {count} source{'s' if count != 1 else ''}." if count else "Nothing to retry."
    )


@app.command()
def drop(
    target: str = typer.Argument(..., help="URL or path exactly as `sb status` shows it."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Remove a source from the queue for good (its original file, if any, is not touched)."""
    if not _open_queue(_load(config)).remove(target):
        typer.secho(f"error: {target} is not in the queue", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.echo(f"Dropped {target}")


@app.command("import-legacy")
def import_legacy_cmd(config: Path | None = CONFIG_OPTION) -> None:
    """One-time import of an older folder (Links/ with dated link lists, and PDFs/) into the queue."""
    cfg = _load(config)
    if cfg.legacy_vault is None or not cfg.legacy_vault.is_dir():
        typer.secho("error: set [paths].legacy_vault to an existing folder", fg="red", err=True)
        raise typer.Exit(1)
    result = import_legacy(cfg.legacy_vault, _open_queue(cfg))
    typer.echo(f"Queued {result.added} sources ({result.duplicates} already known).")


@app.command()
def scan(config: Path | None = CONFIG_OPTION) -> None:
    """Queue what is waiting in the vault's inbox/ folder (Web Clipper notes, PDFs, images)."""
    cfg = _load(config)
    result = scan_inbox(_vault(cfg), _open_queue(cfg), images="ocr" in cfg.llm)
    dupes = f" ({result.duplicates} duplicate{'s' if result.duplicates != 1 else ''} removed)"
    typer.echo(
        f"Queued {result.enqueued} sources from the inbox{dupes if result.duplicates else ''}."
    )
    _report_unsupported(result.unsupported)


def _refresh_index(vault: Vault, queue: Queue) -> None:
    """Register ticks made in earlier daily notes, then rewrite today's note from the state."""
    today = date.today()
    newly_read = sync_read_state(vault, today)
    if newly_read:
        typer.echo(f"Marked {len(newly_read)} source{'s' if len(newly_read) != 1 else ''} as read.")
    path = build_daily_index(vault, queue, today)
    typer.echo(f"Wrote {path.relative_to(vault.root)}")
    try:
        commit_vault(vault.root, f"index: {today.isoformat()}")
    except GitError as exc:
        typer.secho(f"warning: git commit failed: {exc}", fg=typer.colors.YELLOW, err=True)
    if problem := push_vault(vault.root):
        typer.secho(
            f"warning: vault backup not pushed: {problem}", fg=typer.colors.YELLOW, err=True
        )


@app.command()
def index(config: Path | None = CONFIG_OPTION) -> None:
    """Register read ticks and rebuild today's daily index note and the Home block."""
    cfg = _load(config)
    _refresh_index(_vault(cfg), _open_queue(cfg))


@app.command()
def run(
    config: Path | None = CONFIG_OPTION,
    max_sources: int | None = typer.Option(None, "--limit", help="Max sources this run."),
    if_due: bool = typer.Option(
        False,
        "--if-due",
        help="Scheduled mode: run only if today's nightly run has not happened yet.",
    ),
) -> None:
    """Scan the inbox, then ingest queued sources within the configured limits."""
    cfg = _load(config)
    try:
        with RunLock(cfg.vault / ".esbi" / "run.lock"):
            _run_locked(cfg, max_sources, if_due)
    except LockBusy:
        typer.echo("Another run is in progress; skipping.")


def _writers(cfg: Config):
    """(reader, synthesizer, private). The synthesis model is optional: it writes the digest and
    the connections, so it can be a stronger, slower model than the one taking chunk notes. The
    private model, also optional, is the only one that ever reads email."""
    reader = make_llm(cfg.llm_for("summarize"))
    synth = make_llm(cfg.llm["synthesize"]) if "synthesize" in cfg.llm else None
    private = make_llm(cfg.llm["private"]) if "private" in cfg.llm else None
    return reader, synth, private


def _run_locked(cfg: Config, max_sources: int | None, if_due: bool) -> None:
    vault, queue = _vault(cfg), _open_queue(cfg)
    trim_log(cfg.vault / ".esbi" / "logs" / "nightly.log")
    runlog = RunLog(cfg.vault / ".esbi" / "runs.jsonl")
    started = datetime.now()
    if if_due and not is_due(runlog.runs(), started, cfg.nightly_at):
        typer.echo("Not due: the nightly run already happened.")
        return
    try:
        llm, synth, private = _writers(cfg)
        ocr = _ocr(cfg)
    except (KeyError, ValueError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if cfg.email.enabled:
        try:
            _fetch_mail(cfg, vault)
        except (MailError, CredentialError) as exc:  # mail trouble must not stop ingestion
            typer.secho(f"warning: mail skipped: {exc}", fg=typer.colors.YELLOW, err=True)

    scan = scan_inbox(vault, queue, images=ocr is not None)
    recovered = queue.recover()
    if scan.enqueued or recovered:
        typer.echo(f"Inbox: {scan.enqueued} new, {recovered} recovered from an interrupted run.")
    _report_unsupported(scan.unsupported)

    def ingest_and_commit(target: str):
        item = queue.get(target)  # legacy items remember when they were saved
        result = run_ingest(
            target,
            vault=vault,
            llm=llm,
            synth_llm=synth,
            private_llm=private,
            cfg=cfg,
            extractor=_extractor(cfg, ocr),
            captured=item.captured if item else None,
            on_step=lambda step: typer.echo(f"    ... {step}"),
        )
        if result.applied:
            typer.echo(f"  + {result.applied.source_title}")
            for warning in result.warnings:
                typer.secho(f"    warning: {warning}", fg=typer.colors.YELLOW, err=True)
            if result.applied.unsupported_entities:
                names = ", ".join(result.applied.unsupported_entities)
                typer.echo(f"    dropped entities not found in the source: {names}")
            try:
                commit_vault(cfg.vault, f"ingest: {result.applied.source_title}")
            except GitError as exc:
                typer.secho(f"    warning: git commit failed: {exc}", fg="yellow", err=True)
        return result

    summary = run_queue(
        queue,
        ingest_and_commit,
        RunLimits(max_sources or cfg.max_sources_per_run, cfg.max_tokens_per_run),
        tokens_used=lambda: sum(m.tokens_used for m in (llm, synth, private, ocr) if m),
    )
    for f in summary.failures:
        outcome = "parked (`sb retry` puts it back)" if f.parked else "will be tried again"
        reason = " ".join(f.error.split())  # one line, however long the message was
        reason = reason if len(reason) <= 160 else reason[:157] + "..."
        typer.echo(
            f"  ! {f.name}: attempt {f.attempt} of {queue.max_attempts} failed, {outcome}: {reason}"
        )
    typer.echo(
        f"ingested: {summary.ingested}, skipped: {summary.skipped}, failed: {summary.failed} "
        f"({summary.tokens_used} tokens)"
    )
    runlog.record(
        RunRecord(
            started=started,
            finished=datetime.now(),
            ingested=summary.ingested,
            skipped=summary.skipped,
            failed=summary.failed,
            tokens_used=summary.tokens_used,
            stopped_by=summary.stopped_by,
            trigger="scheduled" if if_due else "manual",
        )
    )
    report = _lint(vault)
    if report.issues:
        typer.echo(f"Lint: {len(report.issues)} issues (see wiki/review/Lint.md)")
    _refresh_index(vault, queue)  # even after an outage: the morning index must exist
    if summary.stopped_by == "llm_unavailable":
        typer.secho(
            "The LLM is unreachable (is Ollama running?). Nothing was lost; sources stay queued.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    if summary.stopped_by:
        typer.echo(f"Stopped early ({summary.stopped_by}); the rest stays queued for the next run.")


def _lint(vault: Vault) -> LintReport:
    """Check the wiki's health and (re)write, or remove, wiki/review/Lint.md."""
    report = lint_vault(vault)
    write_lint_report(vault, report, date.today())
    return report


@app.command()
def lint(config: Path | None = CONFIG_OPTION) -> None:
    """Check the wiki for orphans, broken links, duplicates and more. Only reports."""
    cfg = _load(config)
    report = _lint(Vault(cfg.vault, language=cfg.language))
    if not report.issues:
        typer.echo("No problems found.")
        return
    for kind in dict.fromkeys(i.kind for i in report.issues):
        typer.echo(f"{kind}: {sum(i.kind == kind for i in report.issues)}")
    typer.echo("Details in wiki/review/Lint.md")


def _log_question(cfg: Config, question: str, answer, llm, duration_seconds: float) -> None:
    """One line per question in .esbi/asks.jsonl: what was retrieved, what was cited."""
    row = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "retrieved": answer.retrieved,
        "grounded": answer.grounded,
        "cited": answer.citations,
        "tokens": llm.tokens_used,
        "seconds": round(duration_seconds, 1),
    }
    path = cfg.vault / ".esbi" / "asks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


@app.command()
def ask(
    question: str = typer.Argument(..., help="A question the wiki should be able to answer."),
    config: Path | None = CONFIG_OPTION,
    save: bool = typer.Option(False, "--save", help="File a grounded answer in wiki/syntheses/."),
) -> None:
    """Answer a question from the wiki only, citing the pages used."""
    cfg = _load(config)
    vault = _vault(cfg)
    try:
        llm = make_llm(cfg.llm.get("ask") or cfg.llm_for("summarize"))
        started = time.monotonic()
        answer = answer_question(vault, llm, question, rewrite=cfg.rewrite_questions)
    except (KeyError, ValueError, LLMError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    _log_question(cfg, question, answer, llm, time.monotonic() - started)
    typer.echo(answer.text)
    if not answer.grounded:
        return
    typer.echo("\nSources: " + ", ".join(f"[[{c}]]" for c in answer.citations))
    if save:
        path = save_answer(vault, answer, date.today())
        typer.echo(f"Saved {path.relative_to(vault.root)}")
        try:
            commit_vault(cfg.vault, f"ask: {path.stem}")
        except GitError as exc:
            typer.secho(f"warning: git commit failed: {exc}", fg=typer.colors.YELLOW, err=True)


@app.command()
def info(config: Path | None = CONFIG_OPTION) -> None:
    """Print where things are, as key=value lines (the setup wizards read this)."""
    cfg = _load(config)
    typer.echo(f"config={find_config(config)}")
    typer.echo(f"vault={cfg.vault}")
    typer.echo(f"viewer={cfg.viewer}")
    typer.echo(f"language={cfg.language}")
    typer.echo(f"email={'enabled' if cfg.email.enabled else 'disabled'}")


setup_app = Typer(help="Optional guided setups: mail capture and the Web Clipper.")
app.add_typer(setup_app, name="setup")
PACKAGE_DIR = Path(__file__).parent


def _run_wizard(script: str, config: Path | None) -> None:
    """Run a bundled setup wizard (bash) in this terminal, with the paths it needs."""
    path = _config_path(config)
    sb = Path(sys.prefix) / "bin" / "sb"
    env = {
        **os.environ,
        "SB": str(sb if sb.exists() else shutil.which("sb") or "sb"),
        "SB_CONFIG": str(path),
        "SB_TEMPLATES": str(PACKAGE_DIR / "templates"),
    }
    done = subprocess.run(["bash", str(PACKAGE_DIR / "wizards" / script)], env=env)
    if done.returncode != 0:
        raise typer.Exit(done.returncode)


@setup_app.command("email")
def setup_email(config: Path | None = CONFIG_OPTION) -> None:
    """Connect a Gmail mailbox so you can forward articles and PDFs to the app (optional)."""
    _run_wizard("email.sh", config)


@setup_app.command("clipper")
def setup_clipper(config: Path | None = CONFIG_OPTION) -> None:
    """Connect the Obsidian Web Clipper to save pages and YouTube transcripts (optional; needs Obsidian)."""
    _run_wizard("clipper.sh", config)


GOLDEN_HELP = """\
No questions to score yet. Make {path} with one JSON object per line, a question and the
source(s) that should answer it (the start of a title is enough):

  {{"question": "What is an agent harness?", "expect": ["Code as Agent Harness"]}}
"""


@app.command("eval")
def eval_command(
    config: Path | None = CONFIG_OPTION,
    k: int = typer.Option(6, "--k", help="How many pages count as retrieved (sb ask uses 6)."),
    rewrite: bool = typer.Option(
        False,
        "--rewrite",
        help="Rewrite each question into search terms first (one model call each).",
    ),
    answers: bool = typer.Option(
        False, "--answers", help="Also run sb ask on each question (slow; uses the ask model)."
    ),
) -> None:
    """Score how well retrieval finds the right pages, on the questions in .esbi/golden.jsonl."""
    cfg = _load(config)
    vault = _vault(cfg)
    path = cfg.vault / ".esbi" / "golden.jsonl"
    if not path.exists():
        typer.secho(GOLDEN_HELP.format(path=path), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    try:
        golden = load_golden(path)
        llm = (
            make_llm(cfg.llm.get("ask") or cfg.llm_for("summarize")) if rewrite or answers else None
        )
        report = evaluate(
            vault,
            golden,
            k,
            rewrite_llm=llm if rewrite else None,
            answer_llm=llm if answers else None,
        )
    except (ValueError, KeyError, LLMError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    hits = sum(c.rank is not None for c in report.cases)
    typer.echo(
        f"Retrieval on {len(report.cases)} questions: recall@{k} {report.recall:.0%} "
        f"({hits}/{len(report.cases)}), MRR {report.mrr:.2f}"
        + (" (questions rewritten)" if rewrite else "")
    )
    if answers:
        typer.echo(
            f"Answers: grounded {report.rate('grounded'):.0%}, "
            f"cites the expected page {report.rate('cited'):.0%}"
        )
    for case in report.cases:
        if case.rank is None:
            typer.echo(
                f"  miss: {case.question} (expected {', '.join(case.expect)}; got {', '.join(case.retrieved) or 'nothing'})"
            )


@app.command("export")
def export_command(
    config: Path | None = CONFIG_OPTION,
    out: Path = typer.Option(
        None, "--out", help="Where to write the site (default: <vault>/site)."
    ),
) -> None:
    """Write a read-only HTML copy of the wiki, to browse without Obsidian."""
    cfg = _load(config)
    target = out or cfg.vault / "site"
    try:
        count = export_site(_vault(cfg), target)
    except ValueError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Exported {count} pages. Open {target.expanduser().resolve() / 'index.html'}")


@app.command()
def bench(
    config: Path | None = CONFIG_OPTION,
    models: str | None = typer.Option(
        None, "--models", help="Comma-separated, e.g. ollama/qwen3:4b"
    ),
    cases: int | None = typer.Option(
        None, "--cases", help="Cases per task (default: cases in the bench section of config.toml)."
    ),
) -> None:
    """Compare models on your own material. Read-only for the wiki; prints and saves a report."""
    cfg = _load(config)
    names = [m.strip() for m in models.split(",")] if models else cfg.bench.models
    if not names:
        typer.secho("error: pass --models or set [bench].models in config.toml", fg="red", err=True)
        raise typer.Exit(1)
    vault = _vault(cfg)
    ingest_cases, ask_cases = load_cases(vault, cases or cfg.bench.cases)
    if not ingest_cases and not ask_cases:
        typer.secho(
            "error: the vault has no sources or concepts to test with yet", fg="red", err=True
        )
        raise typer.Exit(1)

    base = cfg.llm_for("summarize")

    def llm_for(model: str):
        same_provider = model.split("/")[0] == base.model.split("/")[0]
        # endpoint and key settings belong to one provider: don't leak them to another
        return make_llm(
            replace(
                base,
                model=model,
                base_url=base.base_url if same_provider else None,
                api_key_env=base.api_key_env if same_provider else None,
            )
        )

    def progress(trial) -> None:
        state = "ok" if trial.ok else f"FAILED ({trial.error})"
        typer.echo(
            f"  {trial.model} · {trial.task} · {trial.case}: {state} in {trial.latency_seconds:.0f}s"
        )

    trials = run_benchmark(
        names,
        ingest_cases,
        ask_cases,
        vault,
        llm_factory=llm_for,
        max_source_chars=cfg.max_source_chars,
        on_trial=progress,
    )
    summaries = summarize(trials, cfg.bench.prices)
    now = datetime.now()
    text = render_report(summaries, suggest_routing(summaries), when=now, language=vault.language)
    typer.echo("\n" + text)
    typer.echo(f"Saved {save_report(vault, text, now).relative_to(vault.root)}")


email_app = Typer(help="Capture mail sent to the dedicated mailbox.")
app.add_typer(email_app, name="email")


def make_mail_client(cfg: Config) -> ImapMailClient:
    if not cfg.email.enabled:
        raise MailError("email is disabled: set [email].enabled = true in config.toml")
    if not cfg.email.user:
        raise MailError("set [email].user (the mailbox address) in config.toml")
    return ImapMailClient(
        host=cfg.email.imap_host,
        user=cfg.email.user,
        password=get_password(cfg.email.user),
        mailbox=cfg.email.mailbox,
    )


def _fetch_mail(cfg: Config, vault: Vault) -> None:
    client = make_mail_client(cfg)
    try:
        result = fetch_mail(client, vault)
    finally:
        client.close()
    typer.echo(
        f"Mail: {result.saved} saved, {result.duplicates} duplicates, {result.failed} failed."
    )


@email_app.command("fetch")
def email_fetch(config: Path | None = CONFIG_OPTION) -> None:
    """Save recent mail from the dedicated mailbox into the vault's inbox/."""
    cfg = _load(config)
    try:
        _fetch_mail(cfg, _vault(cfg))
    except (MailError, CredentialError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


@email_app.command("configure")
def email_configure(
    user: str = typer.Option(..., "--user", help="The Gmail address that receives your forwards."),
    label: str = typer.Option("esbi-cli", "--label", help="The Gmail label to read."),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Turn on mail capture in config.toml (the password is stored separately: set-password)."""
    path = _config_path(config)
    set_email_block(path, user, label)
    typer.echo(f"Mail capture on for {user}, label {label}, in {path}")


@email_app.command("set-password")
def email_set_password(
    config: Path | None = CONFIG_OPTION,
    stdin: bool = typer.Option(
        False,
        "--stdin",
        help="Read the password from standard input, e.g. `pbpaste | sb email set-password --stdin`.",
    ),
) -> None:
    """Store the mailbox app password in the macOS Keychain (typed hidden, never shown).

    There is no `--password` option on purpose: an argument ends up in your shell history and in
    the process list."""
    cfg = _load(config)
    if not cfg.email.user:
        typer.secho("error: set [email].user in config.toml first", fg="red", err=True)
        raise typer.Exit(1)
    if stdin:
        password = sys.stdin.read().strip()
        if not password:
            typer.secho("error: the password from standard input is empty", fg="red", err=True)
            raise typer.Exit(1)
    else:
        password = typer.prompt(f"App password for {cfg.email.user}", hide_input=True)
    try:
        save_password(cfg.email.user, password)
    except CredentialError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo("Saved to the Keychain.")


schedule_app = Typer(help="Run the nightly job automatically with launchd (macOS).")
app.add_typer(schedule_app, name="schedule")

AGENTS_DIR_OPTION = typer.Option(
    Path("~/Library/LaunchAgents"), "--agents-dir", help="Where launchd agents live."
)
RUNNING_VENV = Path(sys.prefix)
AGENTS_DIR = Path(
    "~/Library/LaunchAgents"
)  # where launchd agents live (a test points it elsewhere)


@contextmanager
def _needs_launchd(config: Path | None = None):
    """Where launchctl does not exist (Linux), say so and show the cron line that does the same."""
    try:
        yield
    except FileNotFoundError as exc:
        try:
            line = launchd.cron_line(find_config(config))
        except FileNotFoundError:
            line = launchd.cron_line(Path("config.toml"))
        typer.secho(
            "error: the nightly job uses launchd, which only macOS has. On this system add this "
            f"line to cron (`crontab -e`; hourly is fine, it runs once a day):\n  {line}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1) from exc


@schedule_app.command("install")
def schedule_install(
    config: Path | None = CONFIG_OPTION,
    agents_dir: Path = AGENTS_DIR_OPTION,
) -> None:
    """Install and load the LaunchAgent: runs at [run].nightly_time (or the next wake), retrying hourly."""
    cfg = _load(config)
    config = find_config(config).resolve()
    try:
        with _needs_launchd(config):
            path = _install_job(config, agents_dir)
    except launchd.ScheduleError as exc:
        typer.secho(
            f"error: {exc} (run `uv sync` if this is a checkout)", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1) from exc
    typer.echo(
        f"Installed {path}\nRuns every day at {cfg.nightly_time} "
        f"(or at the next wake). Log: {cfg.vault / '.esbi' / 'logs' / 'nightly.log'}"
    )


@schedule_app.command("uninstall")
def schedule_uninstall(agents_dir: Path = AGENTS_DIR_OPTION) -> None:
    """Unload and remove the LaunchAgent."""
    with _needs_launchd():
        removed = launchd.uninstall(
            agents_dir=agents_dir.expanduser(), uid=os.getuid(), launchctl=launchd.run_launchctl
        )
    typer.echo("Removed." if removed else "Nothing to remove.")


@schedule_app.command("status")
def schedule_status(agents_dir: Path = AGENTS_DIR_OPTION) -> None:
    """Show whether the LaunchAgent is installed and loaded."""
    path = agents_dir.expanduser() / f"{launchd.LABEL}.plist"
    with _needs_launchd():
        loaded = launchd.is_loaded(uid=os.getuid(), launchctl=launchd.run_launchctl)
    typer.echo(f"installed: {'yes' if path.exists() else 'no'}")
    typer.echo(f"loaded: {'yes' if loaded else 'no'}")


@app.command()
def ingest(
    target: str = typer.Argument(
        ..., help="An http(s) URL, or a path to a local PDF, Markdown note or image."
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to config.toml."),
    force: bool = typer.Option(False, "--force", help="Ingest even if already in the vault."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the LLM's plan; write nothing."),
    no_commit: bool = typer.Option(False, "--no-commit", help="Do not git-commit the vault."),
) -> None:
    """Ingest one source into the wiki."""
    try:
        cfg = load_config(config)
        llm, synth, private = _writers(cfg)
        result = run_ingest(
            target,
            extractor=_extractor(cfg, _ocr(cfg)),
            vault=_vault(cfg),
            llm=llm,
            synth_llm=synth,
            private_llm=private,
            cfg=cfg,
            force=force,
            dry_run=dry_run,
            on_step=lambda step: typer.echo(f"... {step}"),
        )
    except (FileNotFoundError, KeyError, ValueError, ExtractError, LLMError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if result.status == "skipped":
        typer.echo(f"Already in the vault as [[{result.existing_title}]] (use --force to redo).")
        return
    assert result.plan is not None
    for warning in result.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)
    if result.status == "dry-run":
        typer.echo(result.plan.model_dump_json(indent=2))
        return

    applied = result.applied
    assert applied is not None
    typer.echo(f"Ingested: {applied.source_title}")
    typer.echo(f"  created:  {', '.join(applied.created) or '-'}")
    typer.echo(f"  updated:  {', '.join(applied.updated) or '-'}")
    if applied.reviews:
        typer.echo(f"  review:   {len(applied.reviews)} note(s) in wiki/review/")
    if applied.dropped:
        typer.echo(f"  ignored references to unknown pages: {', '.join(applied.dropped)}")
    if applied.unsupported_entities:
        typer.echo(
            f"  dropped entities not found in the source: {', '.join(applied.unsupported_entities)}"
        )
    if not no_commit:
        try:
            done = commit_vault(cfg.vault, f"ingest: {applied.source_title}")
            typer.echo("  committed to the vault repo" if done else "  nothing to commit")
        except GitError as exc:
            typer.secho(f"  warning: git commit failed: {exc}", fg=typer.colors.YELLOW, err=True)


def _interactive() -> bool:
    """Ask questions only when a person is at the keyboard (tests and scripts use the flags)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _choose(question: str, options: list[str], default: int = 1) -> int:
    """A numbered choice, 1-based."""
    typer.echo(question)
    for n, text in enumerate(options, 1):
        typer.echo(f"  {n}. {text}")
    while True:
        answer = typer.prompt("Choose", default=str(default))
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer)
        typer.echo("Not an option.")


def _install_job(config: Path, agents_dir: Path) -> Path:
    """Write and load the nightly LaunchAgent for this config (macOS)."""
    cfg = _load(config)
    if not (RUNNING_VENV / "bin" / "sb").exists():
        raise launchd.ScheduleError(f"no {RUNNING_VENV}/bin/sb")
    log_dir = cfg.vault / ".esbi" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist = launchd.render_plist(
        config=config, log_dir=log_dir, venv=RUNNING_VENV, at=cfg.nightly_at
    )
    return launchd.install(
        plist, agents_dir=agents_dir.expanduser(), uid=os.getuid(), launchctl=launchd.run_launchctl
    )


@app.command()
def init(
    vault: Path | None = typer.Option(None, "--vault", help="Where the vault should live."),
    config_file: Path = typer.Option(
        Path("~/.config/esbi-cli/config.toml"), "--config-file", help="Where to write config."
    ),
    model: str = typer.Option(
        None, "--model", help="Which model writes the notes: local, subscription or api."
    ),
    runtime: str = typer.Option(None, "--runtime", help="For a local model: ollama or lmstudio."),
    local_name: str = typer.Option(
        None, "--local-model", help="The local model's name (required for lmstudio: see `lms ls`)."
    ),
    base_url: str = typer.Option(
        None,
        "--base-url",
        help="Where the local runtime's server is, if not on this Mac (a local model only).",
    ),
    language: str = typer.Option(
        None,
        "--language",
        help=f"The language the notes are written in ({lang.supported()}). The CLI itself is English.",
    ),
    obsidian: bool = typer.Option(
        None, "--obsidian/--no-obsidian", help="Do you use Obsidian to read your notes?"
    ),
    nightly: str = typer.Option(
        None, "--nightly", help="Run every night at HH:MM (installs the job on macOS), or `none`."
    ),
    remote: str = typer.Option(None, "--remote", help="A git remote to back the vault up to."),
    ocr: bool = typer.Option(
        False,
        "--ocr/--no-ocr",
        help="Also read images and scanned PDFs, with a local Ollama vision model (about 2 GB).",
    ),
) -> None:
    """First-time setup: create the vault, a config file, and (asking) the optional pieces.

    The basics are adding PDFs and links. Obsidian, the nightly job, a backup remote, Gmail and the
    Web Clipper are all optional. Safe to run again: it only creates what is missing."""
    ask_user = _interactive()
    if ask_user:
        typer.echo(
            "esbi-cli turns the PDFs and links you save into a wiki of notes.\n"
            "That is all you need. Every question below is optional or has a default.\n"
        )
    root = Path(
        vault or typer.prompt("Vault folder", default="~/Documents/Obsidian/esbi")
        if ask_user
        else vault or "~/Documents/Obsidian/esbi"
    ).expanduser()
    if language is None:
        codes = list(lang.LANGUAGES)
        language = (
            codes[
                _choose(
                    "In which language should the notes be written? (The CLI itself is English.)",
                    [lang.name(c) for c in codes],
                )
                - 1
            ]
            if ask_user
            else lang.DEFAULT
        )
    if language not in lang.LANGUAGES:
        typer.secho(f"error: --language must be one of: {lang.supported()}", fg="red", err=True)
        raise typer.Exit(1)
    if obsidian is None:
        obsidian = (
            typer.confirm(
                "Do you use Obsidian to read your notes? (Any Markdown editor also works)",
                default=False,
            )
            if ask_user
            else True
        )
    if model is None:
        model = (
            ["local", "subscription", "api"][
                _choose(
                    "How should the notes be written?",
                    [
                        "On this Mac with a local model (nothing leaves it)",
                        "With your Claude subscription (source text goes to Anthropic; email stays local)",
                        "With an API key (source text goes to the provider; email stays local)",
                    ],
                )
                - 1
            ]
            if ask_user
            else "local"
        )
    if model not in MODELS:
        typer.secho("error: --model must be local, subscription or api", fg="red", err=True)
        raise typer.Exit(1)
    if runtime is None:
        runtime = (
            RUNTIMES[
                _choose(
                    "Which local runtime? (also used as the failsafe for the other choices)",
                    ["Ollama (ollama.com)", "LM Studio (lmstudio.ai)"],
                )
                - 1
            ]
            if ask_user
            else "ollama"
        )
    if runtime not in RUNTIMES:
        typer.secho("error: --runtime must be ollama or lmstudio", fg="red", err=True)
        raise typer.Exit(1)
    if runtime == "lmstudio" and not local_name:
        local_name = (
            typer.prompt("Model identifier as LM Studio shows it (`lms ls`)") if ask_user else None
        )
        if not local_name:
            typer.secho(
                "error: LM Studio needs --local-model NAME (see `lms ls`)", fg="red", err=True
            )
            raise typer.Exit(1)
    if ocr and runtime != "ollama":
        typer.secho("error: --ocr needs Ollama (--runtime ollama)", fg="red", err=True)
        raise typer.Exit(1)
    if base_url is None and ask_user and model == "local":
        base_url = typer.prompt("Server address (Enter if it runs on this Mac)", default="") or None
    if base_url and (model != "local" or not urlparse(base_url).hostname):
        typer.secho(
            "error: --base-url needs an http(s) address and goes with --model local",
            fg="red",
            err=True,
        )
        raise typer.Exit(1)
    if nightly is None and ask_user:
        nightly = (
            typer.prompt("At what time? (HH:MM, 24 hours)", default="03:00")
            if typer.confirm("Run automatically every night?", default=False)
            else "none"
        )
    install_job = nightly not in (None, "none")
    if install_job:
        try:
            parse_time(nightly)
        except ValueError as exc:
            typer.secho(f"error: {exc}", fg="red", err=True)
            raise typer.Exit(1) from exc
    if remote is None and ask_user and has_git():
        remote = (
            typer.prompt("Git remote to back the vault up to (Enter to skip)", default="") or None
        )

    config_file = config_file.expanduser()
    made = init_vault(root, language)
    wrote = write_config(
        config_file,
        root.resolve(),
        model,
        viewer="obsidian" if obsidian else "none",
        nightly=nightly if install_job else None,
        runtime=runtime,
        local_name=local_name,
        ocr=ocr,
        base_url=base_url,
        language=language,
    )
    typer.echo(f"Vault {root}: " + (", ".join(made) if made else "nothing to create"))
    typer.echo(f"Config {config_file}: " + ("written" if wrote else "already there, left alone"))
    typer.echo(f"Notes language: {language} ({lang.name(language)}). The CLI itself is English.")
    typer.echo(f"Model: {model}. {MODELS[model]}")
    if base_url and (host := remote_host(local_model(runtime, local_name), base_url)):
        typer.secho(
            f"warning: {remote_warning(local_model(runtime, local_name), host)}",
            fg="yellow",
            err=True,
        )
    if not (root / ".git").exists():
        typer.echo(
            "History: git is not installed, so the vault has no version history. That is optional; "
            "install git and run `sb init` again to turn it on."
        )
    if remote and not (root / ".git").exists():
        typer.echo("Backup remote skipped: it needs git.")
    elif remote:
        added = connect_remote(root, remote)
        typer.echo(
            f"Backup remote: {remote}. Everything in the vault is pushed there, including notes "
            "made from email: use a private repository."
            if added
            else "The vault already has a remote: left alone."
        )
    if install_job and wrote:
        if sys.platform == "darwin":
            try:
                path = _install_job(config_file.resolve(), AGENTS_DIR)
                typer.echo(f"Nightly job installed ({path.name}): runs every day at {nightly}.")
            except launchd.ScheduleError as exc:
                typer.secho(f"warning: nightly job not installed: {exc}", fg="yellow", err=True)
        else:
            typer.echo(
                "Nightly job: this system has no launchd. Add this to cron (hourly is fine, it runs once a day):\n"
                f"  {launchd.cron_line(config_file)}"
            )
    if ask_user:
        _offer_integrations(config_file.resolve(), obsidian)
    steps = []
    if runtime == "ollama" and model != "api":
        steps.append("ollama pull llama3.2")
    if ocr:
        steps.append(f"ollama pull {OCR_MODEL}")
    steps.append("sb doctor")
    typer.echo(
        f"\nNext: {', then '.join(steps)}. Add a link with `sb add URL` or drop a PDF in the "
        "vault's inbox/ folder."
    )


def _offer_integrations(config: Path, obsidian: bool) -> None:
    """The two optional connections, explained, never required."""
    typer.echo("\nOptional extras (skip both and the app works the same for PDFs and links):")
    if typer.confirm("  Connect Gmail, to forward an email and get a note?", default=False):
        _run_wizard("email.sh", config)
    if obsidian:
        if typer.confirm(
            "  Set up the Obsidian Web Clipper, to save web pages and YouTube transcripts?",
            default=False,
        ):
            _run_wizard("clipper.sh", config)
    else:
        typer.echo(
            "  The Web Clipper needs Obsidian: skipped. (`sb add URL` and the inbox/ folder still work.)"
        )


@app.command()
def reingest(
    titles: list[str] = typer.Argument(
        None, help="Rebuild only notes whose title contains one of these words (any format)."
    ),
    config: Path | None = CONFIG_OPTION,
    all_sources: bool = typer.Option(
        False, "--all", help="Rebuild every note, even those already in the current format."
    ),
) -> None:
    """Rebuild the notes from their saved raw sources with the current, richer pipeline.

    Read ticks are kept and the vault is tagged in git first (`git reset --hard <tag>` undoes it).
    Notes are marked when rebuilt, so an interrupted run resumes where it stopped.
    """
    cfg = _load(config)
    if not (cfg.vault / ".git").exists():
        typer.secho(
            "error: reingest rewrites every note and relies on the vault's git history to undo it; "
            "install git and run `sb init` first.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    try:
        llm, synth, private = _writers(cfg)
    except (KeyError, ValueError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    try:
        with RunLock(cfg.vault / ".esbi" / "run.lock"):
            result = reingest_all(
                _vault(cfg),
                llm,
                synth,
                cfg,
                private_llm=private,
                all_sources=all_sources,
                only=titles,
                on_progress=typer.echo,
            )
    except LockBusy:
        typer.echo("Another run is in progress; try again when it finishes.")
        raise typer.Exit(1) from None
    if problem := push_vault(cfg.vault):
        typer.secho(
            f"warning: vault backup not pushed: {problem}", fg=typer.colors.YELLOW, err=True
        )
    if result.tag:
        typer.echo(
            f"Vault tagged {result.tag} (undo: git -C {cfg.vault} reset --hard {result.tag})"
        )
    typer.echo(
        f"rebuilt: {len(result.done)}, skipped: {len(result.skipped)}, failed: {len(result.failed)}"
    )
    for title, why in [*result.skipped, *result.failed, *result.warnings]:
        typer.secho(f"  {title}: {why}", fg=typer.colors.YELLOW, err=True)
    if result.stopped:
        typer.secho(
            "The LLM is unreachable (is Ollama running?). Nothing was lost: run `sb reingest` again to resume.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
