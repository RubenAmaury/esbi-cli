# Concepts and glossary

The words esbi-cli uses, in plain language. The first part tells the story in order; the second is an A to Z list you can search.

## The story in one minute

You **save** things: a link, a PDF, an email, a clip from your browser. Each one becomes an item in the **queue**. When `sb run` works through the queue, a language model reads the **source** and the worker writes a **source note** in your **wiki**, plus pages for the **concepts** and **entities** it mentions, and links to the pages you already had. The original is kept in **raw**. Each morning an **index** note lists what was processed so you can read it and tick it off. Later you can **ask** the wiki a question and get an answer that cites your notes.

Three layers, as in Karpathy's LLM Wiki pattern: `raw/` is what you saved and is never edited; `wiki/` is what the worker writes and you read (and may edit); `SCHEMA.md` is the rulebook the model is given.

## Where the pieces live

```
vault/
├── inbox/         drop zone: PDFs, clips, images waiting to be picked up
├── raw/           the originals, never edited
├── attachments/   figures copied out of PDFs
├── wiki/
│   ├── sources/   one note per source
│   ├── concepts/  one page per idea
│   ├── entities/  one page per person, organization, tool
│   ├── syntheses/ answers you saved with sb ask --save
│   ├── daily/     one index note per day
│   └── review/    things for you to look at
├── SCHEMA.md      the rules the model is given
├── index.md       catalogue of every page
├── log.md         append-only history
└── .esbi/         the worker's own state (queue, page index, logs)
```

The full layout is in [What lives where](../reference/vault-layout.md).

## Glossary

**Ask.** `sb ask "question"`: the worker finds the pages that may answer, shows them to a model, and prints the answer with the pages it cites. It answers only from your notes and refuses when it cannot cite one.

**Chunk.** A piece of a long source, cut at paragraph boundaries (about `chunk_chars` characters). A source longer than `max_source_chars` is read chunk by chunk, and the model writes the note from the notes it took on each chunk, never from the raw text.

**Clip.** A Markdown file made by a browser extension (the Obsidian Web Clipper) or by hand, with `title:` and `source:` (the page URL) at the top. The clipped text is the source: the worker does not fetch the page again.

**Concept.** A page about an idea or technique (`wiki/concepts/`). It grows by one `## From [[source]]` section (`## Desde [[source]]` in a Spanish vault) for every source that mentions it.

**Content hash.** A fingerprint of a source's text, kept in the note's frontmatter. The same text arriving under another URL is recognised by it and skipped.

**Daily index** (or daily note). `wiki/daily/YYYY-MM-DD.md`: where the day starts. It is rebuilt from the vault's state on every run; the only thing the worker reads back from it is the boxes you ticked. See [The daily index](../reference/daily-index.md).

**Edit plan.** The JSON the model returns for a source: title, summary, concepts, entities, and so on. The worker validates it against a schema, checks what it claims against the source, and only then writes files. The model never writes a file.

**Entity.** A page about a proper noun: a person, an organization, a tool (`wiki/entities/`). An entity whose name does not appear in the source text is dropped, because small models copy names from other pages.

**Fallback.** A second model named in a `[llm.*]` section, used when the main model cannot be reached (a spent usage window, a lost login, a server down).

**Format 2 note.** The current layout of a source note, marked `format: 2` in its frontmatter: executive summary, detailed summary, key ideas, glossary, quotes, diagram, figures, connections, open questions. Older notes lack the marker; `sb reingest` rebuilds them.

**Frontmatter.** The block of `key: value` lines between `---` lines at the top of a note. The worker keeps `type`, `title`, `url`, `kind`, `status`, `captured`, `processed`, `read`, `tags`, `summary`, `raw`, `content_hash`, `format` there.

**Ingest.** Turning one source into notes: extract its text, read it, plan, check, write. `sb run` ingests the queue; `sb ingest` does one source immediately.

**Inbox.** The vault's `inbox/` folder. Files dropped there are moved to `raw/inbox/` and queued by `sb scan` (which `sb run` does first).

**Kind.** What sort of source it is: `article`, `paper`, `email` or `video`. `email` has special privacy rules.

**Local model.** A model that runs on your own machine (Ollama, LM Studio). The opposite of a model that "sends text out".

**Nightly job.** A scheduled `sb run --if-due` (launchd on macOS, cron elsewhere) that works through the queue at a time you choose.

**Orphan.** A page that no other page links to. `sb lint` lists them.

**Private model.** `[llm.private]`: the only model that is allowed to read email. It must run on this machine.

**Queue.** The list of sources waiting to be ingested, kept in `.esbi/queue.sqlite3`. A source is `queued`, `processing`, `done` or `failed` (after three failed attempts). `sb status` shows the counts.

**Raw.** `raw/`: the original of every source, written once and never edited or overwritten. `sb reingest` rebuilds notes from it.

**Read state.** A source note is `processed` when the worker has written it and `read` when you have ticked it in a daily note and run `sb index`. It never goes back.

**Recall@k and MRR.** The two numbers `sb eval` prints. Recall@k is how often the right page is among the `k` pages retrieved for a question; MRR (mean reciprocal rank) is how high it ranks (1 for first, 0.5 for second).

**Reingest.** `sb reingest`: rebuild source notes from `raw/` with the current pipeline, keeping your read ticks, dates and tags. The vault is tagged in git first, so one command undoes it.

**Review queue.** `wiki/review/`: notes the worker leaves for you instead of acting on them silently (a possible contradiction, the lint report). They also appear under **To review** in the daily index.

**Run lock.** A lock file that makes sure only one `sb run` or `sb reingest` works at a time. A crashed run cannot leave it stuck.

**`SCHEMA.md`.** The rulebook given to the model on every operation: the layers, the page types, the frontmatter, the link rules. You can read it; changing it changes how the model is told to behave.

**Sends text out.** A flag on every model, and the heart of the privacy rules. A model "sends text out" when someone else runs it: an API (`openai`, `anthropic`), your Claude subscription (`claude-cli`), an Ollama or LM Studio server on another machine, or an Ollama `-cloud` model. A model on your own machine does not. Email is never shown to a model that sends text out. See [Safety and privacy](safety-and-privacy.md).

**Source.** One thing you saved: a web page, a PDF, an email, a clip, an image. The worker keeps its original in `raw/` and writes a source note for it.

**Source note.** The page the worker writes for a source, in `wiki/sources/`.

**State folder.** `.esbi/` inside the vault: the queue, the page index, the run history, logs. It is git-ignored except for `golden.jsonl` (your `sb eval` questions); the page index is disposable and rebuilt if deleted.

**Synthesis.** A page in `wiki/syntheses/` made from an answer you chose to keep (`sb ask --save`). It names the pages it came from.

**Vault.** The folder that holds everything: the Markdown files you read, plus `raw/` and the state folder. It is an Obsidian vault, a git repository (when git is installed), and just a folder of text files.

**Viewer.** The `[notes].viewer` setting: `obsidian` (open notes with an `obsidian://` link) or `none` (print paths; use any editor).

**Wiki.** `wiki/`: the notes the worker writes and maintains. You read it; you may edit it.
