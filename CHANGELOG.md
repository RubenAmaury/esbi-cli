# Changelog

All notable changes are written here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/) (while the major version is 0, a minor version may change commands or the config format).

## [Unreleased]

### Added
- `--json` on `sb version`, `status`, `info`, `doctor`, `add`, `ask` and `run`, for editor plugins and scripts (contract version 1, reported by `sb version --json` as `contract`). Each command prints one JSON object on stdout; `sb run --json` prints JSON Lines (`started`, `source_started`, `step`, `source_done`, `source_failed`, `finished`), flushed line by line, with the human progress lines dropped. A failure prints `{"contract":1,"error":...,"code":...}` and exits 1, with no traceback; exit codes are the same as without `--json`.

## [0.2.1] - 2026-10-04

0.2.0 has a bug in its update check: do not use it, update to 0.2.1 (`brew upgrade rubenamaury/esbi-cli/esbi-cli`, or `uv tool upgrade esbi-cli`; `sb update` itself crashes in 0.2.0).

### Security
- Fetching a link (and the update check) no longer follows `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` or `NO_PROXY` from the environment. Behind a proxy the proxy resolves and connects, so the check that a link points at a public address no longer described where the request went, and a proxy inside the network could be made to reach internal hosts. If your network only has a proxy, set `[network] use_environment_proxy = true`; `sb doctor` then warns that the address checks are done by the proxy.

### Fixed
- The update notice now follows the config the command was run with: `sb status --config other.toml` honours `[update] check = false` in `other.toml`, not in the default config.
- `sb update` now says to run `sb schedule install` when a nightly job is installed, so the job is rewritten by the new version (it never touches launchd itself). `sb doctor` also warns when the job points at another `uv tool` or pipx environment than the one that is running.
- `sb bench --help` named its config section "bench section"; it now reads `[bench]`.
- Pressing Ctrl-C (or sending SIGTERM) during `sb run` left the source being read stuck as in progress, and the next run counted that as a failed attempt, so three interruptions parked a perfectly good source. Now the source goes back to the queue with no attempt counted, the run exits with 130 (Ctrl-C) or 143 (SIGTERM) and says `Interrupted: 1 item put back in the queue.`. A note is never cut in half: a signal that arrives while a note is being written waits until it is whole. `sb ingest` and `sb reingest` stop the same way (`sb reingest` no longer risks losing a note's read state if stopped at the wrong moment). An interrupted scheduled run does not count as tonight's nightly run.
- A chunk of a long source that the model could not read (invalid twice) used to be skipped; it is now read again in two halves first, and the warning names the chunk only when both halves fail too (or says only half was read).
- English leaking into a note written in another language: the check covered the abstract only. Now the executive summary, key points, concept descriptions, key ideas, open questions and each paragraph of the abstract are judged on their own, the retry names the offending fields and the warning lists them. A language without a stopword list is still skipped.
- Glossary trivia: duplicate terms (case, accents, punctuation, and acronyms in either letter order such as IA and AI), generic words ("data", "system") and definitions that say they have none ("not defined in the text") are dropped. Terms still have to appear in the source.
- Invented diagram edges: a relation whose end is neither in the source nor a concept, entity, term or alias of the note (translated or inflected is fine) is dropped; the run reports how many. The prompts now ask for relation ends as names (1-4 words), not sentences: on five real notes 32% of the ends were longer than six words (often a sentence cut at 40 characters) and now 6% are. Small models still rarely tie an end to a concept of the note, so the concept map is often left out when fewer than two relations survive.
- The detailed summary of a long source failed on its first try about one time in four with a small local model (llama3.2): the abstract, one string with no bound, never closed (paragraphs repeated until the token cap) and, once closed, the whole answer did not fit the cap. The digest now asks for the abstract as a list of 3-4 paragraphs and for 4-6 short key ideas, which bounds what the model's grammar can enforce; first-try failures on the same prompts went from 6 of 32 to 1 of 25. The retry with a shorter hint stays.
- Glossary terms come out of PDFs and Markdown clean (no `*`, `_` or spaces around them) and a one-letter term (a formula symbol) is dropped. The hint for key ideas no longer says "why it matters", which a small model copied into Spanish notes as "Matters porque".
- `sb version --check`, `sb update` and `sb doctor` crashed with a traceback, and any command run in a terminal printed one after its own output, because the update check called the download helper with an argument name that had been renamed. The check can no longer break a command, whatever goes wrong inside it.

### Changed
- `Digest` (the model's answer for the detailed summary) has `paragraphs` (a list) instead of `abstract` (a string); `Digest.abstract` is still available as the joined text. Adding a language to `lang.py` now also takes `generic_terms` and `disclaimers` (see the how-to "Add a language").

### Added
- **Image attachments in mail.** PNG, JPEG, WEBP and TIFF attachments are saved to `inbox/` next to the mail's note, so they follow the same road as any image you drop there: read with the local `[llm.ocr]` model when it is configured, listed by `sb scan` as not read (with the hint to enable OCR) when it is not. The bytes decide what a file is, not the declared type or the name; images under 200 px or a few KB (signatures, logos, tracking pixels), over 5 MB, or beyond 15 MB per mail are skipped. Like mail PDFs, they count as email for the privacy rules.
- **`[email].follow_links`** (off by default) and **`follow_links_max`** (3 per mail, 1 to 10): the http(s) links in a mail's text, minus tracking redirects, unsubscribe/preferences/view-in-browser links and pictures, are queued, never fetched while the mail is captured. The nightly run reads them as email: only by `[llm.private]`, the resulting note has `kind: email` and is hidden from cloud models like any email note. `sb email fetch` reports `N images saved` and `N links queued`.
- `sb email configure` no longer drops `follow_links` and `follow_links_max` when it rewrites the `[email]` section.
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
