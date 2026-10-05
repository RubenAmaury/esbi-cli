# Changelog

All notable changes are written here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/) (while the major version is 0, a minor version may change commands or the config format).

## [Unreleased]

### Security
- Fetching a link (and the update check) no longer follows `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` or `NO_PROXY` from the environment. Behind a proxy the proxy resolves and connects, so the check that a link points at a public address no longer described where the request went, and a proxy inside the network could be made to reach internal hosts. If your network only has a proxy, set `[network] use_environment_proxy = true`; `sb doctor` then warns that the address checks are done by the proxy.

### Fixed
- The update notice now follows the config the command was run with: `sb status --config other.toml` honours `[update] check = false` in `other.toml`, not in the default config.
- `sb update` now says to run `sb schedule install` when a nightly job is installed, so the job is rewritten by the new version (it never touches launchd itself). `sb doctor` also warns when the job points at another `uv tool` or pipx environment than the one that is running.
- `sb bench --help` named its config section "bench section"; it now reads `[bench]`.

## [0.2.1] - 2026-10-04

0.2.0 has a bug in its update check: do not use it, update to 0.2.1 (`brew upgrade rubenamaury/esbi-cli/esbi-cli`, or `uv tool upgrade esbi-cli`; `sb update` itself crashes in 0.2.0).

### Fixed
- `sb version --check`, `sb update` and `sb doctor` crashed with a traceback, and any command run in a terminal printed one after its own output, because the update check called the download helper with an argument name that had been renamed. The check can no longer break a command, whatever goes wrong inside it.

### Added
- A smoke test that installs the built wheel in a clean environment and runs the first commands a user runs (including one at a terminal, where the update notice runs). It runs in CI on every pull request and before every release, so a package that crashes cannot be released: the unit tests, which fake the network and the install, had all passed on 0.2.0.

## [0.2.0] - 2026-10-04

Updates you can see and run, a safer nightly job after a Homebrew upgrade, names that carry their unit, and a repository with code scanning, dependency review and protected branches.

### Added
- **Updates you can see and run.** `sb update` shows the command for the way esbi-cli was installed (Homebrew, `uv tool`, pipx, pip), asks `Run it now? [y/N]`, and runs it (`--yes` skips the question, `--dry-run` only prints it). A source checkout, an unknown install, or a `uv` tool pinned to a git tag or a wheel gets the steps to follow by hand. `sb version --check` prints the installed and the latest version.
- **An update notice.** Once a day esbi-cli asks the GitHub releases API for the latest version (one anonymous HTTPS request: no vault data, no identifier), and a command run in a terminal ends with one line on stderr when a newer one exists. It never appears after the nightly run, `schedule`, `update`, `setup`, `init`, `version` or `doctor`, in a pipe, or after a failed command. `sb doctor` has a `version` line. Turn it off with `[update] check = false` or `ESBI_NO_UPDATE_CHECK=1`. Nothing is installed by itself.
- A how-to page, "Update esbi-cli", with what each install method runs, what the check sends and how to turn it off.

### Changed
- The documentation sources are no longer in the repository. The site (https://rubenamaury.github.io/esbi-cli/docs/) is built on the maintainer's machine and only the built site is uploaded, to the `gh-pages` branch that GitHub Pages serves. README and CONTRIBUTING link to the site; report a wrong or missing page as an issue.
- `[llm.*].timeout` is now `timeout_seconds`, so the unit is in the name. The old `timeout` still works and prints `notice: [llm.<task>] timeout is now timeout_seconds` once per run; if both are set, `timeout_seconds` wins. `sb init` writes the new name.

### Fixed
- **The nightly job survives a Homebrew upgrade.** `sb schedule install` wrote the versioned Cellar folder (`.../Cellar/esbi-cli/0.1.0/libexec`) into the launchd job, and `brew upgrade` deletes that folder. It now writes the stable `.../opt/esbi-cli/libexec` path that Homebrew keeps pointing at the current version. `sb doctor` warns about a job installed the old way; run `sb schedule install` once to fix it.

## [0.1.0] - 2026-10-04

The first public release.

### Added
- **Capture**: PDFs, web links, Markdown clips (Obsidian Web Clipper), YouTube transcripts with timestamp links, email over IMAP (read-only, PDF attachments included), and, optionally, images and scanned PDFs read by a local vision model (OCR). A queue with retries, an inbox folder, `sb add`, `sb scan` and `sb run`.
- **Rich notes**: for each source, an executive summary, a detailed summary, key ideas, a glossary, verbatim quotes checked against the source, a concept diagram drawn by code, figures from PDFs, and connections to the notes you already have. Long sources are read in chunks. `sb reingest` rebuilds old notes from the saved originals.
- **The wiki**: sources, concepts, entities and syntheses as plain Markdown, an index, a log, a daily index note with read tracking by ticked checkboxes, lint, a review queue, and `sb export` for a read-only website.
- **Ask your wiki**: `sb ask` answers with citations to your notes; search by keywords, optionally fused with local embeddings (`[llm.embed]`); `sb eval` measures retrieval on your own questions.
- **Models**: local (Ollama, LM Studio), your Claude subscription through the official `claude` tool, or an API key (Anthropic, OpenAI-compatible), with a per-task choice, a fallback model, and token budgets. `sb bench` compares models on your own data.
- **Language**: the language of the notes is a setting (`en` and `es`; adding one is a data-only change). The CLI and the documentation are English.
- **Privacy**: email is read only by a model on your machine and is never shown to a model that sends text away. The mail password lives in the macOS Keychain. Fetching refuses non-public addresses and pins the connection to the address it checked.
- **Setup**: `sb init` creates the vault and the config and asks only about what is optional (Obsidian, model choice, nightly job, git backup, Gmail, Web Clipper); `sb doctor` checks the whole setup; a nightly launchd job on macOS (a cron line elsewhere).
- **Versioning of the vault**: with git installed, the vault is a repository and every ingested source is a commit; without git everything else works.
- **Documentation** (tutorial, how-to guides, a complete command and configuration reference, concepts, FAQ), a landing page, and a Homebrew tap.

[Unreleased]: https://github.com/RubenAmaury/esbi-cli/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/RubenAmaury/esbi-cli/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/RubenAmaury/esbi-cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RubenAmaury/esbi-cli/releases/tag/v0.1.0
