# Export a website

`sb export` writes your wiki as a folder of plain HTML files, to browse in any browser without Obsidian. It is a read-only copy.

## Make the site

```bash
sb export
```

```
Exported 8 pages. Open ~/Documents/Obsidian/esbi/site/index.html
```

Open that file in a browser:

```bash
open ~/Documents/Obsidian/esbi/site/index.html
```

(`xdg-open` on Linux.) To write it somewhere else:

```bash
sb export --out ~/Sites/my-wiki
```

## What is in it

- A front page listing sources, concepts, entities and syntheses, with each page's one-line summary.
- One page per note, with `[[links]]` turned into links and figures copied next to it.
- Concept diagrams, drawn in the browser. The page loads the Mermaid library from a CDN, so diagrams need an internet connection; everything else works offline.
- The pages in `wiki/sources/`, `concepts/`, `entities/` and `syntheses/`. The daily index, `Home.md`, the review notes and `raw/` are not exported.

Notes are shown as text: raw HTML inside a note is displayed, not run, and the site contains no scripts of its own apart from the diagram loader.

## Update it

Run `sb export` again. It replaces the previous export. Ticking is not possible in the site: ticks and edits happen in the Markdown files, then you export again.

## What it will not do

It refuses to write into a folder that has other files in it and is not a previous export, so it can never wipe something that is not an export:

```
error: ~/Documents is not an export of this wiki and has other files: not touching it
```

Pick an empty folder, or a new name.

## Before you publish it

**Notes made from email are in the site.** If you capture email, those notes are ordinary notes and are exported with the rest. Do not put the site on the internet, or share it, if it holds notes from email. `raw/` is never exported.

The site is static files, so anything that serves a folder works: a shared drive, `python3 -m http.server` inside the folder for a quick local look, or a static host. See also [Use it without Obsidian](without-obsidian.md).
