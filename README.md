# esbi-cli

[![CI](https://github.com/RubenAmaury/esbi-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/RubenAmaury/esbi-cli/actions/workflows/ci.yml)

**Save PDFs and links. Get a wiki of notes you can read instead of the originals.**

esbi-cli is a command-line worker (`sb`) that reads what you save (PDFs, web pages, email, clips) and writes a Markdown wiki: an executive summary, the key ideas, a glossary, verbatim quotes, a concept diagram, the figures, and links to the notes you already have. Every morning it builds an index note to start from. It works with local models (Ollama, LM Studio), with your Claude subscription, or with an API key. It follows Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern, and the model never touches your files: it only returns JSON that the program validates and then writes.

## What a note looks like

You save a link or a paper. A few minutes later there is a note like this (abridged, from a Wikipedia article, written by `llama3.2` on a laptop; the notes are in English unless you set `[notes].language = "es"`):

```markdown
## Executive summary
The Zettelkasten is a method of note-taking and knowledge management developed by Niklas Luhmann,
which involves creating a network of interconnected notes and ideas. It emphasizes the importance of
linking and connecting ideas, rather than simply collecting or storing them.

## Key ideas
- **The Zettelkasten system emphasizes the use of index cards to organize and connect ideas.** This
  approach allows users to create a network of interconnected notes, rather than a linear sequence of thoughts.

## Key terms
- **Zettelkasten**: A system of note-taking and personal knowledge management that consists of small
  items of information stored on paper slips or cards.

## Key quotes
> "Every one admits nowadays that it is advisable to collect materials on separate cards or slips of paper."

## Concepts
- [[Index card file]]

## Entities
- [[Niklas Luhmann]]
- [[Roland Barthes]]
```

Quotes are checked against the source word for word, glossary terms must appear in it, diagrams are drawn by code, and PDF figures are copied next to the note. Details: [How a note is made](https://rubenamaury.github.io/esbi-cli/docs/explanation/how-a-note-is-made/).

## Who it is for

People who save more than they read: papers, articles, newsletters, YouTube talks. You decide what to read from a good summary, and you can ask your own wiki questions (`sb ask`) and get answers that cite your notes. It runs on your machine, on macOS first (Linux works by running the same command from cron; it is less tested).

## Install

```bash
brew install rubenamaury/esbi-cli/esbi-cli          # macOS (Homebrew)
# or, with uv:
uv tool install git+https://github.com/RubenAmaury/esbi-cli
```

Then set it up. `sb init` is an installer: it asks what you use and every question is optional.

```bash
sb init        # vault folder, Obsidian or not, local model / Claude subscription / API, nightly job, backup
sb doctor      # checks the whole setup and says what to fix
```

A walk-through from install to a first note is in [Getting started](https://rubenamaury.github.io/esbi-cli/docs/tutorials/getting-started/); other ways to install (a wheel, a source checkout, Linux) are in [Install](https://rubenamaury.github.io/esbi-cli/docs/how-to/install/).

## First five minutes

```bash
sb add https://example.com/a-good-article     # a link
cp ~/Downloads/paper.pdf ~/Documents/Obsidian/esbi/inbox/    # or drop a PDF in inbox/
sb run                                        # reads, writes the notes (a few minutes per source)
sb today                                      # opens today's index note
```

In the index note, tick `- [x]` next to what you have read and run `sb index`. Ask a question with `sb ask "what is an agent harness?"`. [Getting started](https://rubenamaury.github.io/esbi-cli/docs/tutorials/getting-started/) shows every step with its output, and [A first week](https://rubenamaury.github.io/esbi-cli/docs/tutorials/first-week/) teaches the habit.

## What is optional

The basics are PDFs and links. Everything else you can skip, or add later:

| Optional | What it adds | How |
|---|---|---|
| Obsidian | A nice viewer. Any Markdown editor works, or `sb export` for a website | `sb init` asks; [Use it without Obsidian](https://rubenamaury.github.io/esbi-cli/docs/how-to/without-obsidian/) |
| The nightly job | Processes your queue by itself at a time you choose | `sb init --nightly 03:00`; [Run it every night](https://rubenamaury.github.io/esbi-cli/docs/how-to/nightly-job/) |
| Email capture (Gmail) | Forward an email or PDF to yourself and get a note | `sb setup email`; [Capture email](https://rubenamaury.github.io/esbi-cli/docs/how-to/email/) |
| Web Clipper (needs Obsidian) | Save pages, LinkedIn or Reddit posts, YouTube transcripts from your browser | `sb setup clipper`; [Web Clipper](https://rubenamaury.github.io/esbi-cli/docs/how-to/web-clipper/) |
| Claude subscription or API | Better notes than a small local model | `sb init --model subscription` or `api`; [Models](https://rubenamaury.github.io/esbi-cli/docs/how-to/models/) |
| Version history and backup (git) | If `git` is installed the vault is a repository: every ingested source is a commit you can review or undo. A backup is any git remote (GitHub, GitLab, a folder on a NAS), never required | `sb init --remote URL`; [Back up your vault](https://rubenamaury.github.io/esbi-cli/docs/how-to/backup/) |

## Privacy: what leaves your machine

| You choose | What is sent, and to whom |
|---|---|
| A local model (Ollama, LM Studio) | Nothing |
| Your Claude subscription (`claude-cli`) | The text of each source goes to Anthropic, through the official `claude` tool |
| An API key (OpenAI-compatible, Anthropic) | The text of each source goes to that provider |

With either cloud choice, **email is never sent**: it is read only by a local model (`[llm.private]`), and the cloud model is never shown email pages. The mail password is stored in the macOS Keychain, never in a file; the app only reads mail, it never deletes it; URLs are fetched only on public addresses. Details: [Safety and privacy](https://rubenamaury.github.io/esbi-cli/docs/explanation/safety-and-privacy/).

## How it works

```
 you save                         the worker (sb run)                          you read
 ────────                         ───────────────────                          ────────
 sb add / inbox/ PDFs   ┐
 Web Clipper clips      ├─► queue ─► extract ─► read in chunks ─► model writes a   ─► wiki/ notes, index.md,
 forwarded email        ┘   (SQLite)  (web, PDF)  (notes per chunk)   JSON edit plan       log.md, wiki/daily/  ◄── start here
```

`raw/` keeps the originals and is never edited; `wiki/` holds the notes the worker writes and you edit freely; `SCHEMA.md` holds the conventions the model is given. The vault is its own git repository: every ingested source is a commit, so any change can be reviewed or reverted. More: [How it works](https://rubenamaury.github.io/esbi-cli/docs/explanation/how-it-works/), [Internals](https://rubenamaury.github.io/esbi-cli/docs/explanation/internals/).

## Documentation

The same pages are published as a website: <https://rubenamaury.github.io/esbi-cli/> (documentation under `/docs/`).

| | |
|---|---|
| **Start** | [Documentation home](https://rubenamaury.github.io/esbi-cli/docs/) · [How do I...?](https://rubenamaury.github.io/esbi-cli/docs/how-to/) |
| **Learn** | [Getting started](https://rubenamaury.github.io/esbi-cli/docs/tutorials/getting-started/) · [A first week](https://rubenamaury.github.io/esbi-cli/docs/tutorials/first-week/) |
| **Do** | [Install](https://rubenamaury.github.io/esbi-cli/docs/how-to/install/) · [Models](https://rubenamaury.github.io/esbi-cli/docs/how-to/models/) · [Get sources in](https://rubenamaury.github.io/esbi-cli/docs/how-to/getting-sources-in/) · [Manage the queue](https://rubenamaury.github.io/esbi-cli/docs/how-to/manage-the-queue/) · [Read your notes](https://rubenamaury.github.io/esbi-cli/docs/how-to/read-your-notes/) · [Ask your wiki](https://rubenamaury.github.io/esbi-cli/docs/how-to/ask-your-wiki/) · [Check the wiki's health](https://rubenamaury.github.io/esbi-cli/docs/how-to/check-wiki-health/) · [Export a website](https://rubenamaury.github.io/esbi-cli/docs/how-to/export-a-website/) · [Email](https://rubenamaury.github.io/esbi-cli/docs/how-to/email/) · [Web Clipper](https://rubenamaury.github.io/esbi-cli/docs/how-to/web-clipper/) · [Nightly job](https://rubenamaury.github.io/esbi-cli/docs/how-to/nightly-job/) · [Back up and restore](https://rubenamaury.github.io/esbi-cli/docs/how-to/backup/) · [Move to a new Mac](https://rubenamaury.github.io/esbi-cli/docs/how-to/move-to-a-new-mac/) · [Update and uninstall](https://rubenamaury.github.io/esbi-cli/docs/how-to/update-and-uninstall/) · [Without Obsidian](https://rubenamaury.github.io/esbi-cli/docs/how-to/without-obsidian/) · [Offline](https://rubenamaury.github.io/esbi-cli/docs/how-to/use-offline/) · [Troubleshooting](https://rubenamaury.github.io/esbi-cli/docs/how-to/troubleshooting/) |
| **Look up** | [Commands](https://rubenamaury.github.io/esbi-cli/docs/reference/cli/) · [Configuration](https://rubenamaury.github.io/esbi-cli/docs/reference/configuration/) · [Vault layout](https://rubenamaury.github.io/esbi-cli/docs/reference/vault-layout/) · [The daily index](https://rubenamaury.github.io/esbi-cli/docs/reference/daily-index/) |
| **Understand** | [Concepts and glossary](https://rubenamaury.github.io/esbi-cli/docs/explanation/concepts/) · [FAQ](https://rubenamaury.github.io/esbi-cli/docs/explanation/faq/) · [How it works](https://rubenamaury.github.io/esbi-cli/docs/explanation/how-it-works/) · [How a note is made](https://rubenamaury.github.io/esbi-cli/docs/explanation/how-a-note-is-made/) · [Safety and privacy](https://rubenamaury.github.io/esbi-cli/docs/explanation/safety-and-privacy/) · [Why it is built this way](https://rubenamaury.github.io/esbi-cli/docs/explanation/internals/) · [Architecture](https://rubenamaury.github.io/esbi-cli/docs/explanation/architecture/) · [Retrieval and RAG](https://rubenamaury.github.io/esbi-cli/docs/explanation/rag-fit/) · [Storage](https://rubenamaury.github.io/esbi-cli/docs/explanation/storage-fit/) |

## Requirements

Python 3.12 or later (installed for you by `brew` or `uv`), macOS 13 or later (the PDF reader ships no build for older ones) or Linux, `git` (optional: version history and backup), and one way to run a model: [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai) locally, the [Claude Code](https://claude.com/code) `claude` tool signed in to a subscription, or an API key. `sb doctor` checks all of it.

## Status

Version 0.x: it works and is used daily, but commands and the config format can still change between minor versions; see the [changelog](CHANGELOG.md). Quality depends on the model: a small local model writes useful but unpolished notes; a stronger model writes noticeably better ones. Known limits are in [Known limits](https://rubenamaury.github.io/esbi-cli/docs/explanation/internals/#known-limits); open work is in the issue tracker.

## Contributing and security

Bug reports and ideas are welcome: [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately: [SECURITY.md](.github/SECURITY.md).

## License

[MIT](LICENSE). PDFs are read with [PDFium](https://pdfium.googlesource.com/pdfium/) through [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) (BSD-3-Clause or Apache-2.0); no dependency of esbi-cli is under the AGPL, and a test keeps it that way.
