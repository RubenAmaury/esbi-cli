# Get sources in

A **source** is anything you want a note of. Every way in ends in the same place: the queue, which `sb run` works through (see [Manage the queue and old notes](manage-the-queue.md)). The basics are links and PDFs; everything else is optional.

| Source | How | Notes |
|---|---|---|
| Web page | `sb add URL`, or clip it with Obsidian Web Clipper into `inbox/` | Clipping is best for pages behind a login |
| PDF or paper | Drop it in `inbox/`, or `sb add path.pdf` | A PDF with no text layer (a scan) needs [OCR](#images-and-scanned-pdfs-ocr); without it, it is rejected with a message saying so |
| A folder of PDFs | `sb add folder/*.pdf` | [Recipe](#add-a-folder-of-pdfs) |
| Screenshot, photo of a slide, scanned page | Drop the image in `inbox/`, or `sb add image.png` | Needs [OCR](#images-and-scanned-pdfs-ocr) (optional): png, jpg, webp, tiff |
| LinkedIn, X, Reddit, YouTube | Clip with Web Clipper | Never scraped by the worker; the clipped text *is* the source |
| Email | Forward to your `+esbi-cli` address ([Email](email.md)) | The mail body is the source; links inside are not followed |
| Old vault | `sb import-legacy` (once) | Reads its `Links/` and `PDFs/` |

A Markdown clip is ingested from its own body; its `source:` (or `url:`) frontmatter becomes the source URL, `title:` its title and `kind:` (`article`, `paper`, `email` or `video`) its kind. Every URL the worker fetches itself is checked first: only `http(s)`, only public addresses, on every redirect.

## Add a link

```bash
sb add https://en.wikipedia.org/wiki/Zettelkasten
```

```
Queued 1 (0 already known). `sb run` processes them.
```

Nothing is downloaded yet. Add as many as you like in one command: `sb add URL1 URL2 URL3`. Put a link that has `?` or `&` in quotes, or the shell reads it: `sb add "https://example.com/post?id=7"`. Then:

```bash
sb run
```

To do one right now, without the queue, use `sb ingest URL` (add `--dry-run` to print the model's plan and write nothing). A page that needs a login, or is mostly scripts, fails with `No readable article content found`: clip it with the [Web Clipper](web-clipper.md) instead. A GitHub repository link is read through its README.

## Add a PDF

Either copy it into the vault's `inbox/` folder and scan:

```bash
cp ~/Downloads/paper.pdf ~/Documents/Obsidian/esbi/inbox/
```

```bash
sb scan
```

```
Queued 1 sources from the inbox.
```

or give its path to `sb add`, which leaves the file where it is:

```bash
sb add ~/Downloads/paper.pdf
```

The difference: a file in `inbox/` is moved to `raw/inbox/`, which keeps it for good. A file added by path is read from where it is when the run starts, so do not move it before then. Either way a copy of the PDF is saved in `raw/` when the note is written. `sb run` scans `inbox/` itself, so `sb scan` is only for seeing the queue early.

## Add a folder of PDFs

Let the shell list the files:

```bash
sb add ~/Papers/*.pdf
```

```
Queued 2 (0 already known). `sb run` processes them.
```

If the PDFs are in subfolders, copy them all into `inbox/` first:

```bash
find ~/Papers -name '*.pdf' -exec cp {} ~/Documents/Obsidian/esbi/inbox/ \;
```

Two different files with the same name would overwrite each other during the copy (the worker only protects files after they reach `inbox/`). The worker skips a PDF it already has (same bytes, even under another name) and keeps a different PDF with the same name as `name (2).pdf`. A big folder takes a long time with a local model: `sb run --limit 5` processes five at a time, and the nightly job does 20 a night (`max_sources_per_run`).

## Add a Markdown clip

A clip is a Markdown file with `title:` and `source:` (the page URL) at the top. The Web Clipper makes them; so can any tool that saves a page as Markdown.

```markdown
---
title: Notes on the spacing effect
source: https://example.org/spacing
kind: article
---

The spacing effect says that learning is better when study sessions are spread out...
```

Drop it in `inbox/` (or `sb add clip.md`). The text of the file is the source; the page is not fetched again. A clip with fewer than 40 characters of text is rejected as empty. Setting the Clipper up: [Web Clipper and YouTube](web-clipper.md).

## Add a YouTube video

Clip the video page with the Web Clipper's YouTube template: it needs a video that has a transcript, and it is described in [Web Clipper and YouTube](web-clipper.md#youtube-videos-with-a-transcript). The note is written from the transcript, and quotes and glossary terms get a link that opens the video at that second. The worker never downloads video or audio.

Without the Clipper, a file with `kind: video`, `source:` set to the video's URL and a transcript with one line per row, each written as `**2:20** · text of the line`, is read the same way.

## Add an image or a scanned PDF

This needs OCR turned on once ([below](#images-and-scanned-pdfs-ocr)). Then it is the same as a PDF:

```bash
sb add ~/Pictures/slide.png
```

```
Queued 1 (0 already known). `sb run` processes them.
```

Without OCR, `sb add` says why instead of queueing:

```
error: not an http(s) URL or an existing .pdf/.md file:
  ~/Pictures/slide.png
  Images: add an [llm.ocr] model to config.toml to read images and scanned PDFs (`sb init --ocr`, docs/reference/configuration.md)
```

## Add an email

Set up the mailbox once (`sb setup email`); after that, forward anything to your `you+esbi-cli@gmail.com` address and the next `sb run` makes a note. See [Capture email](email.md).

## Import an older vault

If you have an older folder of links and PDFs (`Links/DD-MM-YYYY.md` with one `[url]` per line, and `PDFs/`), set `legacy_vault` under `[paths]` in the config and run it once:

```bash
sb import-legacy
```

```
Queued 5 sources (0 already known).
```

It never changes the old folder, and is safe to repeat.

## Images and scanned PDFs (OCR)

Off by default. Turn it on with `sb init --ocr` (for a config you already have, add `[llm.ocr]`, see [Configuration](../reference/configuration.md)) and pull the model once:

```bash
ollama pull qwen3-vl:2b-instruct     # 1.9 GB download, about 3.4 GB in memory while it reads
```

A vision model served by Ollama on your machine reads the text printed in the image, and that text becomes the source: the note is made like any other (summary, glossary, quotes checked against the text). The original image is kept in `raw/` and shown in the note under "Figuras".

- **What it reads well**: screenshots, slides, and pages of text, in English and Spanish, including a photo taken at a slight angle with some noise. Measured numbers are in [Choosing the OCR model](models.md#choosing-the-ocr-model).
- **What it cannot do**: a photo or a diagram with no text has nothing to read. The source then fails with `no readable text`, and the reason is kept in the queue (`sb status`); no empty note is written. It does not describe pictures, because a description is the model's guess and none of it can be checked against the source. It does not read handwriting reliably, and it can drop or swap a word in dense small print: check anything that matters against the original.
- **Scanned PDFs**: a PDF whose pages have no text layer is rendered page by page and read the same way. At most `[run].ocr_max_pages` pages (default 10) are read; when a PDF is longer the run says how many were read.
- **Time**: expect from a few seconds (a screenshot) to under a minute per page on a small Mac, since the reading model and the writing model take turns in Ollama.
- **Private by construction**: the OCR model must be an Ollama model running on this machine (`[llm.ocr]` refuses anything else), so an image, and the text read from it, is never sent to a cloud model. If a scanned PDF came attached to an email, the text read from it is treated as email (only your local `[llm.private]` model writes it).
- **Not supported** (reported by `sb scan` and `sb run`, never ignored): HEIC (convert it to JPG first), Word, and any other file type. They stay in `inbox/`.

## If a source already exists

The worker never ingests the same thing twice, and never destroys an earlier copy.

| You add | What happens |
|---|---|
| The same link again (tracking junk, case or trailing slash differ) | `sb add` says `already known`; nothing is queued twice |
| A link that is already a note in the wiki | `sb add` skips it and names the page (`already in the wiki as [[...]]`) |
| A link already ingested, but never seen by `sb add` (for example through `sb ingest`) | Queued, then skipped at run time with no model call (`skipped`); the page is fetched once more first |
| The same PDF or clip dropped in `inbox/` again, even renamed | Recognised by its bytes, removed from the inbox, reported as a duplicate |
| A *different* PDF with the same file name | Both kept: the new one is stored as `name (2).pdf` and processed |
| The same text under another path or URL | Caught when ingested, by a hash of its text: `skipped` |
| A page whose content changed since you ingested it | Skipped (same URL). To redo it: `sb ingest URL --force` |
| A link you deleted from the wiki and want again | The queue still remembers it as done: `sb drop URL`, then `sb add URL` |
| The same email again | Recognised by its Message-ID and marked seen, not saved twice |
