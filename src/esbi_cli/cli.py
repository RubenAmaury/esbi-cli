import json
import os
import shlex
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

from esbi_cli import __version__, jsonout, lang, ocr_models
from esbi_cli import schedule as launchd
from esbi_cli import update as updater
from esbi_cli.ask.answer import answer_question, save_answer
from esbi_cli.bench.cases import load_cases
from esbi_cli.bench.report import render_report, save_report, suggest_routing, summarize
from esbi_cli.bench.runner import run_benchmark
from esbi_cli.capture.inbox import scan_inbox
from esbi_cli.capture.legacy import import_legacy
from esbi_cli.config import (
    Config,
    find_config,
    load_config,
    parse_time,
    reset_loaded,
    wants_update_check,
)
from esbi_cli.doctor import run_checks
from esbi_cli.evaluate import evaluate, load_golden
from esbi_cli.export import export_site
from esbi_cli.extract import ExtractError, extract_source, is_url
from esbi_cli.extract.image import IMAGE_SUFFIXES, NO_OCR
from esbi_cli.gitops import GitError, commit_vault, has_git, push_vault
from esbi_cli.hostos import keychain, this_machine
from esbi_cli.ingest import consolidate as consolidation
from esbi_cli.ingest.pipeline import ingest as run_ingest
from esbi_cli.init import (
    MODELS,
    RUNTIMES,
    connect_remote,
    init_vault,
    local_model,
    set_email_block,
    set_ocr_block,
    write_config,
)
from esbi_cli.interrupts import exit_when_interrupted
from esbi_cli.lint.checks import LintReport, lint_vault
from esbi_cli.lint.report import write_lint_report
from esbi_cli.llm.adapter import LLMError, make_embedder, make_llm, make_ocr
from esbi_cli.mail.credentials import CredentialError, get_password, save_password
from esbi_cli.mail.fetch import MAIL_LINK_ORIGIN, fetch_mail
from esbi_cli.mail.imap import ImapMailClient, MailError
from esbi_cli.privacy import remote_host, remote_warning
from esbi_cli.queue import Queue, normalize_target
from esbi_cli.reingest import reingest_all
from esbi_cli.report.daily_index import build_daily_index
from esbi_cli.report.readstate import sync_read_state, sync_unread_state
from esbi_cli.run import RunLimits, run_queue, spend_usd
from esbi_cli.runlock import LockBusy, RunLock
from esbi_cli.runlog import RunLog, RunRecord, is_due, trim_log
from esbi_cli.vault import Vault

# Rich markup would eat `[notes]`, `[llm.ocr]`, `[run]` in help texts: they are config sections.
Typer = partial(typer.Typer, rich_markup_mode="markdown")
app = Typer(help="esbi-cli: maintain an Obsidian wiki from your saved sources.")
# the one --json option; its callback tells jsonout.fail how to report an error
JSON_OPTION = typer.Option(
    False, "--json", help="Print JSON for a program to read, not text.", callback=jsonout.set_mode
)


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


# Commands after which the update notice never appears: the scheduled run and the ones that manage
# the installation or set it up (the notice would be noise or, for `run`, a network call at night).
NO_NOTICE = {"run", "schedule", "update", "setup", "init", "version", "doctor"}
_command: dict[str, str | None] = {"name": None}  # which command is running: Typer's result
# callback gets no context, so the root callback leaves the name here


def _stderr_is_tty() -> bool:
    return sys.stderr.isatty()


def _update_notice(_result: object = None) -> None:
    """The single hook: runs once after a command that succeeded (Typer skips it when the command
    raises or exits with an error). One line on stderr, only at a terminal, only when a newer
    release is known; the network is asked at most once a day, and never for the commands above."""
    name, _command["name"] = _command["name"], None
    if name is None or name in NO_NOTICE or not _stderr_is_tty():
        return
    if not updater.checks_enabled(wants_update_check()):
        return
    release = updater.cached_latest()
    if release and updater.is_newer(release.version, __version__):
        typer.echo(
            f"esbi-cli {release.version} is available (you have {__version__}). "
            "Update with: sb update",
            err=True,
        )


@app.callback(invoke_without_command=True, result_callback=_update_notice)
def main(ctx: typer.Context) -> None:
    """esbi-cli. Run without a command for a menu."""
    reset_loaded()
    _command["name"] = ctx.invoked_subcommand
    jsonout.set_mode(False)
    if ctx.invoked_subcommand is None:
        _menu()


@app.command()
def version(
    check: bool = typer.Option(
        False, "--check", help="Also ask GitHub for the latest release (the one network call)."
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Print the installed version; with --check, say whether a newer one exists."""
    if as_json:
        jsonout.version()
        return
    if not check:
        typer.echo(__version__)
        return
    release = updater.cached_latest(force=True)
    typer.echo(f"installed: {__version__}")
    if release is None:
        typer.echo("latest:    unknown")
        typer.echo("Could not check for a newer version (offline, or GitHub did not answer).")
    elif updater.is_newer(release.version, __version__):
        typer.echo(f"latest:    {release.version}")
        typer.echo(f"A newer version is available ({release.url}). Update with: sb update")
    else:
        typer.echo(f"latest:    {release.version}")
        typer.echo("You are up to date.")


@app.command("update")
def update_command(
    yes: bool = typer.Option(False, "--yes", "-y", help="Run the command without asking."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only print the command."),
) -> None:
    """Update esbi-cli to the latest release: shows the command for how it was installed, asks, runs it."""
    release = updater.cached_latest(force=True)
    if release is None:
        typer.secho(
            "error: could not check for a newer version (offline, or GitHub did not answer)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    prefix = Path(sys.prefix)
    method = updater.install_method(prefix, PACKAGE_DIR)
    typer.echo(f"installed: {__version__}\nlatest:    {release.version}\nmethod:    {method}")
    if not updater.is_newer(release.version, __version__):
        typer.echo("You are up to date.")
        return
    pin = updater.pinned_source(prefix) if method == "uv-tool" else None
    argv = None if pin else updater.upgrade_command(method, release.version)
    if argv is None:
        typer.echo(updater.manual_message(method, release.version, pin))
        return
    typer.echo(f"Will run: {shlex.join(argv)}")
    if dry_run:
        return
    if not yes:
        if not _interactive():
            typer.secho(
                "error: no terminal to ask in. Run it with --yes, or use --dry-run to only see "
                "the command.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)
        if not typer.confirm("Run it now?", default=False):
            typer.echo("Not run.")
            return
    try:
        code = updater.run_command(argv)
    except FileNotFoundError as exc:
        typer.secho(f"error: `{argv[0]}` was not found on your PATH", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    if code != 0:
        typer.secho(
            f"error: the update command exited with code {code}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code)
    typer.echo("Updated. Run `sb version` to confirm.")
    try:  # launchd is only ever changed by the user: say so, do not do it
        if launchd.is_loaded(os.getuid(), launchctl=launchd.run_launchctl):
            typer.echo("The nightly job was written by the old version: run `sb schedule install`.")
    except OSError:  # no launchd here
        pass


def _open_queue(cfg: Config) -> Queue:
    return Queue(cfg.vault / ".esbi" / "queue.sqlite3")


def _load(config: Path | None, need_vault: bool = True) -> Config:
    try:
        cfg = load_config(config)
    except (FileNotFoundError, ValueError) as exc:
        jsonout.fail(
            exc, "config_not_found" if isinstance(exc, FileNotFoundError) else "bad_config"
        )
    # state is opened under the vault: a vault that is gone must be an error, not a new folder
    if need_vault and not cfg.vault.is_dir():
        jsonout.fail(
            f"vault not found: {cfg.vault} (run `sb init`, or fix [paths].vault)", "vault_not_found"
        )
    return cfg


def _config_path(config: Path | None) -> Path:
    """Which config file applies, or an error line and exit 1."""
    try:
        return find_config(config)
    except FileNotFoundError as exc:
        jsonout.fail(exc, "config_not_found")


def _vault(cfg: Config) -> Vault:
    """The vault, with the dense side of search when [llm.embed] is configured (off by default)."""
    if "embed" not in cfg.llm:
        return Vault(cfg.vault, language=cfg.language)
    try:
        return Vault(cfg.vault, embedder=make_embedder(cfg.llm["embed"]), language=cfg.language)
    except ValueError as exc:
        jsonout.fail(exc, "bad_config")


CONFIG_OPTION = typer.Option(None, "--config", help="Path to config.toml.")


@app.command()
def status(config: Path | None = CONFIG_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Show how many sources are queued, done or failed."""
    cfg = _load(config)
    queue = _open_queue(cfg)
    counts = queue.counts()
    if as_json:
        retrying = [i for i in queue.items("queued") if i.attempts]
        return jsonout.status(cfg.vault, counts, queue.items("failed"), retrying)
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
    return make_ocr(cfg.llm["ocr"]) if cfg.ocr_on else None


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
    as_json: bool = JSON_OPTION,
) -> None:
    """Queue sources to be ingested by the next `sb run` (nothing is fetched now)."""
    cfg = _load(config)
    images = cfg.ocr_on
    bad = [t for t in targets if not _is_source(t, images)]
    if bad and as_json:
        jsonout.fail(f"not a source (URL, .pdf, .md or image file): {', '.join(bad)}", "bad_target")
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
    skipped: list[dict] = []
    for t in targets:
        if title := (in_wiki.get(normalize_target(t)) if is_url(t) else None):
            skipped.append({"target": t, "title": title})
            if not as_json:
                typer.echo(f"Skipped {t}: already in the wiki as [[{title}]]")
        elif queue.add(t, "cli", label=None if is_url(t) else Path(t).stem):
            added += 1
        else:
            known += 1
    if as_json:
        return jsonout.add(added, known, skipped)
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
def doctor(config: Path | None = CONFIG_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Check config, vault, Obsidian, model, mailbox, nightly job and install; say what to fix."""
    checks = run_checks(config)
    if as_json:
        jsonout.doctor(checks)
    else:
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
    result = scan_inbox(_vault(cfg), _open_queue(cfg), images=cfg.ocr_on)
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
    if put_back := sync_unread_state(vault):
        typer.echo(f"Put {len(put_back)} source{'s' if len(put_back) != 1 else ''} back to unread.")
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
        help=(
            "Scheduled mode: run only if today's nightly run has not happened yet, or if the "
            "latest scheduled run stopped at the source limit ([run].max_sources_per_run) and "
            "sources are still queued: the hourly tick then runs the next batch. Never when the "
            "last run stopped for an outage, an interruption or a budget, nor while another run "
            "is active."
        ),
    ),
    as_json: bool = JSON_OPTION,
) -> None:
    """Scan the inbox, then ingest queued sources within the configured limits.

    Limits: [run].max_sources_per_run, max_tokens_per_run and max_usd_per_run (an estimate from
    [bench.prices]; models that run here and claude-cli/codex-cli subscriptions count as 0 USD).
    A run that hits a limit puts the rest back in the queue, untouched.
    """
    cfg = _load(config)
    on_event = jsonout.event if as_json else None  # JSON Lines: one event per line
    with jsonout.only_events(as_json):
        try:
            with RunLock(cfg.vault / ".esbi" / "run.lock"):
                _run_locked(cfg, max_sources, if_due, on_event)
        except LockBusy:
            if as_json:
                jsonout.emit({"error": "Another run is in progress.", "code": "run_in_progress"})
            typer.echo("Another run is in progress; skipping.")


def _writers(cfg: Config):
    """(reader, synthesizer, private). The synthesis model is optional: it writes the digest and
    the connections, so it can be a stronger, slower model than the one taking chunk notes. The
    private model, also optional, is the only one that ever reads email."""
    reader = make_llm(cfg.llm_for("summarize"))
    synth = make_llm(cfg.llm["synthesize"]) if "synthesize" in cfg.llm else None
    private = make_llm(cfg.llm["private"]) if "private" in cfg.llm else None
    return reader, synth, private


def _run_locked(cfg: Config, max_sources: int | None, if_due: bool, on_event=None) -> None:
    vault, queue = _vault(cfg), _open_queue(cfg)
    trim_log(cfg.vault / ".esbi" / "logs" / "nightly.log")
    runlog = RunLog(cfg.vault / ".esbi" / "runs.jsonl")
    started = datetime.now()
    if if_due and not is_due(
        runlog.runs(), started, cfg.nightly_at, queued=queue.counts().get("queued", 0)
    ):
        typer.echo("Not due: the nightly run already happened.")
        if on_event:
            on_event("finished", ingested=0, failed=0, skipped=0, tokens=0, stopped_by="not_due")
        return
    try:
        llm, synth, private = _writers(cfg)
        ocr = _ocr(cfg)
    except (KeyError, ValueError) as exc:
        jsonout.fail(exc, "bad_config")

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

    touched: list[str] = []  # the pages this run wrote: the candidates for a new summary

    def ingest_and_commit(target: str):
        item = queue.get(target)  # legacy items remember when they were saved

        def on_step(step: str) -> None:
            typer.echo(f"    ... {step}")
            if on_event:
                on_event("step", target=target, **jsonout.step_fields(step))

        result = run_ingest(
            target,
            vault=vault,
            llm=llm,
            synth_llm=synth,
            private_llm=private,
            cfg=cfg,
            extractor=_extractor(cfg, ocr),
            captured=item.captured if item else None,
            on_step=on_step,
            from_email=bool(item and item.origin == MAIL_LINK_ORIGIN),
        )
        if on_event and (result.applied or result.existing_title):  # ingested, or already known
            title = result.applied.source_title if result.applied else result.existing_title
            note = (
                result.applied.source_path if result.applied else vault.page_path("sources", title)
            )
            on_event(
                "source_done", target=target, title=title, note=str(note.relative_to(cfg.vault))
            )
        if result.applied:
            typer.echo(f"  + {result.applied.source_title}")
            touched.extend([*result.applied.created, *result.applied.updated])
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
        RunLimits(
            max_sources or cfg.max_sources_per_run, cfg.max_tokens_per_run, cfg.max_usd_per_run
        ),
        tokens_used=lambda: sum(m.tokens_used for m in (llm, synth, private, ocr) if m),
        usd_spent=lambda: spend_usd(  # the OCR model is local: never priced
            [
                (cfg.llm[task], model)
                for task, model in (("summarize", llm), ("synthesize", synth), ("private", private))
                if model
            ],
            cfg.bench.prices,
        ),
        on_event=on_event,
    )
    if on_event:
        on_event(
            "finished",
            ingested=summary.ingested,
            failed=summary.failed,
            skipped=summary.skipped,
            tokens=summary.tokens_used,
            stopped_by=summary.stopped_by,
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
    if summary.stopped_by == "interrupted":  # no lint or index: the user asked to stop
        typer.secho(
            f"Interrupted: {summary.released} {'item' if summary.released == 1 else 'items'} "
            "put back in the queue.",
            fg="yellow",
            err=True,
        )
        raise typer.Exit(128 + summary.signum)
    if summary.stopped_by != "llm_unavailable":
        _consolidate_due(cfg, vault, touched, (llm, synth, private))
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


def _report_consolidation(result: consolidation.ConsolidateResult) -> None:
    typer.echo(
        f"consolidated: {len(result.done)}, skipped: {len(result.skipped)}, "
        f"to review: {len(result.reviews)}, merge suggestions: {len(result.suggestions)}"
    )
    for title, why in result.skipped:
        typer.secho(f"  {title}: {why}", fg=typer.colors.YELLOW, err=True)
    for warning in result.warnings:
        typer.secho(f"  warning: {warning}", fg=typer.colors.YELLOW, err=True)


def _consolidate_due(
    cfg: Config, vault: Vault, titles: list[str], models, commit: bool = True
) -> None:
    """The automatic pass after an ingest: a summary for the pages that just got enough sources,
    at most `max_consolidations_per_run` of them."""
    llm, synth, private = models
    result = consolidation.consolidate_due(
        vault,
        titles,
        llm,
        synth,
        private,
        limit=cfg.max_consolidations_per_run,
        commit=commit,
        on_progress=lambda line: typer.echo(f"  ... {line}"),
    )
    if result.done or result.skipped or result.reviews or result.suggestions:
        _report_consolidation(result)


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
        "unsupported": len(answer.unsupported),
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
    as_json: bool = JSON_OPTION,
) -> None:
    """Answer a question from the wiki only, citing the pages used."""
    cfg = _load(config)
    vault = _vault(cfg)
    try:
        llm = make_llm(cfg.llm.get("ask") or cfg.llm_for("summarize"))
        started = time.monotonic()
        answer = answer_question(
            vault,
            llm,
            question,
            rewrite=cfg.rewrite_questions,
            check_support=cfg.check_answers,
        )
    except (KeyError, ValueError, LLMError) as exc:
        jsonout.fail(exc, "llm_error" if isinstance(exc, LLMError) else "bad_config")
    _log_question(cfg, question, answer, llm, time.monotonic() - started)
    if not as_json:
        typer.echo(answer.text)
        if answer.grounded:
            typer.echo("\nSources: " + ", ".join(f"[[{c}]]" for c in answer.citations))
    saved = None
    if answer.grounded and save:
        saved = save_answer(vault, answer, date.today())
        if not as_json:
            typer.echo(f"Saved {saved.relative_to(vault.root)}")
        try:
            commit_vault(cfg.vault, f"ask: {saved.stem}")
        except GitError as exc:
            typer.secho(f"warning: git commit failed: {exc}", fg=typer.colors.YELLOW, err=True)
    if as_json:
        jsonout.ask(answer, str(saved.relative_to(vault.root)) if saved else None)


@app.command()
def info(config: Path | None = CONFIG_OPTION, as_json: bool = JSON_OPTION) -> None:
    """Print where things are, as key=value lines (the setup wizards read this)."""
    cfg = _load(config)
    if as_json:
        return jsonout.info(cfg, find_config(config))
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
        None, "--cases", help="Cases per task (default: [bench].cases in config.toml)."
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
        result = fetch_mail(
            client,
            vault,
            _open_queue(cfg) if cfg.email.follow_links else None,
            cfg.email.follow_links,
            cfg.email.follow_links_max,
        )
    finally:
        client.close()
    extras = "".join(
        f", {n} {what}"
        for n, what in (
            (result.images, "images saved"),
            (result.links, "links queued"),
            (result.unmarked, "not marked as read (the server refused)"),
        )
        if n
    )
    typer.echo(
        f"Mail: {result.saved} saved, {result.duplicates} duplicates, {result.failed} failed{extras}."
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
    """Store the mailbox app password in the macOS Keychain, or the system keyring elsewhere
    (typed hidden, never shown).

    There is no `--password` option on purpose: an argument ends up in your shell history and in
    the process list."""
    cfg = _load(config, need_vault=False)
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
    typer.echo(f"Saved to the {keychain()}.")


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
    cfg = _load(config)
    try:
        llm, synth, private = _writers(cfg)
        with exit_when_interrupted():
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
    _consolidate_due(
        cfg, _vault(cfg), [*applied.created, *applied.updated], (llm, synth, private), not no_commit
    )


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
        help="Where the local runtime's server is, if not on this machine (a local model only).",
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
        None,
        "--ocr/--no-ocr",
        help="Read images and scanned PDFs with a local Ollama vision model (off unless asked).",
    ),
    ocr_model: str = typer.Option(
        None,
        "--ocr-model",
        help="Which Ollama vision model reads images (default: the best one this machine can run).",
    ),
    pull_ocr_model: bool = typer.Option(
        False,
        "--pull-ocr-model",
        help="Download the vision model now if Ollama does not have it (never without this flag).",
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
                        f"On {this_machine()} with a local model (nothing leaves it)",
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
    if (ocr_model or pull_ocr_model) and ocr is not True:
        typer.secho("error: --ocr-model and --pull-ocr-model go with --ocr", fg="red", err=True)
        raise typer.Exit(1)
    if base_url is None and ask_user and model == "local":
        base_url = (
            typer.prompt(f"Server address (Enter if it runs on {this_machine()})", default="")
            or None
        )
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

    ocr_name = _init_ocr_model(ocr, ocr_model, ask_user=ask_user, runtime=runtime)
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
        ocr=ocr_name or False,
        base_url=base_url,
        language=language,
    )
    typer.echo(f"Vault {root}: " + (", ".join(made) if made else "nothing to create"))
    typer.echo(f"Config {config_file}: " + ("written" if wrote else "already there, left alone"))
    typer.echo(f"Notes language: {language} ({lang.name(language)}). The CLI itself is English.")
    typer.echo(f"Model: {model}. {MODELS[model].format(machine=this_machine())}")
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
    ocr_ready = True
    if ocr_name and not wrote:
        typer.echo(
            "Images: the config already exists and was left alone; `sb ocr enable` turns on "
            "reading images in it."
        )
    elif ocr_name:
        _ocr_advice(ocr_name, ocr_models.DEFAULT_BASE)
        ocr_ready = _ocr_model_step(
            ocr_name, ocr_models.DEFAULT_BASE, pull=pull_ocr_model, ask=ask_user
        )
    if ask_user:
        _offer_integrations(config_file.resolve(), obsidian)
    steps = []
    if runtime == "ollama" and model != "api":
        steps.append("ollama pull llama3.2")
    if ocr_name and wrote and not ocr_ready:
        steps.append(f"ollama pull {ocr_name}")
    steps.append("sb doctor")
    typer.echo(
        f"\nNext: {', then '.join(steps)}. Add a link with `sb add URL` or drop a PDF in the "
        "vault's inbox/ folder."
    )


def _init_ocr_model(ocr: bool | None, named: str | None, *, ask_user: bool, runtime: str):
    """The vision model `sb init` should set up, or None when images stay off. Asks only at a
    keyboard; everything that can be refused is checked here, before anything is written."""
    if ocr is None and ask_user and runtime == "ollama":
        ocr = typer.confirm(
            "Read images and scanned PDFs (jpg, png, ...)? It needs a local vision model.",
            default=False,
        )
    if not ocr:
        return None
    if named is not None:
        return _model_name(named)
    ram = ocr_models.machine_ram_gb()
    best = ocr_models.RECOMMENDED
    if not ask_user:
        return best.name
    options = [
        f"{p.name}: {p.size_gb:g} GB download, {p.min_ram_gb} GB of memory or more. {p.note}"
        + (" (recommended for this machine)" if p is best else "")
        for p in ocr_models.PRESETS
    ] + ["Another Ollama vision model (you type its name)"]
    heard = f"This machine has {ram:.0f} GB of memory." if ram else "Its memory is unknown."
    pick = _choose(
        f"Which vision model should read images? {heard}",
        options,
        1 + ocr_models.PRESETS.index(best),
    )
    if pick <= len(ocr_models.PRESETS):
        return ocr_models.PRESETS[pick - 1].name
    while True:
        try:
            return ocr_models.clean_name(typer.prompt("Ollama model name"))
        except ValueError as exc:
            typer.echo(f"  {exc}")


def _model_name(text: str) -> str:
    try:
        return ocr_models.clean_name(text)
    except ValueError as exc:
        typer.secho(f"error: model name: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc


def _ocr_advice(name: str, base: str) -> None:
    """Warn (never block) when this machine or this Ollama is likely too small for the model."""
    known = ocr_models.preset(name)
    if not known:
        return
    ram = ocr_models.machine_ram_gb()
    if ram is not None and ram < known.min_ram_gb:
        typer.secho(
            f"warning: {name} is best with {known.min_ram_gb} GB of memory or more and this "
            f"machine has {ram:.0f} GB, so it may not load. {ocr_models.RECOMMENDED.name} "
            "fits this machine (`sb ocr enable --model NAME`).",
            fg="yellow",
        )
    have = ocr_models.ollama_version(base)
    if not ocr_models.version_at_least(have, known.min_ollama):
        typer.secho(
            f"warning: Ollama {have} is older than the {known.min_ollama} that {name} needs: "
            "upgrade Ollama (`brew upgrade ollama`, or update the app).",
            fg="yellow",
        )


def _pull_progress():
    """A progress printer for Ollama's pull: one line per layer and each 10% step."""
    last: list = [None, None]

    def show(status: str, done: float | None) -> None:
        step = None if done is None else int(done * 10) * 10
        if [status, step] != last:
            last[:] = [status, step]
            typer.echo(f"  {status}" + ("" if step is None else f" {step}%"))

    return show


def _ocr_model_step(name: str, base: str, *, pull: bool, ask: bool) -> bool:
    """Say whether Ollama has the model; fetch it only on `pull` (the flag) or a typed yes when
    `ask` (a person is there). True when the model is installed at the end."""
    command = f"ollama pull {name}"
    have = ocr_models.installed_models(base)
    if have is None:
        typer.echo(f"Ollama is not reachable at {base}. Start it, then fetch the model: {command}")
        return False
    if ocr_models.is_installed(name, have):
        typer.echo(f"{name} is already installed.")
        return True
    known = ocr_models.preset(name)
    size = f" ({known.size_gb:g} GB)" if known else ""
    if not pull and not (
        ask and typer.confirm(f"{name} is not installed{size}. Download it now?", default=False)
    ):
        typer.echo(f"{name} is not installed{size}. When you want it: {command}")
        return False
    typer.echo(f"Downloading {name}{size}. Ollama resumes if this is interrupted.")
    try:
        ocr_models.pull(base, name, _pull_progress())
    except ocr_models.PullError as exc:
        typer.secho(f"warning: {exc}", fg="yellow")
        typer.echo(f"Fetch it yourself: {command}")
        return False
    typer.echo(f"{name} is installed.")
    return True


ocr_app = Typer(help="Read images and scanned PDFs with a local vision model (optional).")
app.add_typer(ocr_app, name="ocr")


@ocr_app.command("status")
def ocr_status(config: Path | None = CONFIG_OPTION) -> None:
    """Is reading images on, which model, is it installed, and can this machine run it."""
    cfg = _load(config, need_vault=False)
    ram = ocr_models.machine_ram_gb()
    heard = f"{ram:.0f} GB" if ram else "unknown"
    llm = cfg.llm.get("ocr")
    if llm is None:
        typer.echo("Reading images and scanned PDFs: off (never set up).")
        typer.echo(f"Machine memory: {heard}. Recommended model: {ocr_models.RECOMMENDED.name}.")
        typer.echo("Turn it on with `sb ocr enable` (add --pull to download the model).")
        return
    name = llm.model.partition("/")[2]
    base = llm.base_url or ocr_models.DEFAULT_BASE
    typer.echo(
        "Reading images and scanned PDFs: on."
        if cfg.ocr_on
        else "Reading images and scanned PDFs: off (the model choice is kept; `sb ocr enable` "
        "switches it on)."
    )
    typer.echo(f"Model: {llm.model}")
    have = ocr_models.installed_models(base)
    known = ocr_models.preset(name)
    if have is None:
        typer.echo(f"Ollama is not reachable at {base}: cannot tell if the model is installed.")
    elif ocr_models.is_installed(name, have):
        typer.echo("The model is installed in Ollama.")
    else:
        typer.echo(f"The model is not installed: ollama pull {name}")
    if known:
        typer.echo(f"Download size: {known.size_gb:g} GB.")
    typer.echo(f"Machine memory: {heard}.")
    if known and ram is not None:
        fits = (
            "this machine can likely run it."
            if ram >= known.min_ram_gb
            else "it may not load here."
        )
        typer.echo(f"This model is best with {known.min_ram_gb} GB or more: {fits}")
    version = ocr_models.ollama_version(base)
    if version is None:
        typer.echo(f"Ollama: not reachable at {base}.")
    elif known:
        old = not ocr_models.version_at_least(version, known.min_ollama)
        need = f"the model needs {known.min_ollama} or later"
        typer.echo(f"Ollama: {version} ({need}{'; upgrade Ollama' if old else ''}).")
    else:
        typer.echo(f"Ollama: {version}.")


@ocr_app.command("enable")
def ocr_enable(
    model: str = typer.Option(
        None,
        "--model",
        help="Which Ollama vision model (default: the current one, else the best this machine can run).",
    ),
    pull: bool = typer.Option(
        False, "--pull", help="Download the model now if Ollama does not have it."
    ),
    config: Path | None = CONFIG_OPTION,
) -> None:
    """Turn on reading images and scanned PDFs, and get the model (or see it is installed)."""
    cfg = _load(config, need_vault=False)
    path = _config_path(config)
    current = cfg.llm.get("ocr")
    if model is not None:
        name = _model_name(model)
    elif current and current.model.startswith("ollama/"):
        name = _model_name(current.model)
    else:
        name = ocr_models.RECOMMENDED.name
    set_ocr_block(path, model=name, enabled=True)
    typer.echo(f"Reading images and scanned PDFs is on, with {name}. Changed: [llm.ocr] in {path}")
    base = (current.base_url if current else None) or ocr_models.DEFAULT_BASE
    _ocr_advice(name, base)
    _ocr_model_step(name, base, pull=pull, ask=_interactive())


@ocr_app.command("disable")
def ocr_disable(config: Path | None = CONFIG_OPTION) -> None:
    """Turn off reading images and scanned PDFs (the model choice stays in the config)."""
    cfg = _load(config, need_vault=False)
    if not cfg.ocr_on:
        typer.echo("Reading images and scanned PDFs is already off.")
        return
    path = _config_path(config)
    set_ocr_block(path, enabled=False)
    typer.echo(
        f"Reading images and scanned PDFs is off. [llm.ocr] in {path} keeps the model; "
        "`sb ocr enable` turns it back on."
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
def consolidate(
    config: Path | None = CONFIG_OPTION,
    all_pages: bool = typer.Option(
        False, "--all", help="Every concept and entity with two or more sources, not only the due."
    ),
    only: list[str] = typer.Option(
        None, "--only", help="Only pages whose title contains this word (repeat for several)."
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="List the pages that would be summarised; ask no model, write nothing.",
    ),
) -> None:
    """Write a consolidated Summary on top of concept and entity pages from their per-source sections.

    Without options: the pages with three or more sources and no summary, or two or more sources
    since the last one (the nightly run does the same for the pages it touched, up to
    `[run].max_consolidations_per_run`; this command has no cap). A summary that fails its checks
    goes to wiki/review/ and the page stays as it was. Pages that look like the same idea as another
    get a merge suggestion in wiki/review/; nothing is merged for you. One commit per page.
    """
    cfg = _load(config)
    vault = _vault(cfg)
    pages = consolidation.pick(vault, all_pages=all_pages, only=only)
    if not pages:
        typer.echo("Nothing to consolidate.")
        return
    if dry_run:
        typer.echo(f"Would write a summary for {len(pages)} page(s):")
        for page in pages:
            typer.echo(f"  {page.title} ({len(page.meta.get('sources') or [])} sources)")
        return
    try:
        llm, synth, private = _writers(cfg)
    except (KeyError, ValueError) as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    try:
        with RunLock(cfg.vault / ".esbi" / "run.lock"):
            result = consolidation.consolidate_pages(
                vault, pages, llm, synth, private, on_progress=typer.echo
            )
    except LockBusy:
        typer.echo("Another run is in progress; try again when it finishes.")
        raise typer.Exit(1) from None
    if problem := push_vault(cfg.vault):
        typer.secho(
            f"warning: vault backup not pushed: {problem}", fg=typer.colors.YELLOW, err=True
        )
    _report_consolidation(result)
    if result.stopped:
        typer.secho(
            "The LLM is unreachable (is Ollama running?). Nothing was lost: run `sb consolidate` again.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)


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
        with exit_when_interrupted(), RunLock(cfg.vault / ".esbi" / "run.lock"):
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
