# Command reference

Every command of `sb`, with every option, its default, what it prints and how it exits. `sb --help` and `sb <command> --help` print the same list; this page adds what the help text has no room for. For a task ("how do I add a PDF?") start from [How do I...?](../how-to/index.md).

Examples show the default vault, `~/Documents/Obsidian/esbi`. Your paths will differ.

## Conventions

- **`--config PATH`.** Every command that reads the config accepts it. When it is left out, the file is found as described in [Configuration](configuration.md#where-the-config-file-is). `sb version`, `sb update`, `sb schedule status`, `sb schedule uninstall` and `sb init` do not read a config (`sb init` writes one: `--config-file`). A `--config` path that does not exist is an error (`error: config file not found: PATH`), not a reason to use another file.
- **Exit codes.** `0` is success. `1` is an error the command already explained on the screen (a missing config, a bad argument, the model is down, a `FAIL` line in `sb doctor`). `2` is a usage mistake caught by the command-line parser (an unknown command or option); it prints the usage and a hint.
- **Quote what the shell would read.** A URL with `?` or `&` must be in quotes, or `zsh` answers `no matches found` before `sb` starts: `sb add "https://example.com/post?id=7"`.
- **Shell completion.** `sb --install-completion` installs it for the current shell, `sb --show-completion` prints the script to copy.

## Commands at a glance

| Command | What it does |
|---|---|
| [`sb`](#sb-menu) | A numbered menu of everyday actions |
| [`sb init`](#sb-init) | First-time setup: the vault, a config file, the optional pieces |
| [`sb doctor`](#sb-doctor) | Check the whole setup and say what to fix |
| [`sb info`](#sb-info) | Print where the config and the vault are, as `key=value` lines |
| [`sb version`](#sb-version) | Print the installed version; `--check` looks for a newer one |
| [`sb update`](#sb-update) | Update esbi-cli to the latest release (asks first) |
| [`sb add`](#sb-add) | Queue links or files for the next run |
| [`sb scan`](#sb-scan) | Queue what is in `inbox/` |
| [`sb status`](#sb-status) | Queue counts and sources that failed |
| [`sb retry`](#sb-retry) | Put failed sources back in the queue |
| [`sb drop`](#sb-drop) | Remove a source from the queue |
| [`sb run`](#sb-run) | The main job: mail, inbox, queue, lint, index |
| [`sb ingest`](#sb-ingest) | Ingest one source right now |
| [`sb reingest`](#sb-reingest) | Rebuild notes from the saved originals |
| [`sb import-legacy`](#sb-import-legacy) | One-time import of an older folder of links and PDFs |
| [`sb today`](#sb-today) | Open (or print the path of) today's daily note |
| [`sb index`](#sb-index) | Register read ticks, rebuild the daily index |
| [`sb lint`](#sb-lint) | Check the wiki's health |
| [`sb ask`](#sb-ask) | Answer a question from the wiki |
| [`sb eval`](#sb-eval) | Score retrieval on your own questions |
| [`sb bench`](#sb-bench) | Compare models on your own material |
| [`sb export`](#sb-export) | Write a read-only HTML copy of the wiki |
| [`sb setup email`](#sb-setup-email), [`sb setup clipper`](#sb-setup-clipper) | Guided setups for Gmail capture and the Web Clipper |
| [`sb email fetch`](#sb-email-fetch), [`configure`](#sb-email-configure), [`set-password`](#sb-email-set-password) | Mail capture |
| [`sb schedule install`](#sb-schedule-install), [`status`](#sb-schedule-status), [`uninstall`](#sb-schedule-uninstall) | The nightly job (macOS launchd) |

## sb (menu)

```bash
sb
```

With no command, a numbered menu. Each choice runs the real command, asking for what it needs, prints its output and returns to the menu. A mistake or a failing command never closes it.

```
esbi-cli
  1. Queue status
  2. Run now (ingest what is queued)
  3. Ask the wiki a question
  4. Add links or files to the queue
  5. Open today's note in Obsidian
  6. Check the wiki's health (lint)
  7. Check my setup (doctor)
Choose (q to quit) [q]: 1
queued: 1
processing: 0
done: 1
failed: 0
```

Anything else than a number from 1 to 7 or `q` prints `Not an option.` The menu has no `--config`: it uses the usual search (set `ESBI_CONFIG` to point it elsewhere).

## sb init

```bash
sb init [--vault PATH] [--config-file PATH] [--model local|subscription|api]
        [--runtime ollama|lmstudio] [--local-model NAME] [--base-url URL]
        [--language en|es] [--obsidian | --no-obsidian] [--nightly HH:MM|none] [--remote URL]
        [--ocr | --no-ocr]
```

First-time setup. It creates the vault if it is missing, writes a config file and says what to do next. It only creates what is missing: running it again changes nothing that exists and never overwrites a config.

At a keyboard it is an installer that asks one question per setting; with no keyboard (a script, a pipe) it asks nothing and uses the flag, or the default. The walk-through, with what each answer changes, is in [Getting started](../tutorials/getting-started.md#step-4-run-sb-init).

| Option | Default | Meaning |
|---|---|---|
| `--vault PATH` | `~/Documents/Obsidian/esbi` | Where the vault lives. Created if missing |
| `--config-file PATH` | `~/.config/esbi-cli/config.toml` | Where the config is written. An existing file is left alone |
| `--model` | `local` (no keyboard) | `local`: a model on this machine, nothing leaves it. `subscription`: your Claude subscription through the official `claude` tool, with a local fallback. `api`: Anthropic's API, billed per token (set `ANTHROPIC_API_KEY`). The last two keep email on the local model |
| `--runtime` | `ollama` | Which local runtime: `ollama` or `lmstudio`. Also the failsafe for `subscription` and `api` |
| `--local-model NAME` | `llama3.2:latest` for Ollama | The local model's name. Required for `lmstudio` (see `lms ls`) |
| `--base-url URL` | this machine | Only with `--model local`: the address of an Ollama or LM Studio server that is not on this Mac. The notes' text then goes to that host, so `sb init` warns and `sb doctor` keeps warning |
| `--language` | `en` (no keyboard) | The language the notes are written in, `en` or `es`: written as `[notes].language`, and used for the vault's `SCHEMA.md` and `index.md`. The command line itself is always English. See [Language of the notes](configuration.md#language-of-the-notes) |
| `--obsidian` / `--no-obsidian` | `--obsidian` (no keyboard), no (asked) | Writes `viewer = "obsidian"` or `viewer = "none"` in `[notes]` |
| `--nightly HH:MM` or `none` | none | Run every night at that time: installs the launchd job on macOS, prints a cron line elsewhere. Only when the config is new: an existing config is left alone, and so is the job |
| `--remote URL` | none | Connects the vault to a git remote for backup (an existing remote is never replaced). Needs git |
| `--ocr` / `--no-ocr` | `--no-ocr` | Also writes an `[llm.ocr]` section so images and scanned PDFs are read. Needs `--runtime ollama` |

Errors it reports and exits 1 on: an unknown `--model`, `--runtime` or `--language`, `--runtime lmstudio` without `--local-model`, `--ocr` with LM Studio, `--base-url` with a cloud model or without a host, a `--nightly` that is not `HH:MM`.

```bash
sb init --vault ~/Documents/Obsidian/esbi --model local --no-obsidian
```

```
Vault ~/Documents/Obsidian/esbi: inbox/, raw/, attachments/, wiki/sources/, wiki/concepts/, wiki/entities/, wiki/syntheses/, wiki/review/, wiki/daily/, SCHEMA.md, index.md, log.md, .gitignore, git repository
Config ~/.config/esbi-cli/config.toml: written
Model: local. Everything stays on this Mac: the notes are written by a local model.

Next: ollama pull llama3.2, then sb doctor. Add a link with `sb add URL` or drop a PDF in the vault's inbox/ folder.
```

Without git installed the vault is created without history and the message `History: git is not installed, so the vault has no version history...` appears. It does not install Ollama or pull a model.

## sb doctor

```bash
sb doctor [--config PATH]
```

Checks the whole setup and prints one line per check, with the fix under anything that is not fine. `ok` is fine, `WARN` is an inconvenience, `FAIL` is broken. **Exit code 1 only when a line is `FAIL`.**

```
  ok   config: ~/.config/esbi-cli/config.toml
  ok   version: 0.1.0 (latest)
  ok   vault: ~/Documents/Obsidian/esbi
  ok   obsidian: not used ([notes].viewer = "none")
  ok   queue: empty
  WARN last run: no scheduled run yet
         fix: the job does it after the nightly time; or try `sb run --if-due`
  ok   model summarize: ollama/llama3.2:latest is installed
  ok   ocr: off (optional): add [llm.ocr] to read images and scanned PDFs (`sb init --ocr`, docs/reference/configuration.md)
  ok   email privacy: all models are local
  ok   email: off (optional)
  WARN nightly job: not installed
         fix: sb schedule install
  ok   global install: /opt/homebrew/bin/sb
```

| Check | Looks at |
|---|---|
| `config` | Which `config.toml` applies, and that it is valid: a misspelled key, an unknown section or a value of the wrong type is a `FAIL` naming the setting |
| `version` | The installed version, and a `WARN` (`0.2.0 is available, run `sb update``) when a newer release is known. It reads the once-a-day cache and asks GitHub only when that is stale; if GitHub cannot be reached the line is just the version, and with `[update].check = false` it says `(update check is off)` |
| `vault` | The folder has `SCHEMA.md` and `wiki/` |
| `vault history` | Whether the vault is a git repository (a warning only when git is installed but the vault is not a repository) |
| `obsidian` | The folder was opened once as a vault in Obsidian (`.obsidian` exists); with `viewer = "none"` it just says `not used` |
| `queue` | Queue counts; warns when sources failed for good |
| `last run` | The last scheduled run, and whether it reached the model |
| `model <task>` | For each of `summarize`, `synthesize`, `ask`, `private`, `embed` that is set (and its fallback): Ollama is reachable and the model installed, LM Studio serves the model, `claude` is installed and logged in, or the API key is in the environment |
| `ocr`, `model ocr` | Images and scanned PDFs are off (optional), or `[llm.ocr]` is not a model on this machine (FAIL), or the vision model is installed |
| `email privacy` | Email is read only by a local model; warns when a cloud model is set with no `[llm.private]`; fails when `[llm.private]` sends text away |
| `server <task>` | Warns when an Ollama or LM Studio model is served from another machine |
| `email` | Only when enabled: the app password is in the Keychain |
| `nightly job` | The launchd job is installed, loaded and set for the time in the config, and does not point into a versioned Homebrew folder (`Cellar`) that `brew upgrade` deletes (fix: `sb schedule install`) |
| `global install` | `sb` is on your `PATH` |

Every message and its fix are listed by symptom in [Troubleshooting](../how-to/troubleshooting.md).

## sb info

```bash
sb info [--config PATH]
```

Prints where things are, as `key=value` lines. The setup wizards read it; it is also the quickest answer to "which config is it using?".

```
config=~/.config/esbi-cli/config.toml
vault=~/Documents/Obsidian/esbi
viewer=none
language=en
email=disabled
```

## sb version

```bash
sb version [--check]
```

Prints the installed version, for example `0.1.0`. It reads the package metadata, so it is the version that is installed, not the one in a checkout. Without options it is offline and instant.

`--check` also asks GitHub for the latest release (one anonymous HTTPS request, ignoring the once-a-day cache) and prints one more line: `You are up to date.`, or the new version and `Update with: sb update`. If GitHub cannot be reached it says so and still exits `0`.

## sb update

```bash
sb update [--yes] [--dry-run]
```

Updates esbi-cli to the latest release. It asks GitHub for it (ignoring the once-a-day cache), prints the installed version, the latest version and how esbi-cli was installed (`brew`, `uv-tool`, `pipx`, `pip`, `editable` or `unknown`), then the exact command it will run and `Run it now? [y/N]`. Nothing is installed without that yes.

| Option | Meaning |
|---|---|
| `--yes`, `-y` | Do not ask; run the command |
| `--dry-run` | Only print the command; run nothing |

Without a terminal and without `--yes` it refuses (exit `1`) and runs nothing. The command is run without a shell and its output is shown as it comes. On success it prints ``Updated. Run `sb version` to confirm.``; if the command fails it exits with that command's code. When there is no command to run (a source checkout, an unknown install, or a `uv` tool pinned to a git ref or a wheel) it prints what to do by hand. When you are already current it says so. See [Update esbi-cli](../how-to/update.md).

## sb add

```bash
sb add TARGET... [--config PATH]
```

Queues one or several sources for the next `sb run`. **Nothing is fetched now.** A target is an `http(s)` URL, or the path to an existing `.pdf` or `.md` file, or an image (`.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`) when `[llm.ocr]` is set; without it the error says how to turn it on.

If any target is invalid nothing is queued and the bad ones are listed (exit 1). Tracking parameters, letter case and a trailing slash are ignored. A link already in the queue is counted as `already known`; a link already in the wiki is skipped and the note that has it is named. The rules for every kind of duplicate are in [If a source already exists](../how-to/getting-sources-in.md#if-a-source-already-exists).

```bash
sb add https://en.wikipedia.org/wiki/Zettelkasten
```

```
Queued 1 (0 already known). `sb run` processes them.
```

```bash
sb add notaurl
```

```
error: not an http(s) URL or an existing .pdf/.md file:
  notaurl
```

## sb scan

```bash
sb scan [--config PATH]
```

Queues what is waiting in the vault's `inbox/`: `.md` clips and `.pdf` files, and images when `[llm.ocr]` is set. Each file is moved to `raw/inbox/`, its permanent home, and queued from there. `sb run` does this for you; run `sb scan` by itself to see the queue before a run.

- A byte-identical copy of a file already in `raw/inbox/` (under any name) is a duplicate: it is removed from `inbox/`, counted and not queued.
- A different file with the same name is kept under a new name (`paper (2).pdf`). Nothing in `raw/` is ever overwritten.
- Hidden files and folders are skipped.
- Any other file that cannot be read stays where it is and is listed: `Not read, esbi-cli cannot read these files in inbox/: ...`, with the way to turn OCR on when an image is among them.

```
Queued 1 sources from the inbox.
```

## sb status

```bash
sb status [--config PATH]
```

Prints the number of sources `queued`, `processing`, `done` and `failed`, then one line per source that failed for good with its last error. A source still being retried (it failed once or twice) counts as `queued`; its last error is in the daily note under **To review**.

```
queued: 2
processing: 0
done: 0
failed: 1
  failed: https://example.com/ (ExtractError: No readable article content found at https://example.com/)
```

## sb retry

```bash
sb retry [TARGET] [--config PATH]
```

Puts sources that failed three times (parked as `failed`) back in the queue with a fresh attempt count, so the next `sb run` tries them again. Without `TARGET` it requeues every parked source; with one (a URL or path as `sb status` shows it; tracking parameters are ignored) only that one.

```
Requeued 1 source.
```

When nothing is parked it prints `Nothing to retry.` and exits 0.

## sb drop

```bash
sb drop TARGET [--config PATH]
```

Removes a source from the queue whatever its state (queued, retrying, failed or done). The original file, if there is one, is not touched, and a note already written stays. You can add the source again later. If `TARGET` is not in the queue: `error: <target> is not in the queue`, exit 1.

```
Dropped https://example.com/
```

## sb run

```bash
sb run [--config PATH] [--limit N] [--if-due]
```

The whole pipeline, in this order:

1. Fetch mail from the mailbox (only if `[email].enabled`; a mail problem is a warning, never fatal).
2. Scan `inbox/` and queue what is there.
3. Put back in the queue anything a crashed run had claimed.
4. Ingest queued sources one by one; every success is a git commit in the vault.
5. Record the run.
6. Lint the wiki.
7. Register your read ticks, rebuild the daily index and `Home.md`, push the vault to its remote if it has one.

| Option | Default | Meaning |
|---|---|---|
| `--limit N` | `[run].max_sources_per_run` (20) | Ingest at most N sources this run |
| `--if-due` | off | Scheduled mode: do nothing unless today's nightly run has not happened yet. Manual runs never satisfy it. See [Run it every night](../how-to/nightly-job.md) |

A run stops early when it reaches `max_sources_per_run` or `max_tokens_per_run`; what is left stays queued. A source that fails is retried on later runs (three attempts, then it is parked as `failed`). Every failure is reported on its own line, before the summary, with the source (its title if it has one, else its link or path), which attempt it was and a short reason; a source that has used all its attempts says it is parked and that `sb retry` puts it back. The summary line counts them (`failed: 1`). The full error is in `sb status` once the source is parked, and in the daily note under **To review** (**Por revisar** with `language = "es"`), which also lists the sources still being retried. Only one run can be active at a time.

**Exit codes.** `0` when the run finished or stopped early on a limit, and also when another run holds the lock (it prints `Another run is in progress; skipping.`) or `--if-due` found nothing due (`Not due: the nightly run already happened.`). `1` when the model is unreachable: nothing is counted against the sources, the index is still rebuilt, and the message is `The LLM is unreachable (is Ollama running?). Nothing was lost; sources stay queued.` `1` also for a config error, such as an unknown provider in `model`.

```bash
sb run
```

```
    ... chunk 1 of 5
    ... chunk 2 of 5
    ... chunk 3 of 5
    ... chunk 4 of 5
    ... chunk 5 of 5
    ... synthesis
    ... detailed summary
    ... connections
  + Zettelkasten
    ... synthesis
    ... connections
  + Spaced Repetition
ingested: 2, skipped: 0, failed: 0 (20826 tokens)
Lint: 2 issues (see wiki/review/Lint.md)
Wrote wiki/daily/2026-10-03.md
```

A failure looks like this (the same source on its first and its third run):

```
  ! http://localhost:9/old-page: attempt 1 of 3 failed, will be tried again: ExtractError: Refused to fetch http://localhost:9/old-page: localhost resolves to a non-public address (127.0.0.1)
  ! http://localhost:9/old-page: attempt 3 of 3 failed, parked (`sb retry` puts it back): ExtractError: Refused to fetch http://localhost:9/old-page: localhost resolves to a non-public address (127.0.0.1)
```

The reason is cut to one line of at most 160 characters. The lines starting `...` are steps of the source being read: `chunk N of M` is chunk N of M being read, `synthesis` the core note, `detailed summary` the abstract (long sources), `connections` the links to your other notes. A line with `+` is a source written. Warnings (a repaired one-liner, a dropped entity, a skipped chunk) follow it.

## sb ingest

```bash
sb ingest TARGET [--config PATH] [--force] [--dry-run] [--no-commit]
```

Ingests one source immediately, bypassing the queue and the run lock. `TARGET` is an `http(s)` URL, or the path to a PDF, a Markdown note (a Web Clipper clip) or an image.

| Option | Default | Meaning |
|---|---|---|
| `--force` | off | Ingest even if the same URL or the same text is already in the vault |
| `--dry-run` | off | Print the model's edit plan as JSON and write nothing |
| `--no-commit` | off | Write the files but do not commit them to the vault's git history |

A source already in the vault is skipped: `Already in the vault as [[...]] (use --force to redo).` After a successful ingest it prints the title and the pages `created:` and `updated:`, how many notes went to `wiki/review/`, references to unknown pages that were ignored, and entities dropped because their name is not in the source. Errors (an unreadable source, the model down, a refused URL) print `error: ...` and exit 1.

```bash
sb ingest ~/Documents/clips/active-recall.md
```

```
... synthesis
... connections
Ingested: Active recall versus rereading
  created:  Active recall versus rereading, Active Recall, Rereading
  updated:  -
  ignored references to unknown pages: Spaced Repetition
  dropped entities not found in the source: Roland Barthes
  committed to the vault repo
```

## sb reingest

```bash
sb reingest [TITLE...] [--config PATH] [--all]
```

Rebuilds source notes from their originals in `raw/` with the current pipeline. It is how notes written by an older version, or by a weaker model, are upgraded; it needs no network (PDFs are read again so their figures come back).

| Argument / option | Meaning |
|---|---|
| `TITLE...` | Only the notes whose title contains one of these words, whatever their format |
| `--all` | Rebuild every note again, even those already in the current format (`format: 2`) |
| (neither) | Every note that is not yet in the current format |

What it keeps and what it replaces:

- **Language:** the note is rebuilt in the language `[notes].language` names now, so `sb reingest --all` is how old notes follow a change of language. Notes you do not rebuild keep theirs.
- **Kept:** the note's title (so every `[[link]]` to it stays valid), `status`, `read`, `captured`, `content_hash`, and the tags you added.
- **Replaced:** the `## From [[...]]` (or `## Desde [[...]]`, whatever language it was written in) sections the old note added to concept and entity pages are removed and written again; a concept page nobody else cites is deleted.
- **Undo:** before touching anything the vault is committed and tagged `pre-reingest-YYYY-MM-DD`. `git -C <vault> reset --hard pre-reingest-YYYY-MM-DD` brings everything back.
- **Resumable:** a rebuilt note is marked `format: 2`. If the run stops (the model went away, the Mac slept, Ctrl-C), run the command again and it continues.
- One git commit per note. A note whose original is missing in `raw/` is skipped and listed; a note that fails is listed and the rest go on.
- It takes the run lock: it will not start while `sb run` works (`Another run is in progress; try again when it finishes.`, exit 1), and the nightly job skips its turn while it runs.
- It refuses to run without git: `error: reingest rewrites every note and relies on the vault's git history to undo it; install git and run sb init first.`

Expect minutes per source with a small local model.

```
[1/1] Active recall versus rereading
    ... synthesis
    ... connections
Vault tagged pre-reingest-2026-10-03 (undo: git -C ~/Documents/Obsidian/esbi reset --hard pre-reingest-2026-10-03)
rebuilt: 1, skipped: 0, failed: 0
```

## sb import-legacy

```bash
sb import-legacy [--config PATH]
```

Queues every URL in an older folder's `Links/*.md` files (one `[url]` per line, oldest file first) and every PDF in its `PDFs/` folder. It needs `[paths].legacy_vault` in the config; without it: `error: set [paths].legacy_vault to an existing folder` (exit 1). It never changes the old folder and is safe to repeat: known sources are counted as `already known`. The date of each links file becomes the note's `captured` date.

```
Queued 5 sources (0 already known).
```

Run again, it says `Queued 0 sources (5 already known).`

## sb today

```bash
sb today [--config PATH]
```

Opens today's daily note. If the note does not exist yet it is built first. With `viewer = "obsidian"` it prints and opens an `obsidian://open` link (Obsidian must know the vault: open the folder once as a vault). With `viewer = "none"` it only prints the file's path, for any editor.

```
~/Documents/Obsidian/esbi/wiki/daily/2026-10-03.md
```

## sb index

```bash
sb index [--config PATH]
```

Registers the sources you ticked in earlier daily notes (they become `status: read`), then rewrites today's `wiki/daily/YYYY-MM-DD.md` and the managed block of `Home.md`, commits, and pushes to the vault's remote if it has one. It is cheap and needs no model: run it whenever you want the index refreshed. The sections of the note are in [The daily index](daily-index.md).

```
Marked 1 source as read.
Wrote wiki/daily/2026-10-03.md
```

## sb lint

```bash
sb lint [--config PATH]
```

Deterministic checks with no model. Prints a count per kind and writes `wiki/review/Lint.md`, which appears under **To review** in the daily note. The file exists only while there is something to fix. It only reports; it never edits the wiki.

| Kind | Meaning |
|---|---|
| `orphan` | No other page links to this one |
| `broken-link` | A `[[link]]` to a page that does not exist |
| `missing-field` | A page without `title` or `summary` |
| `unlinked-mention` | A concept's name appears in a page that does not link to it. Multi-word names match ignoring case and accents; a single word only matches exactly as written |
| `near-duplicate` | Two concepts or entities that look like the same idea (plural or accent variants, a shared alias) |
| `missing-concept` | A glossary term that two or more source notes define, with no concept or entity page of its own |

```
unlinked-mention: 1
near-duplicate: 1
Details in wiki/review/Lint.md
```

With nothing to report it prints `No problems found.`

## sb ask

```bash
sb ask "QUESTION" [--config PATH] [--save]
```

Answers from the wiki only. It finds the relevant pages with full-text search (and by meaning too, when `[llm.embed]` is set), shows them to the model, and prints the answer plus `Sources: [[...]]`. Only citations that resolve to real pages are kept; an invented link becomes plain text. With no valid citation it prints `I find nothing about this in the wiki.` (in the notes' language) rather than an ungrounded answer (exit 0).

| Option | Default | Meaning |
|---|---|---|
| `--save` | off | File a grounded answer as `wiki/syntheses/<question>.md`, update `index.md` and `log.md`, and commit. The page is named after your question (cut at about 80 characters); a name that already belongs to another page gets ` (synthesis)` (` (síntesis)` in Spanish) |

```bash
sb ask "What is the forgetting curve and how does it relate to notes?"
```

```
The forgetting curve describes the rate at which learned material is forgotten unless reviewed [[Forgetting Curve]]. It suggests that most learned material is forgotten within days unless reviewed.

Sources: [[Spaced Repetition]], [[Forgetting Curve]]
```

It uses `[llm.ask]` if set, otherwise `[llm.summarize]`; with `run.rewrite_questions = true` it first asks the model for search words in the notes' language and English. Every question is appended to `.esbi/asks.jsonl` (the pages retrieved and cited, tokens, seconds). A model error prints `error: ...` and exits 1.

## sb eval

```bash
sb eval [--config PATH] [--k 6] [--rewrite] [--answers]
```

Scores retrieval, the step where `sb ask` picks the pages the model will read, on questions whose source you know. The questions live in `<vault>/.esbi/golden.jsonl`, one JSON object per line, with the start of the expected title(s):

```json
{"question": "What is an agent harness?", "expect": ["Code as Agent Harness"]}
```

| Option | Default | Meaning |
|---|---|---|
| `--k N` | 6 | How many pages count as retrieved (`sb ask` uses 6) |
| `--rewrite` | off | First rewrite each question into search terms (one call each, with the `ask` model) |
| `--answers` | off | Also run `sb ask` on each question and report how many answers were grounded and cite the expected page (slow) |

With no flag it needs no model and finishes in about a second. Without the file it explains the format and exits 1. See [Ask your wiki](../how-to/ask-your-wiki.md#measure-retrieval-with-sb-eval).

```
Retrieval on 4 questions: recall@6 75% (3/4), MRR 0.44
  miss: How do I cook rice? (expected Arroz; got nothing)
```

## sb bench

```bash
sb bench [--config PATH] [--models a,b,c] [--cases N]
```

Runs the same ingest and `ask` cases, built from **your own vault** (raw snapshots and concept pages), through each model, and prints a comparison: success rate, share needing no retry, median latency, tokens per case, estimated cost, the share written in the right language (`[notes].language`), concepts per source, and whether answers cite the right page. It ends with a routing suggestion and saves the report in `.esbi/bench/`. It reads the wiki but never writes to it and never changes `config.toml`.

| Option | Default | Meaning |
|---|---|---|
| `--models a,b,c` | `[bench].models` | Comma-separated `provider/model` list |
| `--cases N` | `[bench].cases` (3) | Cases per task |

A model is suggested only if it succeeds on at least 80% of its cases. Without models, or with an empty vault, it exits 1 (`error: pass --models or set [bench].models in config.toml`; `error: the vault has no sources or concepts to test with yet`). See [Choose how the notes are written](../how-to/models.md#compare-models-on-your-own-notes).

## sb export

```bash
sb export [--out DIR] [--config PATH]
```

Writes the wiki as plain HTML files: a front page listing sources, concepts, entities and syntheses, one page per note, `[[links]]` turned into links, figures copied. `raw/` is never exported.

| Option | Default | Meaning |
|---|---|---|
| `--out DIR` | `<vault>/site` | Where to write the site |

Running it again replaces the previous export. It refuses to write into a folder that has other files in it and is not an export (`error: ... is not an export of this wiki and has other files: not touching it`, exit 1), so it can never wipe something else. The page loads Mermaid from a CDN, so diagrams need an internet connection; everything else works offline. See [Export a website](../how-to/export-a-website.md).

```
Exported 11 pages. Open ~/Documents/Obsidian/esbi/site/index.html
```

## sb setup email

```bash
sb setup email [--config PATH]
```

A guided wizard (bash, bundled with the app) that connects a Gmail mailbox in six stages: turn on 2-Step Verification, create the `esbi-cli` label, route `you+esbi-cli@gmail.com` into it, create an app password, save the settings and the password (the password goes straight into the Keychain), and test it. Stop with Ctrl-C and run it again: nothing changes until stage 5. The full guide is [Capture email](../how-to/email.md).

## sb setup clipper

```bash
sb setup clipper [--config PATH]
```

A guided wizard in five stages: install the Obsidian Web Clipper extension, point it at your vault, import the two templates, clip a test page, and let the worker pick it up. It needs Obsidian: with `viewer = "none"` it explains that and exits 0. See [Web Clipper and YouTube](../how-to/web-clipper.md).

## sb email fetch

```bash
sb email fetch [--config PATH]
```

Saves the last 14 days of mail from the configured Gmail label as clip notes (and PDF attachments) in `inbox/`, skipping mail already saved (by Message-ID). It marks a mail as seen only after its note is written and never deletes mail. `sb run` does this for you.

```
Mail: 2 saved, 0 duplicates, 0 failed.
```

Needs `[email].enabled = true` and `[email].user`; otherwise `error: email is disabled: set [email].enabled = true in config.toml` (exit 1). A login or label error is printed with its cause and exits 1.

## sb email configure

```bash
sb email configure --user ADDRESS [--label NAME] [--config PATH]
```

Turns on mail capture in `config.toml` without the wizard: replaces the `[email]` block (or adds it) and touches nothing else. The password is stored separately with `sb email set-password`.

| Option | Default | Meaning |
|---|---|---|
| `--user ADDRESS` | required | The Gmail address that receives your forwards |
| `--label NAME` | `esbi-cli` | The Gmail label to read |

```
Mail capture on for you@gmail.com, label esbi-cli, in ~/.config/esbi-cli/config.toml
```

## sb email set-password

```bash
sb email set-password [--stdin] [--config PATH]
```

Prompts (hidden) for the mailbox app password and stores it in the macOS Keychain, service `esbi-cli-imap`. Spaces in a Gmail-style password are dropped. It needs `[email].user` in the config first. There is deliberately no `--password VALUE` option: a value on the command line is kept in your shell history and visible in the process list.

| Option | Meaning |
|---|---|
| `--stdin` | Read the password from standard input, to paste without typing: `pbpaste \| sb email set-password --stdin`. Clear the clipboard afterwards |

```
App password for you@gmail.com:
Saved to the Keychain.
```

## sb schedule install

```bash
sb schedule install [--config PATH] [--agents-dir DIR]
```

Writes and loads the launchd agent `com.esbi-cli.nightly` that runs `sb run --if-due` at `[run].nightly_time`, at login, and hourly as a retry net (macOS only). It uses the environment that is running `sb`, so it works wherever that lives, and the config is resolved to an absolute path. Run it again after changing `nightly_time`, and after moving or reinstalling `sb`.

| Option | Default | Meaning |
|---|---|---|
| `--agents-dir DIR` | `~/Library/LaunchAgents` | Where launchd agents live |

```
Installed ~/Library/LaunchAgents/com.esbi-cli.nightly.plist
Runs every day at 03:00 (or at the next wake). Log: ~/Documents/Obsidian/esbi/.esbi/logs/nightly.log
```

The first run needs a macOS permission: see [Run it every night](../how-to/nightly-job.md#first-run-macos-asks-for-permission). On a system without launchd (Linux), the command stops with exit code 1, writes nothing and prints the cron line that does the same, the one `sb init --nightly` prints:

```
error: the nightly job uses launchd, which only macOS has. On this system add this line to cron (`crontab -e`; hourly is fine, it runs once a day):
  0 * * * * sb run --if-due --config /home/you/.config/esbi-cli/config.toml
```

See [Linux and cron](../how-to/nightly-job.md#linux-and-other-systems-cron).

## sb schedule status

```bash
sb schedule status [--agents-dir DIR]
```

Prints whether the agent file exists (`installed:`) and whether launchd has it loaded (`loaded:`). Without launchd it prints the same cron advice as `sb schedule install` and exits 1.

```
installed: yes
loaded: yes
```

## sb schedule uninstall

```bash
sb schedule uninstall [--agents-dir DIR]
```

Unloads the agent and deletes its file. It also removes a job installed under the old project name. Prints `Removed.` or `Nothing to remove.` Without launchd it prints the same cron advice and exits 1: remove your cron line with `crontab -e`.
