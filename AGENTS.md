# esbi-cli

`sb`, a Python CLI that turns saved PDFs, links, mail, web clips and images into a Markdown/Obsidian wiki with a local or cloud LLM (the LLM Wiki pattern: `raw/` is immutable, `wiki/` is written by the worker, `SCHEMA.md` describes it). macOS is the only supported platform.

## Run and check

```bash
uv sync
uv run pytest            # parallel by default (pytest-xdist); add -n0 to run serially
uv run ruff check .      # --fix never removes an unused import here, so it is safe mid-TDD
uv run ruff format
uv run sb --help
```

CI (`.github/workflows/ci.yml`) runs ruff, the tests on Linux, and `scripts/smoke.sh` on the built wheel.

## Where things are

- Design rules, branch and release flow: [CONTRIBUTING.md](CONTRIBUTING.md). Read it before changing ingest, the LLM layer or the release flow.
- Rules a reviewer enforces: [CODING_STANDARDS.md](CODING_STANDARDS.md).
- Architecture and internals: the published docs (linked from CONTRIBUTING.md). Their sources are not in this repo.
- Shared test fakes and the autouse fixtures every test gets: `tests/conftest.py`.

## Gotchas

- **The repo-root `config.toml` is a developer's live config** (git-ignored, read by their nightly job). Never edit it. Experiments use a scratch vault: `sb init --vault <scratch>` and `--config <scratch>/config.toml`. Never touch a real vault except with read-only commands.
- **Tests run as on a Mac with plain output**, wherever they run: `tests/conftest.py` pins `sys.platform` to `darwin` and drops `FORCE_COLOR`. A test about another system sets `sys.platform` itself.
- **Tests fake at the seams only**: the LLM (`cli.make_llm`), the mail client, the Keychain, `launchctl` (`schedule.run_launchctl`). A default argument binds its runner when the function is defined (`launchctl=run_launchctl`), so pass it explicitly at the call site or a monkeypatch is bypassed.
- **`sb schedule install` loads a real launchd job.** An agent never runs it against the real `~/Library/LaunchAgents`; the user does.
- **Every URL fetch goes through `netguard.safe_get`** (public addresses only, every redirect checked, DNS pinned).
- **`LLMError` means the model is down**: `run_queue` stops the whole run. A failure of one source is an `ExtractError` (that source fails, the queue goes on).
- **`RunLock` order**: take the lock, then check whether a run is due, then build the LLM.
- **Generated files the user also edits**: the daily note is a view rebuilt from state (only the user's `- [x]` ticks are read back), and `Home.md` is rewritten only between `<!-- esbi:start -->` and `<!-- esbi:end -->`.
- **The queue lives in the user's vault**: a schema change needs a migration in `Queue.__init__` (`ALTER TABLE`), tested against an old-schema database.
- **Messages say `sb ...`**, never `uv run sb ...`: an installed copy has no `uv run`.
- **CHANGELOG.md merges with `merge=union`** (`.gitattributes`): after a merge or rebase, check that the lines under *Unreleased* are in a sensible order.
