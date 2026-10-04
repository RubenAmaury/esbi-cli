# Choose how the notes are written

The notes are written by a language model. You choose where it runs, per task, in `config.toml` (`sb init` writes a first version). All the kinds below work with the same commands, and you can change your mind at any time ([Switch models](#switch-models)).

| Kind | `model =` | What leaves your machine | Good for |
|---|---|---|---|
| Local, Ollama | `ollama/llama3.2:latest` | Nothing | Privacy, no cost; a small model writes useful but plain notes |
| Local, LM Studio | `lmstudio/<identifier>` (see `lms ls`) | Nothing | Same, with LM Studio's model library; set `base_url` if the server is not on port 1234 |
| Your Claude subscription | `claude-cli/default` | Source text goes to Anthropic through the official `claude` tool | Noticeably better notes with no per-token bill; counts against your plan's usage windows |
| An API key | `anthropic/claude-sonnet-5-5`, `openai/gpt-...` (any OpenAI-compatible endpoint with `base_url`) | Source text goes to that provider | Better notes, billed per token |

Which one? Start with Ollama and `llama3.2`: it is free, private and runs on an 8 GB Mac. If the notes are too thin, move only the writing model (`[llm.synthesize]`) to your subscription or an API and keep the reading local. [Different models for different jobs](#different-models-for-different-jobs) shows how.

## Install Ollama and a model

Ollama runs models on your machine. On a Mac:

```bash
brew install ollama
```

```bash
brew services start ollama
```

On Linux, or without Homebrew, use the installer on [ollama.com/download](https://ollama.com/download). Check that it answers:

```bash
curl http://localhost:11434
```

```
Ollama is running
```

Download a model once, then list what you have:

```bash
ollama pull llama3.2
```

```bash
ollama list
```

What is known to work, on an 8 GB Apple Silicon Mac:

| Model | Size | Use it for |
|---|---|---|
| `llama3.2` (3B) | 2.0 GB | The default: reading and writing notes |
| `qwen3:4b` | 2.5 GB | `sb ask`: it cites the right page more often, but is about ten times slower. As the writing model it timed out at 900 s on 8 GB |
| `qwen3:8b` | 5.2 GB | Tight on 8 GB; comfortable on 16 GB |
| `qwen3-vl:2b-instruct` | 1.9 GB | Only for [images and scanned PDFs](#choosing-the-ocr-model) |
| `nomic-embed-text` | 274 MB | Only for [search by meaning](ask-your-wiki.md#search-by-meaning) |

Models whose name ends in `-cloud` run on Ollama's servers, not on your machine; the worker treats them as sending text out.

## Use LM Studio

Install [LM Studio](https://lmstudio.ai), download a model, load it, and start the local server (Developer tab). Find the identifier LM Studio uses for the model:

```bash
lms ls
```

Then tell `sb init` (or edit the config):

```bash
sb init --model local --runtime lmstudio --local-model qwen2.5-7b-instruct
```

In the config it looks like `model = "lmstudio/qwen2.5-7b-instruct"`. `sb doctor` checks that LM Studio answers and serves that identifier.

## Use an Ollama server on another machine

Point the model at it with `base_url`:

```toml
[llm.summarize]
model = "ollama/qwen3:8b"
base_url = "http://192.168.1.50:11434"
```

Be clear about what this means: the text of your notes goes to that machine. The worker treats it like a cloud model: email is kept off it, a remote `[llm.private]` is refused, and `sb doctor` shows `WARN server summarize` for as long as it is set.

## Use an API key

Set the key in your environment, then choose an `anthropic/...` or `openai/...` model:

```toml
[llm.summarize]
model = "anthropic/claude-sonnet-5-5"
fallback = "ollama/llama3.2:latest"
```

The key is never written in `config.toml`. If it lives in a variable with another name, add `api_key_env = "MY_VARIABLE"`. For a service that speaks the OpenAI protocol (OpenRouter, a company gateway) use `openai/<model>` with a `base_url`. A nightly job started by launchd does not see variables from your shell profile, so for unattended runs a local model or the subscription is simpler. Full settings: [Configuration](../reference/configuration.md#setups).

## Use your Claude subscription

Install [Claude Code](https://claude.com/code), then log in once:

```bash
claude auth login
```

Then set `model = "claude-cli/default"` for a task (`sb init --model subscription` writes it for all of them). `sb doctor` checks the login. The app starts `claude` with its tools, settings and plugins switched off, because otherwise every call would carry hundreds of thousands of tokens of your own setup.

## Email always stays local

If any model is a cloud kind, add a local `[llm.private]` model: emails are written only by it, and cloud models are never shown email pages. Without it, emails are refused while a cloud model is set (`sb doctor` warns).

```toml
[llm.summarize]
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"   # used when the main model cannot be reached

[llm.private]
model = "ollama/llama3.2:latest"
```

## Different models for different jobs

`[llm.summarize]` reads each chunk of a long source (many small calls), `[llm.synthesize]` writes the digest and the connections (a few calls), `[llm.ask]` answers questions, and `[llm.private]` reads email. `synthesize` and `ask` fall back to `[llm.summarize]` when absent; `private`, `ocr` and `embed` are simply off. Example:

```toml
[llm.summarize]                # reads each chunk: many cheap calls
model = "ollama/llama3.2:latest"
max_tokens = 1200

[llm.synthesize]               # writes the note: a few calls
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"
```

The full list of settings is in the [configuration reference](../reference/configuration.md).

## Switch models

Edit `config.toml`, then check the setup:

```bash
sb doctor
```

`sb doctor` tells you if the new model is missing (`ollama pull ...`), unreachable or has no key. Notes you already have are not changed by a new model; only new sources use it. To rewrite the old notes with it, run [`sb reingest`](manage-the-queue.md#rebuild-old-notes).

If you have changed `nightly_time`, run `sb schedule install` again. Nothing else needs reinstalling.

## Compare models on your own notes

`sb bench` runs the same ingest and question cases, built from **your own vault**, through each model, and prints a table: success rate, share needing no retry, median latency, tokens, estimated cost, the share written in the right language (`[notes].language`), and whether answers cite the right page. It never writes to the wiki and never changes your config.

```bash
sb bench --models ollama/llama3.2:latest,ollama/qwen3:4b --cases 3
```

It needs a vault with some sources and concepts in it already. It ends with a suggestion for each task (a model is only suggested when it succeeds on at least 80% of cases) and saves the report in `.esbi/bench/`. To price a cloud model, give it a rate in `[bench.prices]`; see [Configuration](../reference/configuration.md#bench). To measure how well `sb ask` finds the right pages, use [`sb eval`](ask-your-wiki.md#measure-retrieval-with-sb-eval).

## Choosing the OCR model

`[llm.ocr]` reads images and scanned PDFs (see [Images and scanned PDFs](getting-sources-in.md#images-and-scanned-pdfs-ocr)). It must be a vision model served by Ollama on your machine; the recommended one is `qwen3-vl:2b-instruct` (1.9 GB download, 3.4 GB in memory at an 8K context, which leaves room for the text model because Ollama keeps one at a time). Use the `-instruct` tag: the plain `qwen3-vl:2b` tag is the "thinking" variant.

Measured on an 8 GB Apple M2 with Ollama 0.13.5, while other programs were also using the model server (so the times are pessimistic). Similarity is the character-level ratio against the known text (1.0 is perfect). The inputs: a real paper page rasterised at 130 dpi (English, 4,500 characters), a rendered Spanish page, a dark-theme code screenshot, a photo of a Spanish slide (rotated, blurred, noisy, JPEG), a Spanish diagram with five labels, and a picture with no text.

| Engine | English page | Spanish page | Code screenshot | Slide photo | Diagram labels | Picture with no text | Time per page |
|---|---|---|---|---|---|---|---|
| `qwen3-vl:2b-instruct` (chosen) | 0.996 | 1.000 | 1.000 | 0.982 | 1.000 | answers `[img]` | 2 to 29 s |
| `granite3.2-vision` (2.4 GB) | 0.537 | 0.717 | 0.675 | 0.982 | 1.000 | invents 725 characters | 12 to 63 s |
| `qwen2.5vl:3b` (3.2 GB) | does not load: its vision step asks Metal for 6.6 GiB and this Mac allows 5.7 GiB | | | | | | |
| macOS Vision (for reference) | 0.999 | 1.000 | 0.973 | 0.982 | 0.805 | nothing | 0.2 to 2.6 s |

A scanned PDF (two pages of the same paper) scored 0.996 with `qwen3-vl:2b-instruct`, 24 s per page. The 0.982 on the slide is the model writing `-` for the bullet `•`; the words are all right.

Why this one: it is the only candidate that is both accurate and honest about an empty picture (granite writes text that is not there), it runs on Ollama so it works on Linux too, and it fits next to the text model. macOS Vision is faster and as accurate, but only exists on macOS and would need a bridge library; it is a possible later addition behind the same `[llm.ocr]` seam. Not tried: `glm-ocr`, `qwen3.5` and `minicpm-v4.6` need a newer Ollama than 0.13.5 (the pull is refused), `deepseek-ocr` is 6.7 GB with an 8K context, and Tesseract needs a system install. If you upgrade Ollama, `glm-ocr` (2.2 GB, built for documents) is worth measuring against these numbers.

What these tests do not show: all inputs are clean renderings or one synthetic "photo", not a pile of real phone photos; handwriting, tables, multi-column layouts and very small print were not measured. Treat the numbers as a floor for clean text and a guess for everything else.
