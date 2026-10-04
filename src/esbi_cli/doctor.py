"""`sb doctor`: check the whole setup and say what to fix. Warnings are inconvenient, FAIL is broken."""

import json
import os
import plistlib
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from esbi_cli import lang
from esbi_cli import schedule as launchd
from esbi_cli.config import Config, find_config, load_config
from esbi_cli.gitops import has_git
from esbi_cli.llm.adapter import make_llm, make_ocr
from esbi_cli.mail.credentials import CredentialError, get_password
from esbi_cli.privacy import remote_host, remote_warning
from esbi_cli.queue import Queue
from esbi_cli.runlog import RunLog

KEY_VARS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
SERVER_PROBE_TIMEOUT_SECONDS = 3  # a model server that does not answer this fast is down
CLAUDE_STATUS_TIMEOUT_SECONDS = 20


@dataclass
class Check:
    level: str  # "ok" | "WARN" | "FAIL"
    name: str
    text: str
    fix: str = ""


def _model(task: str, cfg: Config, fallback: bool = False) -> Check:
    llm = cfg.llm[task]
    if fallback:  # the fallback inherits the section's settings, with its own model
        llm = replace(llm, model=llm.fallback)
        task = f"{task} fallback"
    provider, _, name = llm.model.partition("/")
    label = f"model {task}"
    if provider == "ollama":
        base = (llm.base_url or "http://localhost:11434").rstrip("/")
        try:
            tags = httpx.get(f"{base}/api/tags", timeout=SERVER_PROBE_TIMEOUT_SECONDS).json()[
                "models"
            ]
        except (httpx.HTTPError, KeyError, ValueError):
            return Check(
                "FAIL",
                label,
                f"Ollama is not reachable at {base}",
                "brew services start ollama (or open the Ollama app)",
            )
        have = {m["name"] for m in tags}
        if name in have or f"{name}:latest" in have:
            return Check("ok", label, f"{llm.model} is installed")
        return Check("FAIL", label, f"{llm.model} is not installed", f"ollama pull {name}")
    if provider == "lmstudio":
        base = (llm.base_url or "http://localhost:1234/v1").rstrip("/")
        try:
            served = {
                m["id"]
                for m in httpx.get(f"{base}/models", timeout=SERVER_PROBE_TIMEOUT_SECONDS).json()[
                    "data"
                ]
            }
        except (httpx.HTTPError, KeyError, ValueError):
            return Check(
                "FAIL",
                label,
                f"LM Studio is not reachable at {base}",
                "open LM Studio, load a model, and start the local server (Developer tab)",
            )
        if name in served:
            return Check("ok", label, f"{llm.model} is served by LM Studio")
        return Check(
            "FAIL",
            label,
            f"LM Studio does not serve {name!r}",
            f"use one of: {', '.join(sorted(served)) or '(none loaded)'}",
        )
    if provider == "claude-cli":
        if not shutil.which("claude"):
            return Check(
                "FAIL", label, "the `claude` command is not installed", "https://claude.com/code"
            )
        try:
            who = json.loads(
                subprocess.run(
                    ["claude", "auth", "status"],
                    capture_output=True,
                    text=True,
                    timeout=CLAUDE_STATUS_TIMEOUT_SECONDS,
                ).stdout
            )
        except (OSError, subprocess.TimeoutExpired, ValueError):
            who = {}
        if who.get("loggedIn"):
            return Check(
                "ok", label, f"{llm.model} (subscription of {who.get('email', 'your account')})"
            )
        return Check("FAIL", label, "`claude` is not logged in", "claude auth login")
    if provider in KEY_VARS:
        env = llm.api_key_env or KEY_VARS[provider]
        if os.environ.get(env):
            return Check("ok", label, f"{llm.model} (key in ${env})")
        return Check("FAIL", label, f"{llm.model}: ${env} is not set", f"export {env}=...")
    return Check(
        "FAIL",
        label,
        f"unknown provider in {llm.model!r}",
        "use ollama/, lmstudio/, openai/, anthropic/ or claude-cli/",
    )


def _ocr(cfg: Config) -> list[Check]:
    """Reading images and scanned PDFs is optional; when set up it must be a model on this machine."""
    if "ocr" not in cfg.llm:
        return [
            Check(
                "ok",
                "ocr",
                "off (optional): add [llm.ocr] to read images and scanned PDFs "
                "(`sb init --ocr`, docs/reference/configuration.md)",
            )
        ]
    try:
        make_ocr(cfg.llm["ocr"])
    except ValueError as exc:
        return [Check("FAIL", "ocr", str(exc), 'model = "ollama/qwen3-vl:2b-instruct"')]
    return [_model("ocr", cfg)]


def _sends_text_out(llm_cfg) -> bool:
    try:
        return bool(make_llm(llm_cfg).sends_text_out)  # building a model makes no request
    except ValueError:
        return False  # an unknown provider is reported by the model check


def _privacy(cfg: Config) -> Check:
    """Email must be read only by a model on this machine, and cloud models must never get it."""
    private = cfg.llm.get("private")
    if private and _sends_text_out(private):
        return Check(
            "FAIL",
            "email privacy",
            "[llm.private] (or its fallback) sends text away, so email would leave this machine",
            'use a local model: [llm.private] model = "ollama/llama3.2:latest", with no cloud fallback',
        )
    cloud = [t for t, m in cfg.llm.items() if t not in ("private", "embed") and _sends_text_out(m)]
    if not cloud or private:
        return Check(
            "ok",
            "email privacy",
            "email is read only by a model on this machine" if private else "all models are local",
        )
    return Check(
        "WARN",
        "email privacy",
        f"{', '.join(cloud)} send text away and no [llm.private] is set: emails will be refused",
        'add [llm.private] model = "ollama/llama3.2:latest" to config.toml',
    )


def _remote_servers(cfg: Config) -> list[Check]:
    """A "local" runtime pointed at another machine still sends the notes' text out. (A remote
    [llm.private] is already a FAIL in _privacy: there email would go to that host.)"""
    checks = []
    for task, llm in cfg.llm.items():
        for label, model in ((task, llm.model), (f"{task} fallback", llm.fallback)):
            host = model and task != "private" and remote_host(model, llm.base_url)
            if host:
                checks.append(
                    Check(
                        "WARN",
                        f"server {label}",
                        remote_warning(model, host),
                        "serve the model from this machine, or use it only for text you would share",
                    )
                )
    return checks


def _email(cfg: Config) -> Check:
    if not cfg.email.enabled:
        return Check("ok", "email", "off (optional)")
    try:
        get_password(cfg.email.user or "")
        return Check("ok", "email", f"password for {cfg.email.user} is in the Keychain")
    except CredentialError as exc:
        return Check("FAIL", "email", str(exc), "sb email set-password")


AGENTS_DIR = Path("~/Library/LaunchAgents").expanduser()


def _installed_time() -> tuple[int, int] | None:
    """The (hour, minute) in the installed LaunchAgent, if there is one."""
    try:
        plist = plistlib.loads((AGENTS_DIR / f"{launchd.LABEL}.plist").read_bytes())
        at = plist["StartCalendarInterval"]
        return at["Hour"], at["Minute"]
    except (OSError, KeyError, ValueError):
        return None


def _job(cfg: Config) -> Check:
    try:
        loaded = launchd.is_loaded(os.getuid(), launchctl=launchd.run_launchctl)
    except OSError:
        return Check("WARN", "nightly job", "launchd is not available here")
    if not loaded:
        return Check("WARN", "nightly job", "not installed", "sb schedule install")
    installed = _installed_time()
    if installed is not None and installed != cfg.nightly_at:
        return Check(
            "WARN",
            "nightly job",
            f"installed for {installed[0]:02d}:{installed[1]:02d} but config.toml says {cfg.nightly_time}",
            "sb schedule install",
        )
    return Check("ok", "nightly job", f"installed and loaded, runs at {cfg.nightly_time}")


def _last_run(vault: Path) -> Check:
    runs = [r for r in RunLog(vault / ".esbi" / "runs.jsonl").runs() if r.trigger == "scheduled"]
    if not runs:
        return Check(
            "WARN",
            "last run",
            "no scheduled run yet",
            "the job does it after the nightly time; or try `sb run --if-due`",
        )
    last = runs[-1]
    text = f"{last.started:%Y-%m-%d %H:%M}: {last.ingested} ingested, {last.failed} failed"
    if last.stopped_by == "llm_unavailable":
        return Check(
            "WARN", "last run", f"{text}; the model was unreachable", "check the model line above"
        )
    return Check("ok", "last run", text)


def _vault(root: Path, viewer: str = "obsidian") -> list[Check]:
    if not (root / "SCHEMA.md").is_file() or not (root / "wiki").is_dir():
        return [
            Check(
                "FAIL",
                "vault",
                f"{root} is not a esbi-cli vault (SCHEMA.md or wiki/ missing)",
                "fix [paths].vault in config.toml",
            )
        ]
    checks = [Check("ok", "vault", str(root))]
    if not (root / ".git").exists():
        checks.append(
            Check(
                "ok", "vault history", "off: git is not installed (optional, `sb init` turns it on)"
            )
            if not has_git()
            else Check(
                "WARN",
                "vault history",
                "no version history (the vault is not a git repository)",
                f"git -C {root} init",
            )
        )
    if viewer == "none":
        checks.append(Check("ok", "obsidian", 'not used ([notes].viewer = "none")'))
    elif not (root / ".obsidian").is_dir():
        checks.append(
            Check(
                "WARN",
                "obsidian",
                "this folder was never opened as a vault in Obsidian",
                f"Obsidian > Open folder as vault > {root}",
            )
        )
    else:
        checks.append(Check("ok", "obsidian", "opened as a vault"))
    counts = Queue(root / ".esbi" / "queue.sqlite3").counts()
    text = ", ".join(f"{n} {state}" for state, n in sorted(counts.items())) or "empty"
    if counts.get("failed"):
        checks.append(Check("WARN", "queue", text, "sb status, then `sb retry` or `sb drop`"))
    else:
        checks.append(Check("ok", "queue", text))
    return checks + [_last_run(root)]


def run_checks(config_arg: Path | None) -> list[Check]:
    try:
        path = find_config(config_arg)
        cfg = load_config(path)
    except (FileNotFoundError, ValueError) as exc:
        return [
            Check(
                "FAIL",
                "config",
                str(exc),
                "correct the setting named in the message"
                if isinstance(exc, ValueError)
                else "run `sb init`, or point at your file with --config PATH",
            )
        ]
    checks = [
        Check("ok", "config", str(path)),
        Check("ok", "notes language", f"{cfg.language} ({lang.name(cfg.language)})"),
        *_vault(cfg.vault, cfg.viewer),
    ]
    for task in ("summarize", "synthesize", "ask", "private", "embed"):
        if task in cfg.llm:
            checks.append(_model(task, cfg))
            if cfg.llm[task].fallback:
                checks.append(_model(task, cfg, fallback=True))
    checks += _ocr(cfg)
    checks.append(_privacy(cfg))
    checks += _remote_servers(cfg)
    checks += [_email(cfg), _job(cfg)]
    sb = shutil.which("sb")
    project = Path(__file__).resolve().parents[2]
    checks.append(
        Check("ok", "global install", sb)
        if sb
        else Check(
            "WARN",
            "global install",
            "`sb` is not on your PATH",
            f"uv tool install --editable {project}",
        )
    )
    return checks
