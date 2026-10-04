# Tutorial: your first week with esbi-cli

You save links and papers. A worker on your Mac reads them, writes notes you can read instead of the originals, connects them to what you already have, and each morning builds an index note to start from. This tutorial walks through one week, one short step a day. Every command is explained in the [command reference](../reference/cli.md); here you only learn the habit. If you have not installed it yet, start with [Getting started](getting-started.md).

Commands are written as `sb ...`. If `sb` is not found, see [Install](../how-to/install.md#if-sb-is-not-found).

## What you will have after a week

- A routine: save during the day, read in the morning, tick what you have read.
- Notes you trust: you know what is in one, what the model may have got wrong, and how to fix it.
- A wiki that answers questions (`sb ask`).
- A nightly job that works without you.

## Day 0: check the setup

On a brand-new machine, follow [Getting started](getting-started.md) first: it installs `sb`, runs `sb init` (which creates the vault and a config file, and asks which kind of model you want) and makes a first note.

```bash
sb doctor
```

Each line says `ok`, `WARN` or `FAIL`, and what to do about it. You want no `FAIL`. The usual fixes:

| Line | What it means | Fix |
|---|---|---|
| `model summarize: ... is not installed` | Ollama does not have the model | `ollama pull llama3.2` |
| `Ollama is not reachable` | Ollama is not running | `brew services start ollama`, or open the Ollama app |
| `obsidian: this folder was never opened as a vault` | Obsidian has not seen the vault | Obsidian → *Open folder as vault* → `~/Documents/Obsidian/esbi` |
| `nightly job: not installed` | Nothing runs by itself yet | Day 4 |

Open the vault in Obsidian once and look at `Home.md`. That is your start page.

## Day 1: put things in

There are two ways to feed it, and you will use both.

**A link, from the terminal:**

```bash
sb add https://example.com/a-good-article
```

`sb add` only queues it; nothing is downloaded yet. You can pass several links and `.pdf` or `.md` files in one command. A link you already added or already have in the wiki is skipped and says so.

**A PDF:** drop it into the vault's `inbox/` folder (`~/Documents/Obsidian/esbi/inbox/`), or run `sb add paper.pdf`.

See what is waiting:

```bash
sb status
```

Now process it:

```bash
sb run
```

You will see progress for each source, for example:

```
  ... chunk 3 of 7
  ... synthesis
  ... detailed summary
  ... connections
  + Attention Is All You Need
```

What it is doing, in order: reading the source piece by piece (`chunk`), writing the core note (`synthesis`), writing the detailed summary (`detailed summary`), and relating it to your other notes (`connections`). Expect **3 to 15 minutes per source** on a small laptop with a local model; a long paper is on the slow side. This is why the normal way to use it is to let the nightly job do it (Day 4).

`sb run` does at most 20 sources and stops early if it uses its token budget; what is left stays queued for the next run. `sb run --limit 3` does three.

## Day 2: read a note

```bash
sb today
```

This opens today's index note in Obsidian. Under **Processed today** you see each new source as a checkbox with a one-line summary. Click a source to open its note. From top to bottom, a note holds:

| Section | What to do with it |
|---|---|
| **Executive summary** | Two or three sentences. Decide here whether the source deserves your time |
| **Detailed summary** | The argument in order. If you stop here you have not lost the main idea |
| **Key ideas** | Each idea with *why it matters* |
| **Key terms** | A glossary. A term in a link has its own concept page |
| **Key quotes** | Quotes copied word for word from the source. The worker checks they really are in it |
| **Diagram** | A concept map. Treat it as a hint, not as a fact (see "Trust" below) |
| **Figures** | Figures from a PDF, with their captions |
| **Connections to your wiki** | Other notes of yours this one relates to, with the reason |
| **Open questions** | What the source leaves unanswered |
| **Concepts / Entities** | Pages the note created or added to |

When you have read a source, **tick its checkbox** in the daily note (`- [x]`). Wait a few seconds for Obsidian to save, then:

```bash
sb index
```

The source becomes `status: read` and shows up under **Read** next time. Ticking is one way: a read source stays read.

### Trust: what can be wrong

The model that writes the notes is small and local, so some things are wrong sometimes:

- A quote is always real (it is checked against the source). A summary can still be a little off.
- A glossary term is always in the source. Its definition can be loose, and is sometimes left in English.
- Connections can be generic ("both talk about attention"). They are suggestions to follow, not findings.
- The diagram can contain an odd edge.

When something is wrong, edit the note: it is yours. The worker will not overwrite your edit unless you tell it to (`sb reingest`, Day 6).

## Day 3: ask your wiki

```bash
sb ask "what is the difference between an agent harness and a prompt?"
```

It answers only from your notes and cites them. If your notes do not cover it, it says so instead of inventing. A good answer can be kept as a page of its own:

```bash
sb ask "what is the difference between an agent harness and a prompt?" --save
```

It lands in `wiki/syntheses/`. Answers are only saved when you ask.

Tip: ask in the words your notes use. By default the search is by keyword, so a question that shares no words with your notes finds nothing; turning on [search by meaning](../how-to/ask-your-wiki.md#search-by-meaning) fixes most of those. To see how well retrieval works on your notes, use `sb eval`.

## Day 4: let it run by itself

Install the nightly job once (on Linux there is no launchd: use cron, see [Run it every night](../how-to/nightly-job.md#linux-and-other-systems-cron)):

```bash
sb schedule install
sb schedule status
```

It runs `sb run` every day at **03:00**, or at the time you set with `nightly_time = "HH:MM"` under `[run]` in `config.toml` (run `sb schedule install` again after changing it). If the Mac is asleep, it runs at the next wake. macOS asks once whether Python may read your Documents folder: click **Allow**. To have the Mac awake at 03:00 (use your own time if you changed it):

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 03:00:00
```

(Never earlier than the nightly time; an earlier wake finds nothing due.) Check what it did in the morning: `sb status`, the **Ejecuciones** section of the daily note, or `~/Documents/Obsidian/esbi/.esbi/logs/nightly.log`.

The routine now is: during the day `sb add` or drop PDFs; the night processes them; the morning index is waiting.

## Day 5: keep it healthy

```bash
sb lint
```

It only reports. If there is anything, it writes `wiki/review/Lint.md`: broken links, mentions that could be links, possible duplicate pages. Read it, fix what you care about, ignore the rest. Nothing is changed for you.

When a source fails, `sb status` lists it and the daily note shows it under **To review** with the last error. A source is tried three times and then parked as failed.

```bash
sb retry            # put every parked source back in the queue
sb retry URL        # or just one
sb drop URL         # forget a source for good
```

Common causes: the page needs a login (clip it with the Web Clipper instead), the page was a blank shell, or the model was off. If the model is off, nothing is lost: `sb run` stops, keeps the queue, and says so.

## Day 6: upgrade old notes

When a new version of the worker writes better notes, rebuild the ones you have:

```bash
sb reingest                       # every note not yet in the newest format
sb reingest "Attention" "Harness" # only notes whose title contains these words
sb reingest --all                 # everything, again
```

It rebuilds each note from the original saved in `raw/`, so it needs no internet. Your read ticks, dates and tags are kept. Before touching anything it tags the vault in git, so one command undoes the whole rebuild:

```bash
git -C ~/Documents/Obsidian/esbi reset --hard pre-reingest-YYYY-MM-DD
```

A full rebuild of 24 notes took about 2.5 hours on an 8 GB Mac. If it stops (Mac restarts, Ctrl-C), run `sb reingest` again and it continues where it stopped.

## Day 7: what to set up next

- **Email**: forward articles to a dedicated address and they become notes. Setup is one wizard (`sb setup email`); see [Email](../how-to/email.md).
- **Web Clipper**: save pages behind a login and LinkedIn, X or Reddit posts from your browser into `inbox/`. One wizard: `sb setup clipper` (see [Web Clipper](../how-to/web-clipper.md)).
- **Models**: `config.toml` sets which model reads and which writes. `sb bench` compares models on your own notes without touching them.

## When something goes wrong

| Symptom | First thing to try |
|---|---|
| `sb: command not found` | `uv tool update-shell` and a new terminal; see [Install](../how-to/install.md#if-sb-is-not-found) |
| Nothing happened overnight | `sb doctor`, then read `nightly.log`. `Not due: the nightly run already happened` is normal |
| `Another run is in progress; skipping` | A run (or a rebuild) is working; wait for it |
| A run stops with "The LLM is unreachable" | Start Ollama. Your queue is intact |
| `import esbi_cli` fails | See [Troubleshooting](../how-to/troubleshooting.md#the-package-cannot-be-imported-macos-hidden-files) (a macOS hidden-file quirk, source checkouts only) |
| A note looks wrong | Edit it, or `sb reingest "<part of its title>"` |

For how it works inside, read [Why it is built this way](../explanation/internals.md). For one task at a time, see [How do I...?](../how-to/index.md).
