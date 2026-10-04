# SCHEMA — the rules of this wiki

This document defines how the worker (and the LLM) maintains this wiki. It is given to the model as context on every operation. Based on Karpathy's "LLM Wiki" pattern.

## Language
All notes are written in **{language}**. Verbatim quotes keep the language of their source. The language is set by `[notes].language` in config.toml; if that setting and this paragraph disagree, the setting wins.

## Layers
1. `raw/`: the original sources, **immutable** (markdown snapshots, PDFs). Never edited.
2. `wiki/`: pages generated and maintained by the LLM. The human reads; the LLM writes.
3. `SCHEMA.md`: this file.

## Page types (`wiki/`)
- `sources/`: one summary per source.
- `concepts/`: ideas, techniques, topics. One page per concept, which grows with each new source.
- `entities/`: people, organizations, tools, papers.
- `syntheses/`: analyses that cross several sources, and useful answers to questions.
- `daily/YYYY-MM-DD.md`: the daily index.
- `review/`: the queue of things for the human to check.

## Frontmatter
Sources (`wiki/sources/`):
```yaml
---
type: source
title: ""
url: ""            # or a path in raw/
kind: article|paper|email|other
status: processed  # queued | processed | read | failed
captured: YYYY-MM-DD
processed: YYYY-MM-DD
read: null         # YYYY-MM-DD when the human marks it as read
tags: []
---
```
Concepts and entities: `type`, `title`, `aliases`, `tags`, `sources` (a list of wikilinks), `updated`.

## Links
- Use wikilinks: `[[Page title]]`.
- Every source links to the concepts and entities it mentions, and the other way round (a concept lists its sources).
- Prefer updating an existing page to creating a duplicate. Check aliases.

## Operations
- **Ingest**: summarize the source, extract concepts and entities, create or update pages, link them, update `index.md`, add a line to `log.md`.
- **Query**: answer by citing wiki pages; if the answer is valuable, save it in `syntheses/`.
- **Lint**: find orphans, stale claims, contradictions, concepts without a page, broken links.

## Contradictions and doubts
When a new source contradicts existing content, do not overwrite: note the contradiction on both pages and create a note in `review/`. Merges, deletions and uncertain links also go to `review/`.

## Log
`log.md` is append-only. Format: `## [YYYY-MM-DD] ingest | Title`.
