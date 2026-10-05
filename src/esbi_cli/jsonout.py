"""The `--json` contract (version 1): what an editor plugin reads from `sb`.

Every output is one JSON object per line on stdout, ASCII-safe, carrying `"contract"`; human text
stays on stderr. This module owns every shape: commands call a function here and never build a
dict. An additive change (a new field) keeps CONTRACT; a breaking change bumps it."""

import json
import os
import re
import sys
from contextlib import contextmanager
from typing import NoReturn

import typer

from esbi_cli import __version__
from esbi_cli import schedule as launchd

CONTRACT = 1
_machine_stdout = None  # while human stdout is silenced: the real stream the events go to


def emit(payload: dict) -> None:
    """One object, one line, flushed at once so a reader sees it as it happens."""
    print(
        json.dumps({"contract": CONTRACT, **payload}),
        file=_machine_stdout or sys.stdout,
        flush=True,
    )


def event(kind: str, /, **fields) -> None:  # positional-only: a `step` event has a `name` field
    emit({"event": kind, **fields})


_mode = {"json": False}  # whether the running command was given --json


def set_mode(value: bool) -> bool:
    """The --json option's callback; the root callback resets it for every invocation (the menu and
    the tests run several commands in one process)."""
    _mode["json"] = value
    return value


def fail(message: object, code: str) -> NoReturn:
    """End the command with exit 1: an error object with --json, else the usual line on stderr."""
    if _mode["json"]:
        emit({"error": " ".join(str(message).split()), "code": code})
    else:
        typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@contextmanager
def only_events(active: bool):
    """With --json the human lines a command prints on stdout (progress, summaries) are dropped:
    stdout carries events and nothing else. Warnings go to stderr and are not affected."""
    global _machine_stdout
    if not active:
        yield
        return
    real = sys.stdout
    _machine_stdout, sys.stdout = real, open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    try:
        yield
    finally:
        sys.stdout.close()
        _machine_stdout, sys.stdout = None, real


def step_fields(step: str) -> dict:
    """The progress text `chunk 2 of 6` / `merging section 1 of 3` / `synthesis` as the fields of a
    `step` event."""
    if match := re.fullmatch(r"(chunk|merging section) (\d+) of (\d+)", step):
        return {"name": match[1], "index": int(match[2]), "total": int(match[3])}
    return {"name": step}


def version() -> None:
    emit({"version": __version__})


def status(vault, counts: dict, failed: list, retrying: list) -> None:
    def rows(items):
        return [{"target": i.target, "attempts": i.attempts, "error": i.error or ""} for i in items]

    emit(
        {
            "vault": str(vault.absolute()),
            "queue": {s: counts.get(s, 0) for s in ("queued", "processing", "done", "failed")},
            "failed": rows(failed),
            "retrying": rows(retrying),
        }
    )


def info(cfg, config_path) -> None:
    try:
        installed = launchd.is_loaded(os.getuid(), launchctl=launchd.run_launchctl)
    except OSError:  # no launchd here (not macOS)
        installed = False
    models = {task: llm.model for task, llm in cfg.llm.items()}
    models["ask"] = (cfg.llm.get("ask") or cfg.llm_for("summarize")).model
    emit(
        {
            "version": __version__,
            "config": str(config_path.absolute()),
            "vault": str(cfg.vault.absolute()),
            "viewer": cfg.viewer,
            "language": cfg.language,
            "models": models,
            "nightly": {"installed": installed, "time": cfg.nightly_time},
        }
    )


def doctor(checks: list) -> None:
    emit(
        {
            "ok": not any(c.level == "FAIL" for c in checks),
            "checks": [
                {"level": c.level, "name": c.name, "text": c.text, "fix": c.fix} for c in checks
            ],
        }
    )


def add(queued: int, already_known: int, in_wiki: list[dict]) -> None:
    emit({"queued": queued, "already_known": already_known, "in_wiki": in_wiki})


def ask(answer, saved: str | None) -> None:
    emit(
        {
            "answer": answer.text,
            "cited": answer.citations if answer.grounded else [],
            "refused": not answer.grounded,
            "saved": saved,
        }
    )
