import difflib
import os
import re
import sys
import tomllib
import types
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

from esbi_cli import lang, netguard
from esbi_cli.gitops import ignore_state

# Never a path relative to the current folder: a ./config.toml in a cloned repository could point the
# model, or the mailbox, at someone else's server.
DEFAULT_CONFIG_PATHS = (
    Path("~/.config/esbi-cli/config.toml").expanduser(),
    Path(__file__).resolve().parents[2] / "config.toml",  # next to an editable install: any folder
    Path("~/.config/secondbrain/config.toml").expanduser(),  # legacy: the name before esbi-cli
)


@dataclass
class LLMConfig:
    model: str  # "<provider>/<name>", provider in {ollama, openai, anthropic}
    base_url: str | None = None
    api_key_env: str | None = None
    num_ctx: int = 8192
    temperature: float = 0.2
    timeout_seconds: float = 300.0  # one answer; `timeout` is the deprecated name
    fallback: str | None = None  # "<provider>/<name>" used when this model is out of reach
    max_tokens: int | None = None  # caps the answer; stops a small model that loops on one input
    enabled: bool = True  # [llm.ocr] only: false keeps the model choice but reads no images


@dataclass
class EmailConfig:
    enabled: bool = False
    imap_host: str = "imap.gmail.com"
    mailbox: str = "esbi-cli"
    user: str | None = None
    follow_links: bool = False  # queue the links found in a mail; its pages are read as email
    follow_links_max: int = 3  # at most this many links per mail (1 to 10)


@dataclass
class BenchConfig:
    models: list[str] = field(default_factory=list)
    cases: int = 3
    prices: dict[str, float] = field(default_factory=dict)  # USD per million tokens


@dataclass
class UpdateConfig:
    check: bool = (
        True  # look for a newer release once a day (one anonymous HTTPS GET); see update.py
    )


@dataclass
class NetworkConfig:
    # False: the fetch guard ignores HTTP(S)_PROXY and friends, so its address check is the truth.
    # True: for a network that only has a proxy; the proxy then decides where requests go.
    use_environment_proxy: bool = False


@dataclass
class Config:
    vault: Path
    language: str = lang.DEFAULT  # what the notes are written in: see lang.py
    viewer: str = (
        "obsidian"  # "obsidian" opens notes with obsidian:// links; "none" just prints paths
    )
    legacy_vault: Path | None = None
    max_source_chars: int = 4000  # up to this length a source is read in one go
    chunk_chars: int = 8000  # longer sources are read in chunks of about this size
    max_chunks: int = 16  # ...at most this many (huge sources are sampled)
    ocr_max_pages: int = 10  # a scanned PDF is read (OCR) up to this many pages
    find_connections: bool = True  # relate each new source to pages already in the wiki
    rewrite_questions: bool = False  # `sb ask` first rewrites the question into search terms
    nightly_time: str = "03:00"  # HH:MM, 24 hours: when the nightly job runs
    max_sources_per_run: int = 20
    max_tokens_per_run: int | None = 300_000
    flag_contradictions: bool = (
        False  # small models flag tenuous ones; opt in with a stronger model
    )
    llm: dict[str, LLMConfig] = field(default_factory=dict)
    email: EmailConfig = field(default_factory=EmailConfig)
    bench: BenchConfig = field(default_factory=BenchConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)

    @property
    def nightly_at(self) -> tuple[int, int]:
        return parse_time(self.nightly_time)

    @property
    def ocr_on(self) -> bool:
        """Images and scanned PDFs are read: an [llm.ocr] section exists and is not switched off."""
        return "ocr" in self.llm and self.llm["ocr"].enabled

    def llm_for(self, task: str) -> LLMConfig:
        try:
            return self.llm[task]
        except KeyError:
            raise KeyError(f"No [llm.{task}] section in config") from None


def find_config(path: Path | None = None) -> Path:
    """The config file that applies: --config, $ESBI_CONFIG, then the default places. A file named
    on purpose that does not exist is an error; only the default places may fall through."""
    env = os.environ.get("ESBI_CONFIG") or os.environ.get("SECONDBRAIN_CONFIG")  # legacy name
    if explicit := path or (Path(env) if env else None):
        if not explicit.is_file():
            raise FileNotFoundError(f"config file not found: {explicit}")
        return explicit
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(c) for c in DEFAULT_CONFIG_PATHS)
    raise FileNotFoundError(f"No config.toml found (looked in: {searched})")


_loaded_path: Path | None = None  # the file load_config read for the command that is running


def wants_update_check() -> bool:
    """`[update].check` of the config the running command used (else the one that applies by
    default), read without validating anything else and without any side effect. On any trouble:
    True (the setting's default); the command that is running reports a bad config itself."""
    try:
        raw = tomllib.loads((_loaded_path or find_config()).read_text(encoding="utf-8"))
        return raw.get("update", {}).get("check", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def _adopt_old_state_folder(vault: Path) -> None:
    """legacy: before esbi-cli the vault's state folder was `.secondbrain`. Rename it once and keep
    git ignoring it."""
    old, new = vault / ".secondbrain", vault / ".esbi"
    if old.is_dir() and not new.exists():
        old.rename(new)
    if new.is_dir():
        ignore_state(vault)


def reset_loaded() -> None:
    """Forget what the previous command loaded: every invocation starts from the safe defaults."""
    global _loaded_path
    _loaded_path = None
    netguard.use_environment_proxy = False


def load_config(path: Path | None = None) -> Config:
    global _loaded_path
    found = find_config(path)
    cfg = _parse(tomllib.loads(found.read_text(encoding="utf-8")))
    _loaded_path = found
    _adopt_old_state_folder(cfg.vault)
    netguard.use_environment_proxy = cfg.network.use_environment_proxy
    return cfg


def parse_time(text: str) -> tuple[int, int]:
    """`HH:MM` (24 hours) as (hour, minute)."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text).strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f"[run].nightly_time must look like HH:MM (24 hours), got {text!r}")
    return int(match[1]), int(match[2])


# Which keys each section accepts. The [llm.*], [email], [bench], [update] and [network] ones come from their dataclass.
_TABLES = {
    "paths": ("vault", "legacy_vault"),
    "notes": ("language", "viewer"),
    "run": (
        "max_source_chars",
        "chunk_chars",
        "max_chunks",
        "ocr_max_pages",
        "find_connections",
        "rewrite_questions",
        "nightly_time",
        "max_sources_per_run",
        "max_tokens_per_run",
        "flag_contradictions",
    ),
}
_SECTIONS = ("llm", "email", "bench", "update", "network")
_LLM_TASKS = ("summarize", "synthesize", "private", "ocr", "ask", "embed")
_TYPE_NAMES = {
    int: "a whole number",
    float: "a number",
    str: "text",
    bool: "true or false",
    list: "a list",
    dict: "a table",
}


def _fits(value, tp) -> bool:
    if get_origin(tp) in (Union, types.UnionType):
        return any(_fits(value, arg) for arg in get_args(tp))
    if tp is type(None):
        return value is None
    if get_origin(tp) is list:
        return isinstance(value, list) and all(_fits(v, get_args(tp)[0]) for v in value)
    if get_origin(tp) is dict:
        return isinstance(value, dict) and all(_fits(v, get_args(tp)[1]) for v in value.values())
    if tp is float:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if tp is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str if tp is Path else tp)


def _expects(tp) -> str:
    tp = next((a for a in get_args(tp) if a is not type(None)), tp)  # `X | None` expects an X
    return _TYPE_NAMES.get(get_origin(tp) or tp, "a different kind of value")


def _check(name: str, table, hints: dict, required: tuple[str, ...] = ()) -> None:
    """Refuse what would otherwise surface as a Python traceback: a section that is not a table, a
    key we do not know (with the closest match), a missing key, or a value of the wrong type."""
    if not isinstance(table, dict):
        raise ValueError(f"[{name}] must be a table with keys, not a single value")
    for key, value in table.items():
        if key not in hints:
            close = difflib.get_close_matches(key, hints, n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            raise ValueError(
                f"[{name}] has an unknown key {key!r}{hint}. Valid keys: {', '.join(hints)}"
            )
        if not _fits(value, hints[key]):
            raise ValueError(f"[{name}].{key} must be {_expects(hints[key])}, got {value!r}")
    if missing := [k for k in required if k not in table]:
        raise ValueError(f"[{name}] needs {', '.join(missing)}")


def _dataclass_hints(cls) -> tuple[dict, tuple[str, ...]]:
    hints = get_type_hints(cls)
    required = tuple(
        f.name for f in fields(cls) if f.default is MISSING and f.default_factory is MISSING
    )
    return {f.name: hints[f.name] for f in fields(cls)}, required


# keys that early versions wrote into config.toml and that nothing ever read: accepted, ignored
_RETIRED = {"run": ("daily_cost_cap_usd",)}
_RETIRED_TASKS = (
    "link",
    "lint",
)  # [llm.link] and [llm.lint] were written for tasks that never existed


# `[llm.*]` keys renamed to carry their unit: the old name keeps working, with a notice
_RENAMED_LLM_KEYS = {"timeout": "timeout_seconds"}
_noticed: set[tuple[str, str]] = set()  # one notice per section and key in a process


def _accept_renamed_keys(raw: dict) -> None:
    """Rewrite old key names to the new ones (the new one wins if both are set) before checking."""
    for task, section in raw.get("llm", {}).items():
        if not isinstance(section, dict) or task not in (*_LLM_TASKS, *_RETIRED_TASKS):
            continue  # _validate names the problem
        for old, new in _RENAMED_LLM_KEYS.items():
            if old in section:
                value = section.pop(old)
                section.setdefault(new, value)
                if (task, old) not in _noticed:
                    _noticed.add((task, old))
                    print(f"notice: [llm.{task}] {old} is now {new}", file=sys.stderr)


def _validate(raw: dict) -> None:
    for name, table in raw.items():
        if name in _RETIRED and isinstance(table, dict):
            table = {k: v for k, v in table.items() if k not in _RETIRED[name]}
        if name not in (*_TABLES, *_SECTIONS):
            close = difflib.get_close_matches(name, [*_TABLES, *_SECTIONS], n=1)
            raise ValueError(
                f"unknown section [{name}]" + (f" (did you mean [{close[0]}]?)" if close else "")
            )
        if name in _TABLES:
            hints = get_type_hints(Config)
            _check(name, table, {k: hints.get(k, str) for k in _TABLES[name]})
    for task, section in raw.get("llm", {}).items():
        if not isinstance(section, dict):
            raise ValueError("[llm] holds one table per model task, like [llm.summarize]")
        if task not in _LLM_TASKS and task not in _RETIRED_TASKS:
            close = difflib.get_close_matches(task, _LLM_TASKS, n=1)
            raise ValueError(
                f"unknown section [llm.{task}]"
                + (
                    f" (did you mean [llm.{close[0]}]?)"
                    if close
                    else f"; valid: {', '.join(_LLM_TASKS)}"
                )
            )
        hints, required = _dataclass_hints(LLMConfig)
        if task != "ocr":
            hints = {
                k: v for k, v in hints.items() if k != "enabled"
            }  # only OCR can be switched off
        _check(f"llm.{task}", section, hints, required)
    for name, cls in (
        ("email", EmailConfig),
        ("bench", BenchConfig),
        ("update", UpdateConfig),
        ("network", NetworkConfig),
    ):
        _check(name, raw.get(name, {}), *_dataclass_hints(cls))


def _parse(raw: dict) -> Config:
    _accept_renamed_keys(raw)
    _validate(raw)
    paths = raw.get("paths", {})
    if "vault" not in paths:
        raise ValueError("config.toml needs [paths].vault")
    run = raw.get("run", {})
    llm = {name: LLMConfig(**section) for name, section in raw.get("llm", {}).items()}
    cfg = Config(
        vault=Path(paths["vault"]).expanduser(),
        language=raw.get("notes", {}).get("language", lang.DEFAULT),
        viewer=raw.get("notes", {}).get("viewer", "obsidian"),
        legacy_vault=Path(paths["legacy_vault"]).expanduser() if "legacy_vault" in paths else None,
        max_source_chars=run.get("max_source_chars", 4000),
        chunk_chars=run.get("chunk_chars", 8000),
        max_chunks=run.get("max_chunks", 16),
        ocr_max_pages=run.get("ocr_max_pages", 10),
        find_connections=run.get("find_connections", True),
        rewrite_questions=run.get("rewrite_questions", False),
        nightly_time=run.get("nightly_time", "03:00"),
        max_sources_per_run=run.get("max_sources_per_run", 20),
        max_tokens_per_run=run.get("max_tokens_per_run", 300_000),
        flag_contradictions=run.get("flag_contradictions", False),
        llm=llm,
        email=EmailConfig(**raw.get("email", {})),
        bench=BenchConfig(**raw.get("bench", {})),
        update=UpdateConfig(**raw.get("update", {})),
        network=NetworkConfig(**raw.get("network", {})),
    )
    if not 1 <= cfg.email.follow_links_max <= 10:
        raise ValueError(
            f"[email].follow_links_max must be between 1 and 10, got {cfg.email.follow_links_max}"
        )
    lang.get(cfg.language)  # an unsupported language is an error line, not a wrong note
    if cfg.viewer not in ("obsidian", "none"):
        raise ValueError(f'[notes].viewer must be "obsidian" or "none", got {cfg.viewer!r}')
    parse_time(
        cfg.nightly_time
    )  # refuse a bad time when the config is read, not when the job fires
    return cfg
