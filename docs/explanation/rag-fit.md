# Does esbi-cli fit a RAG workflow?

A review, not a build. The question: if we looked at this project as a retrieval-augmented generation (RAG) system, would its shape hold up, and what would we borrow from a production RAG design, keeping Obsidian as the store?

Reviewed on 2026-10-01 against `main` (after M13), on the real vault: 24 sources, 140 pages.

## Verdict

**Yes, with a different centre of gravity.** A production RAG system does its work at query time: it chunks documents, embeds the chunks, and at question time finds the best chunks and lets a model answer. esbi-cli does its work at **ingest time**: a model reads each source and writes a note (summary, key ideas, glossary, quotes, connections), and the wiki of notes *is* the index. This is Karpathy's "compiled wiki" alternative to chunk embeddings. The offline half of a RAG design matches well. The online half (`sb ask`) is the thin part: keyword retrieval, whole-page context, no evaluation.

It is worth keeping the compiled-wiki design and borrowing four things from RAG: an evaluation set, better context assembly, hybrid retrieval, and an index version. None needs a vector database; all can live in the vault folder and stay readable in Obsidian.

## Stage by stage

The structure on the left is the one from the review request: two systems that share a contract.

| RAG stage | What esbi-cli does | Status |
|---|---|---|
| **Offline: ingest** | Capture from inbox, Web Clipper, email, `sb add`; queue; dedupe by URL and text hash | Done |
| **parse** | trafilatura (web), pymupdf4llm (PDF, with figures), clip reader, GitHub README | Done |
| **chunk** | Paragraph-boundary chunks (8,000 characters), references dropped, sampling past 16 chunks. One strategy for all document types | Done; a single splitter |
| **embed** | None | Gap |
| **index** | Notes in the vault are the index; for lookup, an in-memory SQLite FTS5 table is rebuilt on every call | Different by design; keyword only |
| **evaluate** | `sb bench` scores *models* on format and grounding, not retrieval; no golden question set | Gap |
| **Online: query rewrite** | None: the question's top 20 words are searched as an OR query | Gap |
| **hybrid retrieve** | Keyword (BM25 over title, aliases, body); no dense side | Half |
| **rerank** | None | Gap |
| **generate** | `sb ask`: up to 6 pages, the first 1,500 characters of each, to the model | Done, but see "Context" below |
| **cite** | Citations are checked: `cited_pages` plus inline `[[links]]` must resolve to real pages; invented links become plain text | Done, and stricter than most |
| **refuse** | No valid citation means "No encuentro nada sobre esto en la wiki" | Done |
| **Cache** | None | Gap, low value for one user |
| **Observability** | `runs.jsonl` (counts, tokens, why a run stopped), nightly log, the daily note's *Ejecuciones*; nothing per question | Partial |
| **Security** | Single user. Fetching is public-addresses-only; source text is delimited as data in every prompt; quotes, terms and entities are checked against the source | Fits the use; see "Privacy" |
| **Offline/online separation** | `ingest/` writes; `ask/` reads; they share only the vault's page format and `retrieve.py` | Good |

## What was measured

Two measurements on the real vault, both deterministic and with no model call.

**1. Retrieval quality.** 16 questions written by hand (Spanish and English, about what the notes say), each with the one source that should come back. `find_candidates` is what `sb ask` uses.

| Pages returned (k) | Right source among them | Mean reciprocal rank |
|---|---|---|
| 3 | 13 of 16 (81%) | 0.68 |
| 6 (what `sb ask` uses) | 14 of 16 (88%) | 0.69 |
| 10 | 15 of 16 (94%) | 0.70 |

The two misses at k=6 are both vocabulary mismatches: "juez LLM" against a note titled "JEV-as-a-Judge", and an English question ("what skills should an AI engineer learn") against a note whose key terms are in Spanish (the author's vault was written in Spanish). Keyword search cannot cross that gap; a query rewrite or an embedding can.

**2. Context.** `sb ask` gives the model the first 1,500 characters of each page. The rich notes from M9 have a median body of 6,025 characters. *Ideas clave* (key ideas, in a Spanish vault) starts at about character 1,320 (inside the limit in 16 of 24 notes); *Términos clave* (key terms) starts at about 2,700 (inside the limit in 1 of 24). So the glossary, the quotes and the connections, which the richer notes were built to hold, almost never reach the model. This is the cheapest thing to fix and probably the largest gain.

## How the compiled wiki compares with chunk embeddings

| | Compiled wiki (today) | Chunk embeddings |
|---|---|---|
| Cost | At ingest (minutes per source) | At index time (seconds), and re-embedding on any model change |
| Query time | Fast, no model needed to find pages | Needs the embedding model for each question |
| You can read it | Yes: the notes are the product | No: the index is opaque |
| Provenance | Quotes checked against the source; connections name a reason | Chunk text is the source, unmodified |
| Weakness | The note is only as good as the writing model; a fact the note left out is gone | Chunks lose context; answers can stitch unrelated chunks |
| Cross-language | Fails when the question and the notes use different words | Embeddings handle it well |

They are complements. The note answers "what is this about" and "how does it relate to what I have". The raw source in `raw/` (kept, never edited) is the fallback for "what exactly did it say"; today nothing retrieves from it.

## Update (2026-10-02): what was built from this review

| Addition | Result |
|---|---|
| 1. Golden set and `sb eval` | Built (`sb eval`, questions in `.esbi/golden.jsonl`). The 16 questions above are now the real golden file |
| 2. Better context in `sb ask` | Built: the model gets whole sections in order of usefulness (executive summary, key ideas, glossary, quotes, connections, then the detailed summary), 1,800 characters a page for a local model and 3,500 for a cloud one, instead of the first 1,500 characters. The glossary used to reach the model for 1 note in 24 |
| 3. Query rewrite | Built (`[run] rewrite_questions`, off by default): retrieval recall@6 **88% to 94%**, MRR **0.68 to 0.75**. The cross-language miss ("juez" against "Judge") is fixed |
| 6. Per-question log | Built: `.esbi/asks.jsonl` has the question, pages retrieved, pages cited, grounded, tokens and seconds |
| 4. Hybrid with embeddings | Built (M20, `[llm.embed]`, off by default): see [Hybrid retrieval](#hybrid-retrieval-built-m20). Prefix matching ("engineer" matching "engineering") was tried and measured earlier: no gain, so it was not kept |

End to end with the subscription model on the 16 questions (`sb eval --rewrite --answers`): **100% of answers grounded, 94% cite the expected page** (the local 3B model cited it 33% of the time in the benchmark). The one remaining miss is "what skills should an AI engineer learn", an English question about a note titled "AI Engineering Skills Map ...": common words ("engineer", "skills") also appear in many other pages.

## Hybrid retrieval (built, M20)

An optional `[llm.embed]` model (`ollama/nomic-embed-text`, 274 MB) adds a search by meaning next to the keyword search. Each page is embedded **by section** (its introduction and every `## ` section, each led by the page title), stored as float32 vectors in the same `.esbi/index.sqlite3` (index version 2), and embedded again only when its file changes. A question is embedded with the model's query prefix; the pages are ranked by their best section; that ranking is fused with the FTS5 ranking by reciprocal rank fusion (k = 60). `find_candidates` is the one place this happens, so `sb ask` and the related pages found at ingest both use it. With the section absent, or the embedder down (one warning, then keywords only), search is exactly the keyword search.

Measured on the real vault (a copy: 175 pages, 645 section vectors) with the 16 golden questions through `evaluate()`, the function `sb eval` runs, and the same recorded query rewrites on both sides:

| | recall@3 | recall@6 | recall@10 | MRR (k=6) |
|---|---|---|---|---|
| Keywords only | 75% | 88% | 94% | 0.68 |
| Hybrid | 94% | 94% | 100% | 0.82 |
| Keywords only, questions rewritten | 94% | 94% | 94% | 0.69 |
| Hybrid, questions rewritten | 88% | 94% | 100% | 0.80 |

What the numbers say, without rounding in our favour:

- The dense side is a real gain in **ranking** (MRR 0.68 to 0.82) and in recall without a rewrite (88% to 94% at k=6). Hybrid without a rewrite already matches keywords with a rewrite, so the rewrite call (a paid model call) becomes optional.
- With a rewrite, recall@6 does **not** move (94% both ways); MRR still rises (0.69 to 0.80), and at k=3 hybrid is one question worse (88% vs 94%): the rewrite's extra words push another page above the right one. The two methods overlap rather than add.
- 16 questions is small: one question is 6 points. Fusion constant (10, 30, 60) and feeding the rewrite's words to the dense side made no reliable difference, so the plain version is kept.
- Embedding whole pages instead of sections was **worse** than keywords alone (81% recall@6 at best): a note's meaning is spread over its sections. Dropping the `search_document:` / `search_query:` prefixes that nomic-embed-text expects cost about 20 points of dense-only recall.
- Cost: building the index took 14 s for 175 pages (one-off, then only changed pages; measured while three other agents shared the Ollama server, so treat it as an upper bound), and a question costs about 47 ms more (one embedding call plus a pure-Python scan of the vectors; keyword search alone is 1 ms). The index file grows from 0.5 to 3.1 MB.
- A dense search always returns its nearest pages, so `sb ask` is no longer told "no pages found" before the model call: an unanswerable question now reaches the model, which must still cite a page that exists or the answer is refused.

**Privacy.** A loopback Ollama embedder reads every page. If the embedder is not on this machine (another host, or a `-cloud` model), email-derived pages are never embedded (and the email sections of shared pages are stripped before embedding), and the text of an email being ingested is never used as a query. Vectors made by one embedder are discarded when the configured one changes.

**Ceiling.** The scan is plain Python (about 30 microseconds per vector): fine to a few thousand pages, an estimated 0.6 s a question near 5,000 pages (about 20,000 sections; not measured). Past that, `sqlite-vec` or numpy.

## Ranked additions, with cost

Each stays inside the vault folder (the index in `.esbi/`, git-ignored and rebuildable).

| # | Addition | Why | Cost |
|---|---|---|---|
| 1 | **A golden set and `sb eval`**: the questions above become a file in the vault (`.esbi/golden.jsonl`), and `sb eval` prints recall@k, MRR and the share of answers that are grounded | Everything below needs a number to beat. It also tells you when a change to the notes made retrieval worse | Small: a day |
| 2 | **Better context in `sb ask`**: send the sections that matter (summary, key ideas, glossary, connections) instead of the first 1,500 characters, within a budget | The glossary and connections never reach the model today | Small: hours; measure with #1 |
| 3 | **Query rewrite**: one cheap model call turns the question into search terms in both languages (and the likely title words) | Fixes the two vocabulary misses; no download | Small to medium: one call per question |
| 4 | **Hybrid retrieval with local embeddings**: an Ollama embedding model (for example `nomic-embed-text`, about 270 MB, a download that needs your yes), vectors stored in the existing SQLite next to FTS5, merged by reciprocal rank fusion. The index records the embedding model and the chunking it was built with, so a change is a visible rebuild | Cross-language and paraphrase recall | Medium: a few days, plus the download |
| 5 | **Retrieve from `raw/` as well**, by chunk, when the note is not enough | "What exactly did the paper say" | Medium; do after #4 |
| 6 | **Per-question log**: pages retrieved, tokens, latency, grounded or not, into `runs.jsonl`-style history | Observability for `sb ask` | Small |
| 7 | **Answer cache** keyed by question and index version | One user asks little | Skip until it hurts |
| 8 | **Rerank** | Mostly useful with hundreds of candidates; we return 6 | Skip |

Recommended order: 1, 2, 3 (all small, no download, each measured by #1), then decide on 4 with the numbers in hand.

## Privacy: the one place RAG's security rules apply

"Never embed a document a user is not allowed to see" has no meaning for one user on one Mac. It does have one echo here: if the model is a **cloud API** (or, later, a subscription, see M14), every page sent to it leaves the machine. Today everything runs locally. Two things to decide before using a cloud model for `sb ask` or ingest: whether mail and clipped private pages may be sent, and whether some folders (for example email) should stay local-only.

## Where we differ from the reference structure, on purpose

| Reference | Here | Why |
|---|---|---|
| `schemas/` for Document, Chunk, QueryResult | `llm/schemas.py` (the model's contract) and `ExtractedDoc`; no Chunk type (chunks are strings) | Small, and the contract that matters is the model's JSON |
| Separate vector and lexical stores | One in-memory FTS5 table per call | At 140 pages a rebuild is instant; revisit near a few thousand pages |
| `api/` serving the query path only | `sb ask` in the same package, no server | A personal CLI, not a service |
| Versioned `prompts/` | Prompts in the module that owns them | One owner per prompt is easier to keep consistent; `NOTE_FORMAT` versions the notes |
| ACLs and PII redaction | Not needed for one user | See "Privacy" |

## Reproducing the measurements

The two measurements were run with throwaway scripts against the real vault, not committed. Addition #1 turns the first into a command; the second is a ten-line check on note length against `PAGE_CHARS` in `ask/answer.py`.
