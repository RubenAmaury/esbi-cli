"""`sb init`: a new vault and a config file, without overwriting anything that already exists."""

import json
import re
import subprocess
from pathlib import Path

from esbi_cli import lang
from esbi_cli.gitops import STATE_IGNORE, has_git

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
    return created


MODELS = {
    "local": "Everything stays on this Mac: the notes are written by a local model.",
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
            f'[llm.summarize]\nmodel = "{local}"\ntimeout = 300\n'
            + (f"base_url = {json.dumps(base_url)}\n" if base_url else "")
            + ("num_ctx = 8192\nmax_tokens = 1200\n" if runtime == "ollama" else "")
        )
    main = "claude-cli/default" if model == "subscription" else "anthropic/claude-sonnet-5-5"
    sections = [
        f'[llm.summarize]\nmodel = "{main}"\nfallback = "{local}"\ntimeout = 300\n',
        f'[llm.ask]\nmodel = "{main}"\nfallback = "{local}"\ntimeout = 600\n',
        f'[llm.private]\nmodel = "{local}"\n',  # email is read only by the local model
    ]
    if model == "subscription":
        sections.insert(
            1, f'[llm.synthesize]\nmodel = "{main}"\nfallback = "{local}"\ntimeout = 600\n'
        )
    return "\n".join(sections)


OCR_MODEL = "qwen3-vl:2b-instruct"
OCR_SECTION = f'[llm.ocr]\nmodel = "ollama/{OCR_MODEL}"\ntimeout = 600\n'


def write_config(
    path: Path,
    vault: Path,
    model: str = "local",
    *,
    viewer: str = "obsidian",
    nightly: str | None = None,
    runtime: str = "ollama",
    local_name: str | None = None,
    ocr: bool = False,
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
        llm += "\n" + OCR_SECTION
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
        "# The app password lives in the macOS Keychain (service esbi-cli-imap), never in this file.\n"
    )
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\[email\]\n.*?(?=^\[|\Z)", text, re.S | re.M)
    if match:
        text = text[: match.start()] + block + "\n" + text[match.end() :]
    else:
        text = text.rstrip("\n") + "\n\n" + block
    path.write_text(text, encoding="utf-8")
