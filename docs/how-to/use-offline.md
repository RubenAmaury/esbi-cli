# Use it offline

With a local model, esbi-cli can do almost everything without a network. What needs one is fetching, not thinking.

## What works with no network

With a local model (Ollama or LM Studio on this machine) and the models already downloaded:

| Works offline | How |
|---|---|
| Notes from PDFs, Markdown clips and images | Drop them in `inbox/`, or `sb add file`, then `sb run` |
| Reading, ticking, the daily index | `sb today`, `sb index` |
| Asking questions | `sb ask`, with the keyword search or [hybrid search](ask-your-wiki.md#search-by-meaning) (the embedding model is local) |
| Lint, evaluation, `sb reingest` | `sb lint`, `sb eval`, `sb reingest` (it reads from `raw/`, so it needs no internet) |
| Backup to a drive or NAS | A git remote on your network, or a folder copy |
| Browsing the wiki | `sb export`; everything works except the concept diagrams, which load a library from a CDN |
| The nightly job | It runs on your machine |

## What needs a network

| Needs the network | Why |
|---|---|
| `sb add URL` and `sb run` of a link | The page has to be fetched. A link queued offline fails (`Could not fetch ...`) and is retried on later runs: after three tries it is parked, and `sb retry` puts it back |
| Email capture | IMAP to Gmail |
| A cloud model (API, subscription) | The model is elsewhere. When it cannot be reached the run stops and **nothing is lost**; a `fallback` local model takes over if you set one |
| Downloading a model, installing, updating | Once |
| Pushing the backup to GitHub or another remote | A failed push is only a warning |
| The concept diagrams in an exported site | The page loads Mermaid from a CDN |

## A plan for a flight

Before you go: pull the models you need (`ollama list`), `sb run` so the queue is empty, and put the PDFs you want to read in `inbox/` or save the pages you want as Markdown clips while you are still online (a clip is read from its own text; the worker never fetches it again). In the air: `sb run` writes their notes, and `sb ask` works.

If you use a cloud model normally, set a local `fallback` so the run does not stop when the network goes:

```toml
[llm.summarize]
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"
```

Details: [Choose how the notes are written](models.md).
