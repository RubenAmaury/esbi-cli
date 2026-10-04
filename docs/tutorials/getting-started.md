# Getting started: from install to your first note

This page takes you from a machine with nothing installed to a first note you can read, one numbered step at a time. Every command is shown with what it prints. Budget about 30 minutes, most of it the model download and the first run.

By the end you will have:

- `sb` installed and checked,
- a model that writes the notes (on your machine, or your Claude subscription, or an API key),
- a vault with a web page and a PDF turned into notes,
- the notes open in Obsidian, in any Markdown editor, or as a website,
- a question answered from your own notes.

Once you have a first note, [A first week](first-week.md) teaches the daily habit and [How do I...?](../how-to/index.md) answers any single task.

## Before you start

You need:

- A Mac (best supported) or a Linux machine, and a terminal.
- About 8 GB of memory for a small local model, and 3 GB of free disk for it. With your Claude subscription or an API key the model runs elsewhere and you need neither.
- Optional: [Obsidian](https://obsidian.md) to read the notes. Any Markdown editor works, and `sb export` makes a website.

Windows is not supported natively; see the [FAQ](../explanation/faq.md#does-it-run-on-windows) for WSL.

## Step 1: install `sb`

Pick **one** row. They install the same program.

| Where | Command |
|---|---|
| macOS with [Homebrew](https://brew.sh) | `brew install rubenamaury/esbi-cli/esbi-cli` |
| macOS or Linux with [uv](https://docs.astral.sh/uv/) | `uv tool install git+https://github.com/RubenAmaury/esbi-cli` |
| A downloaded wheel (any system with uv) | `uv tool install ~/Downloads/esbi_cli-0.1.0-py3-none-any.whl` |
| A copy of the source code | `git clone https://github.com/RubenAmaury/esbi-cli`, then in that folder `uv tool install --editable .` |
| Linux | The `uv` row. Install uv first (below), and git |

Do you not have `uv` yet? Install it once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal afterwards so the command is found. With `uv`, the install ends like this:

```
Installed 1 executable: sb
```

If it adds a warning that the folder "is not on your PATH", run `uv tool update-shell` and open a new terminal.

Check it:

```bash
sb version
```

```
0.1.0
```

Any version number is fine. If you get `sb: command not found`, see [Install](../how-to/install.md#if-sb-is-not-found). The wheel files are attached to every [GitHub release](https://github.com/RubenAmaury/esbi-cli/releases). More detail on every route, and how to update, is in [Install](../how-to/install.md).

## Step 2: get a model

The notes are written by a language model. Choose where it runs. If you are unsure, take **A**.

| | Where the model runs | What leaves your machine | Cost |
|---|---|---|---|
| **A. Ollama** | On your machine | Nothing | Free |
| **B. LM Studio** | On your machine | Nothing | Free |
| **C. Claude subscription** | At Anthropic, through the official `claude` tool | The text of each source | Counts against your plan |
| **D. API key** | At the provider | The text of each source | Per token |

The comparison, and how to change your mind later, is in [Choose how the notes are written](../how-to/models.md).

### A. Ollama (recommended to start)

Install it. On a Mac:

```bash
brew install ollama
```

```bash
brew services start ollama
```

On Linux, or without Homebrew, follow the installer on [ollama.com/download](https://ollama.com/download). Check that it is running:

```bash
curl http://localhost:11434
```

```
Ollama is running
```

Download the model (about 2 GB, once):

```bash
ollama pull llama3.2
```

The last line it prints is `success`. Check:

```bash
ollama list
```

```
NAME                       ID              SIZE      MODIFIED
llama3.2:latest            a80c4f17acd5    2.0 GB    2 minutes ago
```

### B. LM Studio

Install [LM Studio](https://lmstudio.ai), download a model, load it, and start the local server (Developer tab). Note the model's identifier; `lms ls` lists it. You will give it to `sb init` in step 4.

### C. Claude subscription

Install [Claude Code](https://claude.com/code) and log in once:

```bash
claude auth login
```

The worker never sees your login: it only runs the `claude` tool. You will still want a small local model as a fallback and for email, so install Ollama and `llama3.2` as in A.

### D. API key

Put your key in the environment (add the line to your shell profile to keep it):

```bash
export ANTHROPIC_API_KEY="your-key"
```

As with C, install Ollama and `llama3.2` for the fallback and for email.

## Step 3: choose where the notes live

The **vault** is an ordinary folder. `sb` creates it. A good place is `~/Documents/Obsidian/esbi`; any folder works. If you use Obsidian, the vault is the folder you open in Obsidian. Do not put it inside a folder that another program rewrites (a git checkout of another project, for example).

## Step 4: run `sb init`

```bash
sb init
```

`sb init` is an installer. Every question has a default, and the first message says so. This is a real run, with the answers that suit most people (Enter takes the default shown in brackets):

```
esbi-cli turns the PDFs and links you save into a wiki of notes.
That is all you need. Every question below is optional or has a default.

Vault folder [~/Documents/Obsidian/esbi]:
In which language should the notes be written? (The CLI itself is English.)
  1. English
  2. Spanish
Choose [1]: 1
Do you use Obsidian to read your notes? (Any Markdown editor also works) [y/N]: y
How should the notes be written?
  1. On this Mac with a local model (nothing leaves it)
  2. With your Claude subscription (source text goes to Anthropic; email stays local)
  3. With an API key (source text goes to the provider; email stays local)
Choose [1]: 1
Which local runtime? (also used as the failsafe for the other choices)
  1. Ollama (ollama.com)
  2. LM Studio (lmstudio.ai)
Choose [1]: 1
Server address (Enter if it runs on this Mac) []:
Run automatically every night? [y/N]: n
Git remote to back the vault up to (Enter to skip) []:
Vault ~/Documents/Obsidian/esbi: inbox/, raw/, attachments/, wiki/sources/, wiki/concepts/, wiki/entities/, wiki/syntheses/, wiki/review/, wiki/daily/, SCHEMA.md, index.md, log.md, .gitignore, git repository
Config ~/.config/esbi-cli/config.toml: written
Notes language: en (English). The CLI itself is English.
Model: local. Everything stays on this Mac: the notes are written by a local model.

Optional extras (skip both and the app works the same for PDFs and links):
  Connect Gmail, to forward an email and get a note? [y/N]: n
  Set up the Obsidian Web Clipper, to save web pages and YouTube transcripts? [y/N]: n

Next: ollama pull llama3.2, then sb doctor. Add a link with `sb add URL` or drop a PDF in the vault's inbox/ folder.
```

What each question changes:

| Question | What your answer changes |
|---|---|
| **Vault folder** | Where the vault is created, and `paths.vault` in the config. If the folder exists it is kept; only what is missing is added |
| **In which language should the notes be written?** | `1` writes `language = "en"`, `2` writes `language = "es"`: the language of the notes, the daily index and the answers of `sb ask`. It also writes the vault's `SCHEMA.md` and `index.md` in that language. The command line stays English. You can change it later in the config: [Language of the notes](../reference/configuration.md#language-of-the-notes) |
| **Do you use Obsidian?** | `y` writes `viewer = "obsidian"`: `sb today` opens an Obsidian link. `n` writes `viewer = "none"`: `sb today` prints the path of the note, and the Web Clipper question is skipped (it needs Obsidian) |
| **How should the notes be written?** | `1` writes one local model. `2` writes your subscription as the main model with the local one as fallback, plus a local `[llm.private]` model for email. `3` does the same with the Anthropic API. It also says what leaves your machine for each |
| **Which local runtime?** | Ollama or LM Studio. This is the local model for `1`, and the fallback and email model for `2` and `3`. LM Studio asks for the model identifier (`lms ls`) |
| **Server address** | Only for a local model. Leave it empty when the server runs on this Mac. An address on another machine means the text of your notes goes to that machine; `sb init` warns, and `sb doctor` keeps warning |
| **Run automatically every night?** | `y` asks for a time and installs the nightly job on macOS (on Linux it prints a cron line). You can do this later: [Run it every night](../how-to/nightly-job.md) |
| **Git remote** | Only shown when git is installed. A remote makes the vault's history a backup; leave it empty to skip. See [Back up your vault](../how-to/backup.md) |
| **Connect Gmail / Web Clipper** | Offers the two guided setups. Skip them now: [Capture email](../how-to/email.md) and [Web Clipper and YouTube](../how-to/web-clipper.md) cover them later |

You can run `sb init` again at any time. It only creates what is missing and never overwrites your config.

**Without questions.** Every answer is also a flag, so a script can run `sb init` with no questions: `sb init --vault ~/Documents/Obsidian/esbi --model local --language en --no-obsidian`. See the [command reference](../reference/cli.md#sb-init). The settings that were written are explained in [Configuration](../reference/configuration.md).

## Step 5: check the setup

```bash
sb doctor
```

Each line says `ok`, `WARN` or `FAIL`, and what to do about it. On a fresh install you should see:

```
  ok   config: ~/.config/esbi-cli/config.toml
  ok   notes language: en (English)
  ok   vault: ~/Documents/Obsidian/esbi
  WARN obsidian: this folder was never opened as a vault in Obsidian
         fix: Obsidian > Open folder as vault > ~/Documents/Obsidian/esbi
  ok   queue: empty
  WARN last run: no scheduled run yet
         fix: the job does it after the nightly time; or try `sb run --if-due`
  ok   model summarize: ollama/llama3.2:latest is installed
  ok   ocr: off (optional): add [llm.ocr] to read images and scanned PDFs (`sb init --ocr`, docs/reference/configuration.md)
  ok   email privacy: all models are local
  ok   email: off (optional)
  WARN nightly job: not installed
         fix: sb schedule install
  ok   global install: ~/.local/bin/sb
```

You want no `FAIL`. The warnings above are normal now:

- **obsidian**: open the vault once in Obsidian (*Open folder as vault*, then choose the folder). If you do not use Obsidian you will not see this line.
- **last run** and **nightly job**: nothing has run by itself yet. Both are fixed in [Run it every night](../how-to/nightly-job.md), whenever you want.

If a line is `FAIL`, find it in [Troubleshooting](../how-to/troubleshooting.md); the two you are most likely to meet are:

```
  FAIL model summarize: Ollama is not reachable at http://localhost:11434
         fix: brew services start ollama (or open the Ollama app)
  FAIL model summarize: ollama/llama3.2:latest is not installed
         fix: ollama pull llama3.2:latest
```

## Step 6: add your first link

```bash
sb add https://en.wikipedia.org/wiki/Zettelkasten
```

```
Queued 1 (0 already known). `sb run` processes them.
```

`sb add` only queues the link: nothing is downloaded yet. Quote a link that has a `?` or `&` in it, or your shell will try to read it.

## Step 7: add your first PDF

Copy a PDF into the vault's `inbox/` folder (the one you chose in step 4), then ask the worker to look at it:

```bash
cp ~/Downloads/paper.pdf ~/Documents/Obsidian/esbi/inbox/
```

```bash
sb scan
```

```
Queued 1 sources from the inbox.
```

The file has moved to `raw/inbox/`, where originals are kept and never edited. Look at what is waiting:

```bash
sb status
```

```
queued: 2
processing: 0
done: 0
failed: 0
```

You can also do `sb add ~/Downloads/paper.pdf` instead of copying the file. A scanned PDF or a screenshot needs one more setting, described in [Get sources in](../how-to/getting-sources-in.md#images-and-scanned-pdfs-ocr).

## Step 8: run it

```bash
sb run
```

The worker fetches each page, reads it in pieces, writes the note, and links it to the notes you already have. This is the real output for the two sources above, a Wikipedia article and a one-page PDF, with `llama3.2` on a laptop (about three minutes in all):

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

What the lines mean:

| Line | Meaning |
|---|---|
| `... chunk 3 of 5` | A long source is read in pieces; this is piece 3 of 5. A short one has none |
| `... synthesis` | The model writes the core of the note |
| `... detailed summary` | The detailed summary (long sources only) |
| `... connections` | The model relates the note to the ones you already have |
| `+ Zettelkasten` | A note was written |
| `Lint: 2 issues` | The wiki's health check found two things to look at (not errors) |

Expect **3 to 15 minutes per source** with a small local model; a long paper is slower. You can stop with Ctrl-C and run `sb run` again later: what was not finished stays queued (the source that was being read counts one attempt). If you see `The LLM is unreachable (is Ollama running?)`, start Ollama; nothing is lost.

**The notes are in English** because you chose English in `sb init`. Quotes stay in the language of the original. To write in Spanish instead, set `language = "es"` under `[notes]`: see [Language of the notes](../reference/configuration.md#language-of-the-notes).

## Step 9: read the result

The worker wrote one note per source, pages for the concepts and people it found, and today's **index** note. Start with the index:

```bash
sb today
```

- **With Obsidian** (`viewer = "obsidian"`), this opens today's index in Obsidian. If Obsidian does not know the vault yet, open the folder once with *Open folder as vault*.
- **Without Obsidian**, it prints the path of the file; open it in any Markdown editor:

```
~/Documents/Obsidian/esbi/wiki/daily/2026-10-03.md
```

The index lists what was processed, as checkboxes:

```markdown
## Processed today
- [ ] [[Spaced Repetition]] — A learning technique that uses review sessions at increasing intervals to improve memory retention.
- [ ] [[Zettelkasten]] — A system of note-taking and personal knowledge management that consists of small items of information stored on paper slips or cards.
```

Open a note. A note from a long source has an executive summary, a detailed summary, key ideas, a glossary, verbatim quotes, a diagram, figures, connections to your other notes and open questions. A short source gets a shorter note. This is the real note for the PDF:

```markdown
## Executive summary
This paper explains the concept of spaced repetition, describes the forgetting curve, and shows how a personal wiki can use review dates to resurface old notes. It concludes that spacing reviews beats cramming and provides a cheap form of spaced repetition with almost no effort.

## Key points
- The forgetting curve: most learned material is forgotten within days unless reviewed
- Scheduling: simple schedules review notes after one day, three days, one week, and one month
- Notes as a system: linking related ideas helps recall, resurfacing old notes provides spaced repetition

## Connections to your wiki
- [[Zettelkasten]]: **complements**. The Zettelkasten system uses notes as a system, linking related ideas to help recall, which is similar to the concept of spaced repetition in the Spaced Repetition paper.

## Concepts
- [[Forgetting Curve]]
```

When you have read a source, tick its box (`- [x]`), save, and run:

```bash
sb index
```

```
Marked 1 source as read.
Wrote wiki/daily/2026-10-03.md
```

Prefer a website? Make a read-only copy and open it in a browser:

```bash
sb export
```

```
Exported 8 pages. Open ~/Documents/Obsidian/esbi/site/index.html
```

More on every part of the note: [How a note is made](../explanation/how-a-note-is-made.md). What each file is: [What lives where](../reference/vault-layout.md).

## Step 10: ask a question

```bash
sb ask "What is the forgetting curve and how does it relate to notes?"
```

```
The forgetting curve describes the rate at which learned material is forgotten unless reviewed [[Forgetting Curve]]. It suggests that most learned material is forgotten within days unless reviewed.

Sources: [[Spaced Repetition]], [[Forgetting Curve]]
```

The answer comes only from your notes and cites them. When your notes do not cover the question, it says so instead of inventing an answer:

```
I find nothing about this in the wiki.
```

## If something does not work

| What you see | Go to |
|---|---|
| `sb: command not found` | [Install](../how-to/install.md#if-sb-is-not-found) |
| A `FAIL` line in `sb doctor` | [Troubleshooting](../how-to/troubleshooting.md) |
| `The LLM is unreachable (is Ollama running?)` | [Troubleshooting](../how-to/troubleshooting.md#the-model-is-not-reachable) |
| A source that keeps failing | [Troubleshooting](../how-to/troubleshooting.md#a-source-keeps-failing) |
| Something not listed | [Troubleshooting](../how-to/troubleshooting.md), then [open an issue](https://github.com/RubenAmaury/esbi-cli/issues) with the output of `sb doctor` |

## Where to go next

- [A first week](first-week.md): one short step a day, from the first note to a nightly routine.
- [How do I...?](../how-to/index.md): one recipe per task (a folder of PDFs, a YouTube video, email, a backup, a new Mac).
- [Concepts and glossary](../explanation/concepts.md): what a source, a concept and the queue are.
- [Command reference](../reference/cli.md) and [Configuration](../reference/configuration.md).
