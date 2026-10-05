"""`sb init`: a new vault and a config file, without overwriting anything that already exists."""

import json
import re
import subprocess
from pathlib import Path

from esbi_cli import lang, ocr_models
from esbi_cli.gitops import STATE_IGNORE, GitError, commit_vault, has_git
from esbi_cli.hostos import keychain

TEMPLATES = Path(__file__).parent / "templates"
EXAMPLE_CONFIG = TEMPLATES / "config.example.toml"  # inside the package: an installed copy has it
FOLDERS = (
    "inbox",
    "raw",
    "attachments",
    *(
        f"wiki/{kind}"
        for kind in ("sources", "concepts", "entities", "syntheses", "review", "daily")
    ),
)


def _files(language: str) -> dict[str, str]:
    schema = (TEMPLATES / "SCHEMA.md").read_text(encoding="utf-8")
    return {
        "SCHEMA.md": schema.replace("{language}", lang.name(language)),
        "index.md": f"# {lang.t(language, 'index_title')}\n",
        "log.md": "# Log\n",
        ".gitignore": ".obsidian/workspace*.json\n.obsidian/cache\n.trash/\n.DS_Store\n"
        + "\n".join(STATE_IGNORE)
        + "\n",
    }


def init_vault(root: Path, language: str = lang.DEFAULT) -> list[str]:
    """Create what is missing; return what was created."""
    created = []
    for folder in FOLDERS:
        if not (root / folder).is_dir():
            (root / folder).mkdir(parents=True)
            created.append(f"{folder}/")
    for name, text in _files(language).items():
        if not (root / name).exists():
            (root / name).write_text(text, encoding="utf-8")
            created.append(name)
    if not (root / ".git").exists() and has_git():
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        created.append("git repository")
        try:  # a first commit, so that nothing (not even .gitignore) waits untracked for a run
            commit_vault(root, "init: vault")
        except GitError:
            pass  # history is optional: a commit that fails must not fail the setup
    return created


MODELS = {
    "local": "Everything stays on {machine}: the notes are written by a local model.",
    "subscription": (
        "The text of each source goes to Anthropic through your Claude subscription "
        "(the official `claude` tool, `claude auth login` once). Email is read only by the local model."
    ),
    "api": (
        "The text of each source goes to Anthropic through its API, billed per token: set "
        "ANTHROPIC_API_KEY in the environment. Email is read only by the local model."
    ),
}
RUNTIMES = ("ollama", "lmstudio")


def local_model(runtime: str, name: str | None) -> str:
    """`<provider>/<name>` of the local model: Ollama's default, or the LM Studio identifier."""
    return f"lmstudio/{name}" if runtime == "lmstudio" else f"ollama/{name or 'llama3.2:latest'}"


def llm_sections(model: str, runtime: str, name: str | None, base_url: str | None = None) -> str:
    """The [llm.*] sections for the chosen kind of model."""
    local = local_model(runtime, name)
    if model == "local":
        return (
            f'[llm.summarize]\nmodel = "{local}"\ntimeout_seconds = 300\n'
            + (f"base_url = {json.dumps(base_url)}\n" if base_url else "")
            + ("num_ctx = 8192\nmax_tokens = 1200\n" if runtime == "ollama" else "")
        )
    main = "claude-cli/default" if model == "subscription" else "anthropic/claude-sonnet-5-5"
    sections = [
        f'[llm.summarize]\nmodel = "{main}"\nfallback = "{local}"\ntimeout_seconds = 300\n',
        f'[llm.ask]\nmodel = "{main}"\nfallback = "{local}"\ntimeout_seconds = 600\n',
        f'[llm.private]\nmodel = "{local}"\n',  # email is read only by the local model
    ]
    if model == "subscription":
        sections.insert(
            1, f'[llm.synthesize]\nmodel = "{main}"\nfallback = "{local}"\ntimeout_seconds = 600\n'
        )
    return "\n".join(sections)


OCR_MODEL = ocr_models.QWEN.name  # the default for machines that cannot run the best one


def write_config(
    path: Path,
    vault: Path,
    model: str = "local",
    *,
    viewer: str = "obsidian",
    nightly: str | None = None,
    runtime: str = "ollama",
    local_name: str | None = None,
    ocr: bool | str = False,
    base_url: str | None = None,
    language: str = lang.DEFAULT,
) -> bool:
    """Write the example config with this vault and choices; False if a config is already there."""
    if path.exists():
        return False
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    text = re.sub(r'^vault = ".*"', f'vault = "{vault}"', text, count=1, flags=re.M)
    text = re.sub(
        r'^language = ".*"$',
        f'language = "{language}"\nviewer = "{viewer}"',
        text,
        count=1,
        flags=re.M,
    )
    if nightly:
        text = re.sub(
            r'^nightly_time = "[^"]*"', f'nightly_time = "{nightly}"', text, count=1, flags=re.M
        )
    llm = llm_sections(model, runtime, local_name, base_url)
    if ocr:  # a local vision model reads images and scanned PDFs: nothing leaves this machine
        llm += "\n" + ocr_block(OCR_MODEL if ocr is True else ocr)
    text = re.sub(
        r"^\[llm\.summarize\].*?(?=^# Optional|^\[bench\])",
        llm + "\n",
        text,
        count=1,
        flags=re.M | re.S,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def connect_remote(root: Path, url: str) -> bool:
    """Add `origin` as the backup remote; False if the vault already has one (left alone)."""
    if (
        subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=root, capture_output=True
        ).returncode
        == 0
    ):
        return False
    subprocess.run(["git", "remote", "add", "origin", url], cwd=root, check=True)
    return True


def set_email_block(path: Path, user: str, label: str = "esbi-cli") -> None:
    """Turn on the [email] section of a config file for this Gmail address and label, replacing the
    block if there is one and touching nothing else. The password is never written here."""
    block = (
        "[email]\n"
        "enabled = true\n"
        'imap_host = "imap.gmail.com"\n'
        f'mailbox = "{label}"\n'
        f'user = "{user}"\n'
        f"# The app password lives in the {keychain()} (service esbi-cli-imap), never in this file.\n"
    )
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\[email\]\n.*?(?=^\[|\Z)", text, re.S | re.M)
    if match:
        kept = [  # choices made by hand survive a re-run of the setup
            line for line in match.group().splitlines() if line.startswith("follow_links")
        ]
        block += "".join(line + "\n" for line in kept)
        text = text[: match.start()] + block + "\n" + text[match.end() :]
    else:
        text = text.rstrip("\n") + "\n\n" + block
    path.write_text(text, encoding="utf-8")


def ocr_block(model: str, enabled: bool = True) -> str:
    model = ocr_models.clean_name(model)  # it goes into a file: never anything but a model name
    return (
        f'[llm.ocr]\nmodel = "ollama/{model}"\nenabled = {str(enabled).lower()}\n'
        "timeout_seconds = 600\n"
    )


def set_ocr_block(path: Path, *, model: str | None = None, enabled: bool = True) -> bool:
    """Switch reading images on or off in a config file, and optionally choose the model, changing
    only those two lines of [llm.ocr] (a new section is added at the end when there is none).
    False when there was nothing to switch off."""
    model = ocr_models.clean_name(model) if model is not None else None
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\[llm\.ocr\]\n.*?(?=^\[|\Z)", text, re.S | re.M)
    if not match:
        if not enabled:
            return False
        block = ocr_block(model or OCR_MODEL)
        path.write_text(text.rstrip("\n") + "\n\n" + block, encoding="utf-8")
        return True
    section = match[0]
    for key, value in (
        ("model", f'"ollama/{model}"' if model else None),
        ("enabled", str(enabled).lower()),
    ):
        if value is None:
            continue
        line = f"{key} = {value}"
        section, n = re.subn(rf"^{key} = .*$", line, section, count=1, flags=re.M)
        if not n:  # the key is not there yet: right under the header
            section = section.replace("[llm.ocr]\n", f"[llm.ocr]\n{line}\n", 1)
    path.write_text(text[: match.start()] + section + text[match.end() :], encoding="utf-8")
    return True
