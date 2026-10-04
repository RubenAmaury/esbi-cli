# Read your notes and tick what you have read

The daily index is where the day starts. This page is the routine: open it, read, tick, register. The meaning of every section is in [The daily index](../reference/daily-index.md); how a note is laid out is in [How a note is made](../explanation/how-a-note-is-made.md).

## Open today's index

```bash
sb today
```

- With `viewer = "obsidian"` it opens today's note in Obsidian through an `obsidian://` link. Obsidian must know the vault: open the folder once with *Open folder as vault*.
- With `viewer = "none"` it prints the path of the file, to open in any Markdown editor:

```
~/Documents/Obsidian/esbi/wiki/daily/2026-10-03.md
```

If today's note does not exist yet it is built first. In Obsidian you can also start from `Home.md`, which links to it.

## Read a note

Under **Processed today** each new source is a checkbox with a one-line summary. Open a source from there. Read the executive summary first and decide whether the source deserves your time; the detailed summary, key ideas, glossary, quotes and connections follow. A note is a draft written by a model, so trust what it quotes (quotes are checked against the source) and treat connections and the diagram as hints: see [Trust: what can be wrong](../tutorials/first-week.md#trust-what-can-be-wrong).

## Tick what you have read

Change the box of a source to `- [x]` in the daily note, save, and run:

```bash
sb index
```

```
Marked 1 source as read.
Wrote wiki/daily/2026-10-03.md
```

The source's `status` becomes `read`, its `read` date is set to today, and it shows under **Read** from then on. Ticking is one way: a ticked source stays read, and unticking it later changes nothing. Ticks in earlier days' notes count too, so a tick you forgot to register is not lost.

You do not have to run `sb index`: every `sb run` registers your ticks before it rebuilds the note. The tick is only read from a line shaped `- [x] [[Source title]]`.

## Edit a note

The notes are yours. You can fix a sentence, add tags, add your own thoughts, or add links. The worker will not overwrite an edit on its own. Two exceptions: [`sb reingest`](manage-the-queue.md#rebuild-old-notes) writes a source note again from its original (its git tag keeps your version), and each new source that mentions a concept adds a `## From [[source]]` section to that concept's page (your own text on the page stays).

Do not edit anything between `<!-- esbi:start -->` and `<!-- esbi:end -->` in `Home.md`: the worker rewrites that block. The rest of `Home.md` is yours.

## Find a note again

- In Obsidian: search, the graph, and backlinks work as usual.
- From the command line: `sb ask "..."` ([Ask your wiki](ask-your-wiki.md)).
- `index.md` in the vault is a catalogue of every page, rebuilt by the worker.

## If a note looks wrong

Edit it, or rebuild it: `sb reingest "<part of its title>"`. A note that is in English or thin usually means the model is too small: see [Choose how the notes are written](models.md).
