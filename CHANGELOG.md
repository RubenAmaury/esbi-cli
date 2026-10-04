# Changelog

All notable changes are written here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/) (while the major version is 0, a minor version may change commands or the config format).

## [Unreleased]

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

[Unreleased]: https://github.com/RubenAmaury/esbi-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/RubenAmaury/esbi-cli/releases/tag/v0.1.0
