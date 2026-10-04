# What lives where

## Inside the vault

```
~/Documents/Obsidian/esbi/        (the vault; its own git repo when git is installed)
├── Home.md              your start page; the worker only edits the block between its two marker comments
├── index.md             catalog of every wiki page (rebuilt by the worker on every run: do not keep your own here)
├── log.md               append-only history: "## [date] ingest | Title"
├── SCHEMA.md            the conventions given to the model
├── inbox/               DROP ZONE: Web Clipper notes, PDFs and images waiting to be picked up
├── raw/                 originals, never edited
│   ├── inbox/           what arrived through inbox/ or by mail (kept as it came)
│   └── DATE-title-hash.md/.pdf/.png   the text snapshot of each source, with the PDF or image next to it
├── attachments/         figures copied out of PDFs and pictures, one folder per source
├── wiki/
│   ├── sources/         one note per source
│   ├── concepts/  entities/  syntheses/
│   ├── daily/           one index note per day
│   └── review/          things for you: contradiction notes, Lint.md
├── site/                only if you run `sb export` without --out: the exported website
└── .esbi/               worker state (git-ignored, except golden.jsonl)
```

### The state folder, `.esbi/`

Git-ignored (but for `golden.jsonl`, which is versioned with the vault), and none of it is in the notes. Delete it to start the worker's memory afresh; the notes are untouched.

| File | What it is | Disposable? |
|---|---|---|
| `queue.sqlite3` | The queue: every source, its state, attempts and last error | No: it is what remembers what was done |
| `index.sqlite3` | The page index: names, URLs, hashes, full text, and embeddings when `[llm.embed]` is set | Yes: rebuilt from the vault |
| `runs.jsonl` | One line per `sb run`: counts, tokens, why it stopped. Feeds the daily note and the nightly due check | Yes |
| `run.lock` | The lock that lets only one run work at a time (an `flock`: a crash cannot leave it stuck) | Yes |
| `logs/nightly.log` | Output of the scheduled job; trimmed by itself | Yes |
| `asks.jsonl` | One line per `sb ask`: question, pages retrieved and cited, tokens, seconds | Yes |
| `golden.jsonl` | **Yours.** The questions for `sb eval` | No: it is committed with the vault; without git, back it up |
| `bench/` | Reports saved by `sb bench` | Yes |
| `mail-failed.txt`, `mail-pdfs.txt` | Mail the worker could not read (reported once), and fingerprints of PDFs that came by mail (for the privacy rules) | Mostly |

## Page frontmatter

**Source note**: `type: source`, `title`, `url`, `kind` (`article` / `paper` / `email` / `video`), `status` (`processed` then `read`), `captured`, `processed`, `read` (the date you ticked it), `tags`, `summary` (one line, used in indexes), `raw` (path of the original's snapshot), `content_hash`, `format` (`2` = the rich note; `sb reingest` rebuilds notes without it).

**Concept / entity pages**: `type`, `title`, `aliases`, `tags`, `sources` (links), `updated`, `summary`; the body grows one `## From [[source]]` section (`## Desde` in Spanish) per source that mentions it.

**Synthesis pages** (from `sb ask --save`): `type: synthesis`, `title`, `question`, `sources`, `updated`, `summary`.

Obsidian resolves `[[links]]` by file name across folders, so the worker never gives a concept the same name as a source or another page.

## Outside the vault

| What | Where |
|---|---|
| The settings | `~/.config/esbi-cli/config.toml` (or wherever `--config` or `ESBI_CONFIG` points; `sb info` prints it) |
| The mailbox password | The macOS Keychain, service `esbi-cli-imap`, account = your Gmail address |
| The nightly job (macOS) | `~/Library/LaunchAgents/com.esbi-cli.nightly.plist`, label `com.esbi-cli.nightly` |
| The program | Homebrew's Cellar, or `uv`'s tool folder (`uv tool dir`) |
| The models | Ollama's own store (`ollama list`); LM Studio's library |

An uninstall touches none of the first two rows: see [Update and uninstall](../how-to/update-and-uninstall.md#uninstall).
