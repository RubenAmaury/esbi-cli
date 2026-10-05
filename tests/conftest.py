import json
import subprocess
from pathlib import Path

import pytest

from esbi_cli.config import Config
from esbi_cli.extract import ExtractedDoc
from esbi_cli.queue import Queue
from esbi_cli.vault import Page, Vault, fold


@pytest.fixture(autouse=True)
def never_check_for_updates(monkeypatch, tmp_path: Path):
    """No test reaches GitHub or writes the real cache: the automatic check is off, the cache folder
    is a temp one, and a test that wants a release must say which one (update.latest_release)."""
    from esbi_cli import update

    def no_network():
        raise AssertionError("a test asked GitHub for the latest release")

    monkeypatch.setenv("ESBI_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setattr(update, "latest_release", no_network)


@pytest.fixture(autouse=True)
def fresh_config_memory():
    """What a loaded config leaves behind (its path, the proxy setting) is per command invocation:
    no test inherits it from another."""
    from esbi_cli.config import reset_loaded

    reset_loaded()
    yield
    reset_loaded()


@pytest.fixture(autouse=True)
def no_real_ollama_for_ocr_setup(monkeypatch):
    """The OCR setup helpers never reach a real Ollama or read the real machine's memory: Ollama
    is down and the machine has 16 GiB, until a test says otherwise (see ocr_models._client)."""
    import httpx

    from esbi_cli import ocr_models

    def down(request):
        raise httpx.ConnectError("no Ollama in tests")

    monkeypatch.setattr(
        ocr_models, "_client", lambda: httpx.Client(transport=httpx.MockTransport(down))
    )
    monkeypatch.setattr(ocr_models, "machine_ram_gb", lambda: 16.0)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    for sub in ("sources", "concepts", "entities", "syntheses", "review", "daily"):
        (root / "wiki" / sub).mkdir(parents=True)
    (root / "raw").mkdir()
    (root / "inbox").mkdir()
    (root / "SCHEMA.md").write_text("# SCHEMA\nEscribe en español.\n", encoding="utf-8")
    (root / "index.md").write_text("# Índice\n", encoding="utf-8")
    (root / "log.md").write_text("# Log\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    return Vault(root, language="es")  # the fixtures' texts are Spanish; English has its own tests


@pytest.fixture
def queue(tmp_path: Path) -> Queue:
    return Queue(tmp_path / "queue.sqlite3")


@pytest.fixture
def cfg(vault: Vault) -> Config:
    # connections are an extra model call: the tests that want it switch it on explicitly
    return Config(vault=vault.root, language="es", max_source_chars=5000, find_connections=False)


@pytest.fixture
def doc() -> ExtractedDoc:
    text = (
        "Los agentes de IA usan un arnés de código para planificar y ejecutar herramientas. "
        "El arnés gestiona el contexto, la memoria y la verificación de resultados. "
        * 5
        + "Anthropic publica ejemplos de arneses de agentes."
    )
    return ExtractedDoc(title="Arnés de agentes", text=text, kind="article", url="https://x.test/a")


class FakeLLM:
    """Returns queued JSON payloads in order; records the prompts it was given."""

    def __init__(self, *payloads: dict | str):
        self.payloads = list(payloads)
        self.sends_text_out = False  # tests flip it to play a cloud model
        self.tokens_used = 0
        self.calls: list[dict] = []

    def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        self.calls.append({"system": system, "user": user, "schema": schema})
        self.tokens_used += 100
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload if isinstance(payload, str) else json.dumps(payload)


class FakeOCR:
    """Returns queued texts in order (one per image read); records the PNGs it was shown."""

    def __init__(self, *texts: str | Exception):
        self.texts = list(texts)
        self.sends_text_out = False
        self.tokens_used = 0
        self.images: list[bytes] = []

    def read_image(self, png: bytes) -> str:
        self.images.append(png)
        self.tokens_used += 50
        text = self.texts.pop(0)
        if isinstance(text, Exception):
            raise text
        return text


def make_plan(**overrides) -> dict:
    plan = {
        "title": "Arnés de agentes",
        "one_liner": "Cómo un arnés de código gestiona a un agente de IA.",
        "summary": "El artículo explica que un arnés de código organiza el contexto y las herramientas.",
        "key_points": ["Gestiona contexto", "Verifica resultados"],
        "tags": ["agentes", "#ia"],
        "concepts": [
            {
                "title": "Arnés de agente",
                "aliases": ["agent harness"],
                "description": "Capa de código que rodea al modelo y orquesta herramientas.",
            }
        ],
        "entities": [
            {
                "title": "Anthropic",
                "aliases": [],
                "description": "Organización citada como ejemplo.",
            }
        ],
        "related_pages": [],
        "contradictions": [],
    }
    plan.update(overrides)
    return plan


QUOTE = "The harness manages context, memory and the verification of results."


def english_plan(**overrides):
    plan = make_plan(
        title="Agent harness",
        one_liner="How a code harness manages an AI agent for the user.",
        summary="The article explains that a code harness organises the context and the tools.",
        abstract="This is the detailed summary of the article. " * 8,
        insights=[
            {
                "idea": "The harness manages the context of the agent.",
                "why": "Without it the agent forgets what it was doing.",
            }
        ],
        terms=[{"term": "harness", "definition": "The code layer that surrounds the model."}],
        quotes=[QUOTE],
        open_questions=["How is the harness tested for the user?"],
        key_points=["Manages context", "Verifies results"],
        concepts=[
            {
                "title": "Code harness",
                "aliases": [],
                "description": "A code layer that surrounds the model and runs the tools.",
            }
        ],
        entities=[],
    )
    plan.update(overrides)
    return plan


@pytest.fixture
def config_file(tmp_path: Path, vault: Vault) -> Path:
    """A config.toml pointing at the temp vault and a (not yet created) legacy vault."""
    path = tmp_path / "config.toml"
    path.write_text(
        f"""[paths]
vault = "{vault.root}"
legacy_vault = "{tmp_path / "old-notes"}"

[notes]
language = "es"

[run]
max_sources_per_run = 20

[llm.summarize]
model = "ollama/fake"

[email]
enabled = true
user = "me@example.test"
mailbox = "esbi-cli"
""",
        encoding="utf-8",
    )
    return path


def add_source(
    vault: Vault,
    title: str,
    *,
    processed: str = "2026-09-29",
    status: str = "processed",
    read: str | None = None,
    summary: str = "Resumen de prueba de la fuente.",
    body: str | None = None,
) -> Page:
    page = Page(
        vault.page_path("sources", title),
        {
            "type": "source",
            "title": title,
            "status": status,
            "processed": processed,
            "read": read,
            "summary": summary,
        },
        body if body is not None else f"# {title}",
    )
    vault.write_page(page)
    return page


def write_daily(vault: Vault, day: str, text: str) -> Path:
    path = vault.wiki / "daily" / f"{day}.md"
    path.write_text(text, encoding="utf-8")
    return path


class FakeLaunchctl:
    """Stands in for the launchctl binary; records calls, can be told to fail."""

    def __init__(self, loaded: bool = False, fail: str | None = None):
        self.calls: list[list[str]] = []
        self.loaded, self.fail = loaded, fail

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if args[0] == "bootstrap" and self.fail:
            return subprocess.CompletedProcess(args, 5, "", self.fail)
        if args[0] == "bootstrap":
            self.loaded = True
        if args[0] == "bootout":
            gone, self.loaded = not self.loaded, False
            return subprocess.CompletedProcess(args, 3 if gone else 0, "", "")
        return subprocess.CompletedProcess(args, 0 if self.loaded else 113, "", "")


class FakeMailClient:
    """Stands in for a mailbox: hands out (uid, raw) pairs and records what was marked seen."""

    def __init__(self, *mails: tuple[str, bytes], on_mark=None, accepts_seen=True, uidvalidity="1"):
        self.mails = list(mails)
        self.seen: list[str] = []
        self.on_mark = on_mark
        self.accepts_seen, self.uidvalidity = accepts_seen, uidvalidity
        self.asked_after: list[int | None] = []

    def recent(self, days: int = 14, after_uid: int | None = None) -> list[tuple[str, bytes]]:
        self.asked_after.append(after_uid)
        return list(self.mails)  # like IMAP SINCE: seen or not, the worker dedupes by Message-ID

    def close(self) -> None:
        pass

    def mark_seen(self, uid: str) -> bool:
        if self.on_mark:
            self.on_mark(uid)
        self.seen.append(uid)
        return self.accepts_seen


class FakeKeyring:
    """An in-memory Keychain."""

    def __init__(self, store=None):
        self.store = store or {}

    def get_password(self, service, user):
        return self.store.get((service, user))

    def set_password(self, service, user, password):
        self.store[(service, user)] = password


@pytest.fixture(autouse=True)
def isolated_keychain(monkeypatch):
    """Tests must never read or write the real macOS Keychain (nor depend on one existing)."""
    from esbi_cli.mail import credentials

    monkeypatch.setattr(credentials, "keyring", FakeKeyring())


class FakeEmbedder:
    """Deterministic vectors, one axis per group of words that mean the same thing, so a question
    and a note can share a meaning without sharing a word. Records every text it was given."""

    GROUPS = (("coche", "auto", "car"), ("gato", "felino", "cat"), ("pan", "bread", "hornear"))

    def __init__(self, sends_text_out: bool = False, fail: Exception | None = None):
        self.sends_text_out, self.fail = sends_text_out, fail
        self.identity = "fake/embed"
        self.seen: list[str] = []  # page texts
        self.queries: list[str] = []  # question texts

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        if self.fail:
            raise self.fail
        (self.queries if query else self.seen).extend(texts)
        folded = [fold(t) for t in texts]
        return [[float(sum(w in t for w in g)) for g in self.GROUPS] + [0.01] for t in folded]
