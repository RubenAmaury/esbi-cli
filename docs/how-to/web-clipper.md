# Web Clipper and YouTube

The Obsidian Web Clipper is a browser extension that saves what you see as a Markdown file. It is the way to get in pages behind a login, LinkedIn, X and Reddit posts, and YouTube transcripts: the worker never scrapes those, and the clipped text *is* the source. It is optional, and it needs Obsidian.

## Set it up with the wizard

```bash
sb setup clipper
```

The wizard has five stages:

1. Install the extension for your browser and pin it to the toolbar.
2. Add your vault to the Clipper's settings, by the vault's folder name.
3. Import the template [`clipper-template.json`](https://github.com/RubenAmaury/esbi-cli/blob/main/src/esbi_cli/templates/clipper-template.json). It saves into `inbox/` with the properties `title`, `source` (the page URL), `author`, `published` and `kind: article`. The wizard also tells you about the YouTube template (below).
4. Clip a test page (the wizard opens one).
5. Run `sb scan` to check the worker reads the clip.

If your config says `viewer = "none"` the wizard says so and stops: the Clipper saves into an Obsidian vault.

## Use it

Clip a page with the extension. The next `sb run`, or tonight's run, turns it into a note. The clip is not fetched again: whatever you saw is what is read, which is why this works for pages that need a login.

To queue clips without running everything: `sb scan`.

## YouTube videos with a transcript

Import the second template, [`clipper-youtube-template.json`](https://github.com/RubenAmaury/esbi-cli/blob/main/src/esbi_cli/templates/clipper-youtube-template.json). It applies by itself on `youtube.com/watch` pages. Open a video that has a transcript and clip it.

The note is written like any other, from the transcript, and every quote and glossary term that the transcript contains carries a link that opens the video at that second: `([2:20](https://youtube.com/watch?v=...&t=140s))`. The transcript is whatever language the Clipper gets from YouTube (often English, even for a Spanish video); the note is written in the language of `[notes].language`. A video without a transcript cannot be processed this way. The worker never downloads video or audio.

## Without the Clipper

Any tool that saves a page as a Markdown file with `title:` and `source:` (the URL) at the top works the same if you drop its files in `inbox/`. See [Add a Markdown clip](getting-sources-in.md#add-a-markdown-clip).
