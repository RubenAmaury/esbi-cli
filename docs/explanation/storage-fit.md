# Is SQLite enough, if other people install this and the wiki grows?

Question (2026-10-01): when the app is packaged for other people, will "just SQLite" hold up, or does it need something more robust such as PostgreSQL, especially as the wiki grows?

## Verdict

**SQLite is the right database. What will not scale is not SQLite: it is how the worker reads the vault.** The queue is fine at any size a person will reach. The part that slows down is the lookup of pages and the lint, because they re-read every Markdown file each time. The fix is to keep a persistent index in SQLite (still one file, still zero install), not to move to PostgreSQL. PostgreSQL would add a server, credentials and upkeep for every user, which works against "install it with one command", and it solves nothing the index does not.

## What SQLite does today

| Use | Where | Size it holds |
|---|---|---|
| The work queue | `.esbi/queue.sqlite3` | Thousands of rows |
| Finding related pages (full-text search) | An in-memory FTS5 table, rebuilt from every page on every call | Rebuilt each time |

The notes themselves are Markdown files, not rows. That is by design (you read and edit them in any editor), and it stays.

## Measured

Synthetic vaults shaped like the real one (one source per five concept or entity pages), on this Mac. Your vault today has about 140 pages.

| Pages | Find related pages (`find_candidates`) | One `find_page` | The ~30 lookups of one ingest | `sb lint` | Daily index | On disk |
|---|---|---|---|---|---|---|
| 150 | 0.04 s | 42 ms | 1.3 s | 1.3 s | 0.1 s | under 1 MB |
| 1,000 | 0.25 s | 239 ms | 7.2 s | 48 s | 0.7 s | 2 MB |
| 5,000 | 1.3 s | 1.2 s | 37 s | about 20 min (estimated: it grows with the square of the pages, 25 times the 1,000 figure) | 3.4 s | 11 MB |

The queue, measured separately: 20,000 sources added at 0.35 ms each, and claiming one at 20,000 rows takes 0.3 ms. It is not a concern.

How big does a wiki get? At 5 new sources a day and about 5 new pages per source, that is roughly 9,000 pages a year. So the figures above are a first year or two for a heavy user, not an extreme.

## Why it slows down

`Vault.find_page` and `resolve_page` loop over every page, reading and parsing each file, and an ingest calls them dozens of times (every concept, entity, link and glossary term). `lint` compares every page with every other. Nothing here is a limit of SQLite; each is a full scan done from scratch.

## After M19: the persistent index (measured)

Same synthetic vaults, with the index in place (a fresh process: the index file exists, nothing is cached in memory):

| Pages | Find related pages | One `find_page` | The ~30 lookups of one ingest | `sb lint` | Before (lookups / lint) |
|---|---|---|---|---|---|
| 150 | under 10 ms | 1 ms | under 0.1 s | under 1 s | 1.3 s / 1.3 s |
| 1,000 | under 10 ms | 4 ms | 0.1 s | 5.5 s | 7.2 s / 48 s |
| 5,000 | 20 ms | 18 ms | 0.5 s | about 16 s (1.5 + 2.4 + 1.2 + 1.9 + 9 + 0.4 + 0.3, by check) | 37 s / about 20 min (estimated) |

On your real vault the lint report is identical before and after (339 issues, compared line by line) and runs in 0.47 s instead of 1.4 s. Three changes did it: the index (`src/esbi_cli/index.py`: names, URLs, hashes and the full text in `.esbi/index.sqlite3`, re-reading only files whose size or modification time changed), lint asking the index which pages could mention a name instead of testing every pair, and the duplicate check comparing only titles of similar length with cheap bounds first. What is still linear in the page count (the daily index, orphan and link checks) reads every page once and takes seconds at 5,000.

## What to do, and when

1. **A persistent index in SQLite**, in `.esbi/index.sqlite3`: a `pages` table (path, kind, title, aliases, modified time) and an FTS5 table for the text, updated only for files whose modified time changed. `find_page` becomes an indexed lookup (milliseconds at any size), related-page search stops rebuilding, and lint's "unlinked mention" check can read from the index instead of the files. The index is disposable: delete it and the next run rebuilds it from the vault, so there is nothing to migrate and nothing to back up.
2. **When:** the first row where it hurts is around 1,000 pages (7 s of lookups per ingest, 48 s of lint). A vault of 150 pages does not need it. Do it before packaging for others (M16), because a stranger's first year will pass 1,000 pages.
3. **Embeddings (M17) fit the same file.** If vectors are added later, they can live in the same SQLite file next to FTS5 (for example through the `sqlite-vec` extension), keeping one file and no server.

## When PostgreSQL would be right

Only if the situation changes from "one person, one machine" to one of these:

- several people sharing one wiki, with simultaneous writers;
- a hosted version that serves requests from a web page;
- a corpus so large (hundreds of thousands of pages) that a single file stops being practical.

None of these is the product today. Concurrency on one machine is already handled: a lock lets only one run write at a time, so the queue never has two writers.

## What this means for other users

- Install stays simple: no database server, no password, no port, nothing to keep running.
- Backup is the vault folder (already a git repository, now with an optional private remote). The queue is the only state that is not in the notes, and it can be rebuilt from the vault.
- Lookups stay fast through a persistent index, a disposable SQLite file inside the vault's `.esbi/` folder that is rebuilt from the notes if it is lost.
