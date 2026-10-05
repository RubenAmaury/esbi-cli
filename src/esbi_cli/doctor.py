"""`sb doctor`: check the whole setup and say what to fix. Warnings are inconvenient, FAIL is broken."""

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from esbi_cli import __version__, lang, ocr_models, update
from esbi_cli import schedule as launchd
from esbi_cli.config import Config, find_config, home_path, load_config
from esbi_cli.gitops import has_git
from esbi_cli.hostos import keychain
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


def _start_ollama() -> str:
    if sys.platform == "darwin":
        return "brew services start ollama (or open the Ollama app)"
    return "start it: `ollama serve` (or `sudo systemctl start ollama` if it was installed as a service)"


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
                _start_ollama(),
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
    if provider == "codex-cli":
        if not shutil.which("codex"):
            return Check(
                "FAIL",
                label,
                "the `codex` command is not installed",
                "https://github.com/openai/codex",
            )
        try:  # prints "Logged in using ..." to stderr; exit 0 means logged in, 1 means not
            logged_in = (
                subprocess.run(
                    ["codex", "login", "status"],
                    capture_output=True,
                    text=True,
                    timeout=CLAUDE_STATUS_TIMEOUT_SECONDS,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            logged_in = False
        if logged_in:
            return Check("ok", label, f"{llm.model} (your ChatGPT plan through `codex`)")
        return Check("FAIL", label, "`codex` is not logged in", "codex login")
    if provider in KEY_VARS:
        env = llm.api_key_env or KEY_VARS[provider]
        if os.environ.get(env):
            return Check("ok", label, f"{llm.model} (key in ${env})")
        return Check("FAIL", label, f"{llm.model}: ${env} is not set", f"export {env}=...")
    return Check(
        "FAIL",
        label,
        f"unknown provider in {llm.model!r}",
        "use ollama/, lmstudio/, openai/, anthropic/, claude-cli/ or codex-cli/",
    )


def _ocr(cfg: Config) -> list[Check]:
    """Reading images and scanned PDFs is optional; when on it must be a model on this machine."""
    if not cfg.ocr_on:
        kept = f" ({cfg.llm['ocr'].model} is kept)" if "ocr" in cfg.llm else ""
        return [
            Check(
                "ok",
                "ocr",
                f"off (optional){kept}: `sb ocr enable` turns on reading images and scanned PDFs "
                "with a local vision model ([llm.ocr], "
                "https://rubenamaury.github.io/esbi-cli/docs/reference/configuration/)",
            )
        ]
    llm = cfg.llm["ocr"]
    try:
        make_ocr(llm)
    except ValueError as exc:
        return [Check("FAIL", "ocr", str(exc), 'model = "ollama/qwen3-vl:2b-instruct"')]
    checks = [_model("ocr", cfg)]
    name = llm.model.partition("/")[2]
    known = ocr_models.preset(name)
    if not known:
        return checks
    ram = ocr_models.machine_ram_gb()
    if ram is not None and ram < known.min_ram_gb:
        checks.append(
            Check(
                "WARN",
                "ocr memory",
                f"{name} is best with {known.min_ram_gb} GB of memory or more; this machine has "
                f"{ram:.0f} GB, so it may not load",
                f"sb ocr enable --model {ocr_models.RECOMMENDED.name}",
            )
        )
    have = ocr_models.ollama_version(llm.base_url or ocr_models.DEFAULT_BASE)
    if not ocr_models.version_at_least(have, known.min_ollama):
        checks.append(
            Check(
                "WARN",
                "ocr ollama",
                f"Ollama {have} is older than the {known.min_ollama} that {name} needs",
                "upgrade Ollama (`brew upgrade ollama`, or update the Ollama app)",
            )
        )
    return checks


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


def _network(cfg: Config) -> list[Check]:
    if not cfg.network.use_environment_proxy:
        return []
    return [
        Check(
            "WARN",
            "network",
            "[network].use_environment_proxy is on: address checks are done by the proxy, not by "
            "esbi-cli, so a link in an email could make the proxy reach an internal host",
            "set it to false unless this network only has a proxy",
        )
    ]


def _email(cfg: Config) -> Check:
    if not cfg.email.enabled:
        return Check("ok", "email", "off (optional)")
    try:
        get_password(cfg.email.user or "")
        return Check("ok", "email", f"password for {cfg.email.user} is in the {keychain()}")
    except CredentialError as exc:
        return Check("FAIL", "email", str(exc), "sb email set-password")


def _version(cfg: Config) -> Check:
    """The installed version, and whether a newer one is known (from the daily cache)."""
    if not update.checks_enabled(cfg.update.check):
        return Check("ok", "version", f"{__version__} (update check is off)")
    release = update.cached_latest()
    if release is None:  # offline, or GitHub did not answer: not a problem with this setup
        return Check("ok", "version", __version__)
    if update.is_newer(release.version, __version__):
        return Check("WARN", "version", f"{release.version} is available, run `sb update`")
    return Check("ok", "version", f"{__version__} (latest)")


AGENTS_DIR = home_path("Library/LaunchAgents")


def _installed_plist() -> dict:
    """The installed LaunchAgent, or {} when there is none (or it cannot be read)."""
    try:
        return plistlib.loads((AGENTS_DIR / f"{launchd.LABEL}.plist").read_bytes())
    except (OSError, ValueError):
        return {}


def _installed_time() -> tuple[int, int] | None:
    """The (hour, minute) in the installed LaunchAgent, if there is one."""
    try:
        at = _installed_plist()["StartCalendarInterval"]
        return at["Hour"], at["Minute"]
    except KeyError:
        return None


def _job(cfg: Config) -> Check:
    try:
        loaded = launchd.is_loaded(os.getuid(), launchctl=launchd.run_launchctl)
    except OSError:
        return Check(
            "WARN",
            "nightly job",
            "the nightly job uses launchd, which only macOS has",
            "add the line that `sb schedule install` prints to cron",
        )
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
    command = " ".join(map(str, _installed_plist().get("ProgramArguments", [])))
    if "/Cellar/esbi-cli/" in command:  # `brew upgrade` deletes that folder: the job would stop
        return Check(
            "WARN",
            "nightly job",
            "points into a versioned Homebrew folder (Cellar) that the next `brew upgrade` removes",
            "sb schedule install",
        )
    prefix = Path(
        sys.prefix
    )  # a uv tool or pipx environment can be rebuilt elsewhere by an upgrade
    if update.install_method(prefix, Path(__file__).resolve().parent) in ("uv-tool", "pipx"):
        current = launchd.stable_prefix(prefix) / "bin" / "sb"
        if str(current) not in command:
            old = re.search(r"\S+/bin/sb\b", command)
            return Check(
                "WARN",
                "nightly job",
                f"runs {old[0] if old else 'another environment'}, not the {current} that is "
                "running now",
                "sb schedule install",
            )
    return Check("ok", "nightly job", f"installed and loaded, runs at {cfg.nightly_time}")


def _last_run(vault: Path) -> Check:
    every_run = RunLog(vault / ".esbi" / "runs.jsonl").runs()
    if every_run and every_run[-1].stopped_by == "llm_unavailable":  # the latest record, any kind
        return Check(
            "WARN",
            "last run",
            f"{every_run[-1].started:%Y-%m-%d %H:%M}: the model server was unreachable "
            "(nothing was lost; the sources stay queued)",
            f"start Ollama ({_start_ollama()}) or check the model line above, then run `sb run`",
        )
    runs = [r for r in every_run if r.trigger == "scheduled"]
    if not runs:
        return Check(
            "WARN",
            "last run",
            "no scheduled run yet",
            "the job does it after the nightly time; or try `sb run --if-due`",
        )
    last = runs[-1]
    text = f"{last.started:%Y-%m-%d %H:%M}: {last.ingested} ingested, {last.failed} failed"
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


_INSTALL_FIXES = {
    "brew": f"brew upgrade {update.BREW_FORMULA}",
    "uv-tool": "uv tool upgrade esbi-cli",
    "pipx": "pipx upgrade esbi-cli",
    "pip": "pip install -U esbi-cli",
}


def _install_fix() -> str:
    """What puts `sb` on the PATH, for the way this copy was installed: an editable install only
    for a source checkout, never the site-packages folder of an installed one."""
    method = update.install_method(Path(sys.prefix), Path(__file__).resolve().parent)
    if method == "editable":
        return f"uv tool install --editable {Path(__file__).resolve().parents[2]}"
    return _INSTALL_FIXES.get(method, "put the folder that holds `sb` on your PATH")


def run_checks(config_arg: Path | None) -> list[Check]:
    try:
        path = find_config(config_arg)
        cfg = load_config(path, always_notice=True)
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
        _version(cfg),
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
    checks += [*_network(cfg), _email(cfg), _job(cfg)]
    sb = shutil.which("sb")
    checks.append(
        Check("ok", "global install", sb)
        if sb
        else Check("WARN", "global install", "`sb` is not on your PATH", _install_fix())
    )
    return checks
