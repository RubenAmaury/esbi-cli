# Frequently asked questions

Short answers, with a link to the page that has the whole story.

## What does it cost?

The program is free and open source (MIT). What costs money is the model that writes the notes:

- **A local model** (Ollama, LM Studio): nothing but electricity.
- **Your Claude subscription**: no extra bill, but every call counts against your plan's usage windows. When one is spent the run stops and resumes later.
- **An API key**: per token. A source costs roughly 3,000 to 25,000 tokens in the worker's own count: in the example in [Getting started](../tutorials/getting-started.md), a five-chunk Wikipedia article and a one-page PDF used 27,252 tokens together. A run stops after `max_tokens_per_run` (300,000 by default), so a mistake cannot run up a large bill. `sb bench` estimates cost per model once you give it prices ([Configuration](../reference/configuration.md#bench)).

## How long does a note take?

With a small local model on a laptop, **3 to 15 minutes per source**; a long paper is on the slow side. That is why the normal way to use it is the [nightly job](../how-to/nightly-job.md). With your subscription or an API, a three-chunk source took about a minute. Reading an image takes from a few seconds to under a minute per page. Rebuilding 24 notes with `sb reingest` took about 2.5 hours on an 8 GB Mac. Asking a question takes seconds to a minute or two.

## Which model should I use?

Start with Ollama and `llama3.2`: free, private, and it runs on an 8 GB Mac. It writes useful but plain notes. If the notes are too thin, move only the writing model (`[llm.synthesize]`) to your subscription or an API and keep the reading local. `qwen3:4b` answers questions with better citations but is about ten times slower. To choose with evidence on your own material, run `sb bench`. See [Choose how the notes are written](../how-to/models.md).

## Is my data private?

With a local model, nothing leaves your machine. With a cloud model (an API key, or your subscription) the text of each source goes to that provider. **Email never does**: a local model reads it, and cloud models are never shown email pages. The mail password lives in the macOS Keychain. There is no telemetry and no account. See [Safety and privacy](safety-and-privacy.md).

## Can I edit the notes?

Yes: they are yours, plain Markdown. The worker does not overwrite an edit on its own. Two things to know: `sb reingest` writes a source note again from its original, so edits to its body are lost (the vault is tagged in git first, so you can get them back; tags and your read ticks are kept); and new sources that mention a concept add a `## Desde [[source]]` section to that concept's page, leaving your text alone. Never edit between the `esbi` marker comments in `Home.md`.

## What if I delete a note?

Nothing breaks, but things around it notice:

- **A source note.** The original stays in `raw/`. The queue still remembers the source as done, so `sb add URL` says `already known`: run `sb drop URL` first, then `sb add URL` to make the note again. Links to the deleted note, in concept pages, become broken, and `sb lint` lists them as `broken-link`.
- **A concept or entity page.** The next source that mentions the idea creates the page again, with only that source's section. Until then, links to it are broken.
- **By mistake.** If you use git (recommended), the deletion is a diff and the note is in the history: [Back up and restore](../how-to/backup.md#undo-a-bad-change-without-restoring).

## Can the notes be in English or another language?

Yes: English (the default) or Spanish, chosen by `[notes].language` in the config (`sb init --language en|es` writes it). The setting decides the instruction to the model, the section headings of every note, the daily index, `index.md`, the lint and benchmark reports and the answers of `sb ask`. Quotes stay in the source's language, and the sources can be in any language the model reads. The command line and the documentation are always English. Details: [Language of the notes](../reference/configuration.md#language-of-the-notes).

Another language is a data-only change in one file (a dictionary entry): [Add a language](../how-to/add-a-language.md). Notes written in a language you no longer use stay as they are, and `sb reingest --all` rebuilds them in the new one.

A question to `sb ask` can be in any language; the answer is in the notes' language.

One limit of a vault that holds both languages: search is by words, and `rewrite_questions` translates a question into the language of `[notes].language` and English only. After switching a Spanish vault to `en`, a question in English may not find a Spanish note by keyword. Turn on [hybrid search](../how-to/ask-your-wiki.md#search-by-meaning) (`[llm.embed]`), which compares meaning, or rebuild the old notes with `sb reingest --all`.

**Does a small model write good Spanish?** Measured with `llama3.2` (3B) on four sources, Spanish and English output both came out in the right language on the first try, with no retry; see the numbers in the pull request that added the setting, or run `sb bench` on your own material. A model that answers in the source's language instead is asked once more, and then kept with a warning.

## Does it run on Windows?

Not natively. macOS is the best supported system; Linux works with the same program but is less tested (cron instead of launchd, no Keychain for email). On Windows, WSL (Windows Subsystem for Linux) runs a Linux system, so follow the Linux route in [Install](../how-to/install.md#linux) inside it. This is untested.

## Do I need Obsidian? Do I need git?

Neither. Obsidian is only a viewer: any Markdown editor works, and `sb export` makes a website ([Use it without Obsidian](../how-to/without-obsidian.md)). Git gives you history and a backup, and is used if it is installed ([Back up and restore](../how-to/backup.md)).

## Can I point it at my existing Obsidian vault?

It is better not to. The worker adds `inbox/`, `raw/`, `wiki/`, `attachments/`, `SCHEMA.md`, `index.md` and `log.md`, and **rewrites `index.md` every run**, so an `index.md` of your own would be overwritten. It never changes your existing notes, but `sb ask`, `sb lint` and the index only look in `wiki/`. Use a separate vault: you can open it in Obsidian next to your own, and link from your notes to it.

## Can I use it on two computers?

Not at the same time on one vault. The run lock is a file lock on one machine, so two machines working on a synced folder can step on each other. Use one machine as the worker and read the vault anywhere, or move the vault between machines with git ([Move to a new Mac](../how-to/move-to-a-new-mac.md)).

## How good are the notes?

Quality tracks the model. A small local model writes useful but unpolished notes; a stronger model writes noticeably better ones. Quotes are always real (they are checked against the source), glossary terms are always in the source, and entities are always named in it. Summaries can still be a little off, connections can be generic, and a diagram can contain an odd edge: treat them as a first draft to read, not as findings. See [How a note is made](how-a-note-is-made.md) and [What the worker repairs](what-the-worker-repairs.md).

## Where do I report a bug or ask for something?

[GitHub Issues](https://github.com/RubenAmaury/esbi-cli/issues). Paste the output of `sb doctor`. Security problems go through private reporting: see [Safety and privacy](safety-and-privacy.md#reporting-a-problem).
