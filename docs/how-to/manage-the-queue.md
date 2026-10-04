# Manage the queue and old notes

Everything you add waits in the **queue** until `sb run` works through it. This page is about looking at the queue, getting a failed source through, and rebuilding notes. How sources get in is in [Get sources in](getting-sources-in.md).

## See what is queued

```bash
sb status
```

```
queued: 3
processing: 0
done: 5
failed: 0
```

| State | Meaning |
|---|---|
| `queued` | Waiting for a run (also: failed once or twice and will be tried again) |
| `processing` | A run is working on it now |
| `done` | A note was written, or the source was already in the wiki |
| `failed` | Failed three times and is parked until you decide |

`sb status` also lists each parked source with its last error. The names of what is waiting are in today's daily index under **Tomorrow's queue** (the oldest 20), and sources being retried show there too, under **To review**, with the attempt number and the error.

`sb run` scans `inbox/` first. To queue what is in `inbox/` without running anything, use `sb scan`.

## Run a few at a time

```bash
sb run --limit 3
```

A run stops by itself after `max_sources_per_run` sources (20) or `max_tokens_per_run` tokens (300,000), and says so: `Stopped early (max_sources); the rest stays queued for the next run.` The rest is not lost.

## Retry a failed source

A source that fails is tried again on later runs. `sb run` names it and the reason when it fails (`! TITLE: attempt 1 of 3 failed, will be tried again: ...`). After the third failure it is parked as `failed`, and the line says so (`attempt 3 of 3 failed, parked`):

```bash
sb status
```

```
queued: 0
processing: 0
done: 2
failed: 1
  failed: https://en.wikipedia.org/wiki/DoesNotExist12345 (ExtractError: Could not fetch https://en.wikipedia.org/wiki/DoesNotExist12345: Client error '404 Not Found' for url 'https://en.wikipedia.org/wiki/DoesNotExist12345'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404)
```

Read the error, fix the cause, then put it back:

```bash
sb retry
```

```
Requeued 1 source.
```

`sb retry URL` requeues only that one; `sb retry` with nothing parked prints `Nothing to retry.` The next `sb run` tries again. If the cause is not yours to fix (a dead link), forget it:

```bash
sb drop https://en.wikipedia.org/wiki/DoesNotExist12345
```

```
Dropped https://en.wikipedia.org/wiki/DoesNotExist12345
```

Common causes and what to do:

| Last error | What it means | Do |
|---|---|---|
| `No readable article content found at ...` | The page is a login wall, mostly scripts, or very short | Clip it with the [Web Clipper](web-clipper.md), or `sb drop` it |
| `Could not fetch ...: Client error '404 Not Found'` | The link is dead | `sb drop` it |
| `Refused to fetch ...: localhost resolves to a non-public address` | Only public addresses are fetched, by design | Save the page as a Markdown file and drop it in `inbox/` |
| `PDF has almost no extractable text (scanned?)` | A scan | Turn on [OCR](getting-sources-in.md#images-and-scanned-pdfs-ocr) and `sb retry` |
| `... has no readable text (a photo or a diagram?)` | An image with no text in it | `sb drop` it; the worker does not describe pictures |
| A timeout, or a model error | The model was too slow for this input | Try a stronger model, or raise `timeout`; then `sb retry` |

The whole list of messages, by symptom, is in [Troubleshooting](troubleshooting.md).

## Stop a run and continue later

Press Ctrl-C. What was not finished stays in the queue, and the source that was being read counts one attempt. Run `sb run` again whenever you like. If the model goes away (`The LLM is unreachable (is Ollama running?)`), the run stops and **nothing is counted against the sources**.

## Forget a source and add it again

The queue remembers a source as `done` even after you delete its note, so adding the same link says `already known`. To redo it:

```bash
sb drop https://example.com/post
```

```bash
sb add https://example.com/post
```

If the note is still in the wiki, `sb add` skips the link and names the note; to rebuild that note instead, see below, or use `sb ingest URL --force`.

## Rebuild old notes

`sb reingest` rebuilds source notes from the originals in `raw/` with the current pipeline. Use it after an update that says the note format changed, after you switch to a better model, after you change [`[notes].language`](../reference/configuration.md#language-of-the-notes), or when a note came out badly. It needs no network. It keeps your read ticks, dates and tags, and keeps every `[[link]]` to the note valid.

Rebuild every note that is not yet in the current format (`format: 2`):

```bash
sb reingest
```

Rebuild only the notes whose title contains a word:

```bash
sb reingest "Active recall"
```

```
[1/1] Active recall versus rereading
    ... synthesis
    ... connections
Vault tagged pre-reingest-2026-10-03 (undo: git -C ~/Documents/Obsidian/esbi reset --hard pre-reingest-2026-10-03)
rebuilt: 1, skipped: 0, failed: 0
```

Rebuild everything again, even notes already in the current format:

```bash
sb reingest --all
```

With nothing to rebuild it prints `rebuilt: 0, skipped: 0, failed: 0` and touches nothing.

Things to know:

- **Language.** Notes are written in the language the config names when they are rebuilt. Changing `[notes].language` never rewrites old notes by itself; `sb reingest --all` rebuilds every note in the new language (concept pages keep a `## Desde` or `## From` section per source, and the rebuilt note's sections are swapped for ones in the new language; sections of notes you do not rebuild stay as they were). New notes follow the setting at once.
- **Undo.** Before it touches anything it commits the vault and tags it `pre-reingest-<date>`. To go back: `git -C ~/Documents/Obsidian/esbi reset --hard pre-reingest-2026-10-03` (use your vault path and the tag it printed).
- **It replaces the note.** Edits you made in the body of a source note are not kept (the note is written again from the original); the git tag has the old version. Tags you added and the read state are kept.
- **Resumable.** If it stops (the model went away, the Mac slept, Ctrl-C), run `sb reingest` again: notes already rebuilt carry `format: 2` and are skipped. A full rebuild of 24 notes took about 2.5 hours on an 8 GB Mac.
- **Needs git.** It refuses without a git history, because the undo depends on it.
- **One at a time.** It takes the run lock, so it will not start while `sb run` works: `Another run is in progress; try again when it finishes.`
- A note whose original is missing from `raw/` is skipped and listed with the reason.
