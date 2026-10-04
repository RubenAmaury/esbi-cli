# Architecture

esbi-cli is a **modular monolith** (one Python package, one process) organised as **ports and adapters** (hexagonal): the logic that decides what a note says sits in the middle, and everything that touches the outside world (a model, the network, a mailbox, the Keychain, launchd, the disk) sits behind a small seam that tests replace with a fake. This page says what that means in this code, and why; for the data flow and the file layout see [Internals](internals.md).

## The one principle that shapes everything

**The model never touches files and never needs tool calling.** The worker retrieves candidate pages, asks the model for a JSON edit plan, validates it against a schema, checks what it claims against the source, and only then writes. So the model is an adapter that turns text into validated data, and nothing else. That is what lets small local models work: they only have to produce JSON, not drive tools.

## Core, ports, adapters

| | What it is | Where |
|---|---|---|
| **Core** | Ingest (read, plan, apply), the retrieval and ask logic, the queue and run loop, the daily index, lint, privacy rules | `ingest/`, `ask/`, `run.py`, `queue.py`, `report/`, `lint/`, `privacy.py`, `vault.py`, `index.py` |
| **Ports** | The few things the core needs from outside, written as a small protocol or as a callable passed in | `LLM` (`complete_json`, `tokens_used`, `sends_text_out`), `MailClient`, the `extractor` callable, `ingest_fn` in `run_queue`, the `launchctl` runner, the DNS `resolver`, the Keychain `backend` |
| **Adapters** | The real implementations | `llm/adapter.py` (Ollama, LM Studio, OpenAI-compatible, Anthropic, the `claude` tool, embeddings, OCR), `mail/imap.py`, `extract/` (web, PDF, image, clip), `netguard.py`, `mail/credentials.py` (Keychain), `schedule.py` (launchd), `gitops.py` |

The **dependency rule**: the core depends on the ports (today the `LLM` protocol and its errors live in `llm/adapter.py`, next to the adapters) and never builds or imports a concrete provider. The CLI (`cli.py`) is the composition root that builds the adapters from the config (`make_llm`, `make_embedder`, `make_ocr`, `make_mail_client`) and hands them in. One known leak: the ingest pipeline asks `mail/fetch.py` whether a PDF came from email (`is_mail_pdf`), because the privacy rules need that fact. The vault is the one place the core touches the disk directly, because the vault is the product: plain Markdown files you own.

The ports are plain Python protocols and injected callables, not abstract base classes: nothing in this project needs a class hierarchy to express "a thing that returns JSON for a prompt".

## Why every external effect is behind a seam

Because tests never touch the network, a real model, the Keychain or launchd. They fake at the seams and nowhere else: a `FakeLLM` that returns queued JSON, a fake mail client, a fake `launchctl`, a resolver that returns chosen addresses, a fake Keychain backend. A new adapter or a new effect gets its seam first and its fake second; code that reaches the outside world without a seam cannot be tested and does not get merged.

## Patterns that earn their place

- **Adapter**: one per model provider and per source type, chosen by a prefix in the config (`ollama/…`, `claude-cli/…`).
- **Facade**: `Vault` hides the layout of the folders and the page index behind a few methods.
- **Repository**: `Queue` (SQLite) is the only owner of the work queue state.
- **Composition root**: `cli.py` wires the parts; no module builds its own collaborators.

Patterns are not added for their own sake: a layer or an interface that has one implementation and no seam to fake is not worth having.

## Rules the design holds to

- **KISS and YAGNI**: the smallest change that works; a setting needs a reason to exist.
- **Separation of concerns**: extracting text, planning, applying and reporting are separate steps with separate tests.
- **DRY, without forcing it**: one source of truth for a fact (for example the language labels live in `lang.py`; the privacy decision lives in `privacy.py`).
- **Safe by default**: email never reaches a model that sends text away; fetching goes through `netguard.safe_get` only; secrets live in the Keychain.

## Gotchas for developers

- **iCloud and `.venv`.** In an iCloud-synced folder (`~/Documents`), macOS flags files inside dot-folders as hidden and Python 3.13 then skips hidden `.pth` files, so `import esbi_cli` fails. Keep the environment outside, with `UV_PROJECT_ENVIRONMENT`.
- **One writer at a time.** `RunLock` is an `flock`, so a crashed run can never leave a stuck lock. The order in a run is: lock, then the "is it due" check, then build the model.
- **One way to fetch.** All URL fetching goes through `netguard.safe_get` (public addresses only, every redirect hop checked, the connection pinned to the address that was checked, size and time capped). Do not call `httpx` directly.
- **The nightly time is in the plist.** The launchd agent is static: changing `[run].nightly_time` needs `sb schedule install` again (`sb doctor` warns on a mismatch). Launchd agents cannot read `~/Documents` until macOS privacy allows that binary, which only the user can grant.
- **The daily note is a view.** It is regenerated from state (source notes and the queue); the only input channel is the user's ticked checkboxes, read before each regeneration. Never make the worker depend on text it wrote earlier in that note. `Home.md` is partly the user's: only the block between the `esbi` markers is rewritten.
- **State lives in the vault.** `.esbi/` holds the queue, the page index and logs. Anything that changes the queue table needs a migration (`Queue.__init__` migrates old databases), because the real database lives in users' vaults.
- **Injected defaults bind at definition time.** A function that takes an injectable runner as a default argument (`launchctl=run_launchctl`) must be given it explicitly at the call site, or a test's patch is silently bypassed and the test talks to the real system.
- **Heading names are data.** Note headings come from the language catalogue (`lang.py`), and readers recognise the headings of every catalogued language. Do not compare against a hard-coded heading.
