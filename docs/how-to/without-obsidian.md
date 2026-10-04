# Use it without Obsidian

The vault is plain Markdown folders (frontmatter, `[[links]]`, `- [ ]` checkboxes), so any editor can read and edit it: VS Code, Logseq, Typora, or just a text editor. Obsidian is only the viewer, and nothing here needs it.

## Turn it off

Set `viewer = "none"` under `[notes]` in `config.toml`, or answer no to the Obsidian question in `sb init` (or run `sb init --no-obsidian`):

```toml
[notes]
viewer = "none"
```

What changes:

- `sb today` prints the path of today's note instead of opening an `obsidian://` link, and `sb doctor` stops asking you to open the folder in Obsidian.
- `sb setup clipper` explains that the Web Clipper needs Obsidian and stops.

## Read and tick

Open today's note with any editor:

```bash
sb today
```

```
~/Documents/Obsidian/esbi/wiki/daily/2026-10-03.md
```

Ticking works the same: put an `x` in `- [ ]` in the daily note with your editor, save, and run `sb index`. See [Read your notes and tick what you have read](read-your-notes.md). The `[[links]]` are Obsidian's wiki-link syntax; other editors show them as text, and some (Logseq, Foam, VS Code with a wiki-link extension) follow them.

## Browse as a website

```bash
sb export
```

writes a read-only website of the wiki for any browser: [Export a website](export-a-website.md).

## Get sources in

`sb add URL`, dropping PDFs and Markdown files in `inbox/`, and email all work without Obsidian. The Web Clipper is an Obsidian project and needs it; another tool that saves a page as a Markdown file with `title:` and `source:` (the URL) at the top works the same if you drop its files in `inbox/`. See [Get sources in](getting-sources-in.md).

## Run it every night

Nothing needs Obsidian: [Run it every night](nightly-job.md).

## What you give up

The graph view, backlinks panel and live search of Obsidian. The questions you would ask them, you can ask the wiki: `sb ask "..."` ([Ask your wiki](ask-your-wiki.md)).
