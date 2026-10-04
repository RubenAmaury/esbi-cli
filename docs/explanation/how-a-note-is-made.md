# How a note is made

A source note is written so that you can skip the original: read the note, know what the source says, decide whether it deserves your time.

## What a note looks like

You save a link or a paper. A few minutes later there is a note like this (abridged, from a Wikipedia article, written by `llama3.2` on a laptop):

```markdown
## Executive summary
The Zettelkasten is a method of note-taking and knowledge management developed by Niklas Luhmann,
which involves creating a network of interconnected notes and ideas. It emphasizes the importance of
linking and connecting ideas, rather than simply collecting or storing them.

## Key ideas
- **The Zettelkasten system emphasizes the use of index cards to organize and connect ideas.** This
  approach allows users to create a network of interconnected notes, rather than a linear sequence of thoughts.

## Key terms
- **Zettelkasten**: A system of note-taking and personal knowledge management that consists of small
  items of information stored on paper slips or cards.

## Key quotes
> "Every one admits nowadays that it is advisable to collect materials on separate cards or slips of paper."

## Concepts
- [[Index card file]]
```

The language is a setting, `[notes].language` (default `en`). With `es` the same kind of note reads like this (abridged, from a paper on the Transformer, written by an earlier version of the pipeline):

```markdown
## Resumen ejecutivo
El artículo describe el modelo Transformer, que usa mecanismos de atención para la
traducción de secuencias y supera a los modelos publicados en calidad y coste de entrenamiento.

## Ideas clave
- **El Transformer se basa exclusivamente en atención.** Es una alternativa a los modelos
  recurrentes y convolucionales, dominantes hasta entonces.

## Términos clave
- **Self-attention**: Un mecanismo que relaciona posiciones de una secuencia para calcular su representación.

## Frases clave
> "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely"
```

Quotes always stay in the language of the source. Section headings, the daily index and the other text the program writes follow the setting; see [Language of the notes](../reference/configuration.md#language-of-the-notes).

Quotes are checked against the source word for word, glossary terms must appear in it, diagrams are drawn by code, and PDF figures are copied next to the note. The model never touches your files: it only returns JSON that the program validates and then writes.

## How it is made

**Images and scanned PDFs first.** With `[llm.ocr]` set, a vision model reads the text printed in an image (or in each page of a PDF that has no text layer, up to `ocr_max_pages`), and that text is the source from here on: everything below, including the checks that quotes appear verbatim, is against what the OCR model read. The picture itself is kept in `raw/` and shown in the note.

**The language.** The instructions to the model are in English for every output language: they name the language to write in (`Write ALL text in Spanish`) and the request for the note repeats it after the source, where a small model listens. If the answer comes back in the wrong language the worker asks once more, and keeps the second answer with a warning if it is still wrong. A language the program has no word list for is never judged.

The steps:

1. **Reading.** A source that fits in `max_source_chars` goes to the model whole. A longer one (most papers) is cut into chunks at paragraph boundaries; the references section is dropped; beyond `max_chunks` the start, the end and an even spread of the middle are kept. The reading model (`llm.summarize`) takes notes on each chunk: points, defined terms, verbatim quotes, and relations between concepts. A chunk it cannot read is skipped with a warning in the note's log line, not a failure.
2. **Synthesis.** The synthesis model (`llm.synthesize`, or the same one) receives the notes, not the raw text, and writes the digest below.
3. **Connections.** A separate call shows the model the pages you already have (with their one-line summaries) and asks how the new source relates to them, with the reason. It is a separate call on purpose: showing a small model existing pages while it summarizes makes it copy their wording into the new note.
4. **Checks, then writing.** The worker verifies before it writes: quotes must appear verbatim in the source, glossary terms and entities must appear in the source text, invented links are dropped, the diagram is drawn by code from the extracted relations (so it is always valid Mermaid).

What the note contains (sections with nothing to say are left out; the table gives the English heading and, in brackets, the Spanish one):

| Section | What it is |
|---|---|
| Executive summary (`Resumen ejecutivo`) | The 2-4 sentence answer to "what is this and why does it matter" |
| Detailed summary (`Resumen detallado`) | The abstract: the argument in order, with the data that supports it |
| Key ideas (`Ideas clave`) | Each idea with why it matters (or plain key points if the model gave none) |
| Key terms (`Términos clave`) | A glossary of terms the source defines, linked to your concept pages |
| Key quotes (`Frases clave`) | Verbatim quotes worth keeping |
| Diagram (`Diagrama`) | A Mermaid concept map of the relations found |
| Figures (`Figuras`) | PDF figures (up to 8, captioned ones first) copied into `attachments/`; for web pages, images are linked, not downloaded |
| Connections to your wiki (`Conexiones con tu wiki`) | Pages you already have this relates to, with the relation and why |
| Open questions (`Preguntas abiertas`) | What the source leaves unanswered |
| Concepts / Entities / Related (`Conceptos`, `Entidades`, `Relacionado`) | Links to the pages the note created or updated |

Known limits: figures drawn as vectors (not embedded images) are not extracted; a source sampled beyond `max_chunks` is read partially; a page that is mostly a list of links (a GitHub README of links) has little to summarize; quality tracks the synthesis model.
