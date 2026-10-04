# Configuration reference

All settings live in one TOML file, `config.toml`. `sb init` writes a first version; this page lists every key, its default, and a complete example for the common setups. For the choice between models, read [Choose how the notes are written](../how-to/models.md) first.

## Where the config file is

The first file that exists in this list is used:

1. `--config PATH`, given to the command.
2. The `ESBI_CONFIG` environment variable.
3. `~/.config/esbi-cli/config.toml` (where `sb init` writes it).
4. A `config.toml` next to an editable install of the project (so a `uv tool install --editable` copy works from any folder).

A `config.toml` in the **current folder** is never read: a cloned repository could otherwise point the model or the mailbox at someone else's server.

`sb info` prints which file is used. A file you name on purpose must exist: if the `--config` path (or the file `ESBI_CONFIG` points at) is missing, the command stops with `error: config file not found: PATH` and exit code 1. Only the default places (3 and 4) are tried one after the other without a message.

```bash
sb info
```

```
config=~/.config/esbi-cli/config.toml
vault=~/Documents/Obsidian/esbi
viewer=none
language=en
email=disabled
```

Edit the file with any editor. There is nothing to reload: the next command reads it again. Two things need a second step: a changed `nightly_time` needs `sb schedule install` again, and a changed `[llm.embed]` model rebuilds the page index on the next `sb ask` or `sb run`.

The file is checked whenever it is read, in every section. A misspelled key, an unknown section, or a value of the wrong type stops the command with one `error:` line (exit code 1) that names the section, the key and what is valid, and `sb doctor` shows it as `FAIL config`:

```
error: [llm.summarize] has an unknown key 'num_ctxx' (did you mean 'num_ctx'?). Valid keys: model, base_url, api_key_env, num_ctx, temperature, timeout, fallback, max_tokens
error: [run].max_chunks must be a whole number, got 'ten'
```

## A complete file

This is the starter file (`config.example.toml`) with every key at its default. Lines starting with `#` are optional sections.

```toml
[paths]
vault = "~/Documents/Obsidian/esbi"
# legacy_vault = "~/Notes/old-links"

[notes]
language = "en"
viewer = "obsidian"

[run]
max_source_chars = 4000
chunk_chars = 8000
max_chunks = 16
ocr_max_pages = 10
find_connections = true
rewrite_questions = false
nightly_time = "03:00"
max_sources_per_run = 20
max_tokens_per_run = 300000
flag_contradictions = false

[llm.summarize]
model = "ollama/llama3.2:latest"
num_ctx = 8192

# [llm.synthesize]
# [llm.private]
# [llm.ocr]
# [llm.ask]
# [llm.embed]

[bench]
models = ["ollama/llama3.2:latest"]
cases = 3

[bench.prices]

[email]
enabled = false
imap_host = "imap.gmail.com"
mailbox = "esbi-cli"
# user = "you@gmail.com"
```

## `[paths]`

| Key | Default | Meaning |
|---|---|---|
| `vault` | required | The vault folder. `~` is expanded. Without it every command fails with `config.toml needs [paths].vault` |
| `legacy_vault` | none | An older folder with `Links/` and `PDFs/`, read only by `sb import-legacy` |

## `[notes]`

| Key | Default | Meaning |
|---|---|---|
| `language` | `"en"` | The language the notes are written in: `"en"` (English) or `"es"` (Spanish). It sets the instruction to the model, the section headings (`Executive summary`, `Resumen ejecutivo`...), the daily index, `index.md`, the lint and benchmark reports and the answers and refusals of `sb ask`. Quotes stay in the source's language. Any other value is an error that lists the supported ones. A missing key means `"en"`. See [Language of the notes](#language-of-the-notes) |
| `viewer` | `"obsidian"` | `"obsidian"` opens notes with `obsidian://` links; `"none"` makes `sb today` print a path and stops `sb doctor` asking you to open the folder in Obsidian. Anything else is an error |

### Language of the notes

`[notes].language` is the one setting that decides the language of everything the program writes into the wiki. The command line itself (messages, `--help`, errors) is always English.

| Value | Language | Example heading |
|---|---|---|
| `"en"` | English (the default) | `## Executive summary` |
| `"es"` | Spanish | `## Resumen ejecutivo` |

What follows the setting: the notes' section headings and labels (`## From [[Source]]` on concept pages), the daily index and the `Home.md` block, `index.md`, the lint report, the `sb bench` report, and what `sb ask` answers and refuses with. The instruction to the model says which language to write in; if the model answers in the wrong language, the worker asks once more and then keeps the answer with a warning.

Changing the setting is safe: the worker never rewrites a note by itself. Notes already written keep their language, and every reader (privacy filters, `sb ask`, read ticks, `sb reingest`) recognises the headings of both languages, so a vault can hold both. To rebuild the old notes in the new language, run `sb reingest --all` (see [Manage the queue](../how-to/manage-the-queue.md#rebuild-old-notes)). Your `SCHEMA.md` is never overwritten; its `Language` paragraph says which language the notes are in, and the setting wins if they disagree.

`sb init --language en|es` writes the setting and the vault's `SCHEMA.md` and `index.md` in that language. To add a language, see [Add a language](../how-to/add-a-language.md).

## `[run]`

| Key | Default | Meaning |
|---|---|---|
| `max_source_chars` | `4000` | A source up to this many characters is read by the model in one go; a longer one is read in chunks (see [How a note is made](../explanation/how-a-note-is-made.md)) |
| `chunk_chars` | `8000` | Size of each chunk of a long source |
| `max_chunks` | `16` | Beyond this many chunks a source is sampled: its start, its end and an even spread of the middle |
| `ocr_max_pages` | `10` | A scanned PDF is read (OCR) up to this many pages; the run says when it stopped short |
| `find_connections` | `true` | One extra model call per source that relates the new note to pages you already have, with the reason. `false` skips it (faster, no "Connections to your wiki" section) |
| `rewrite_questions` | `false` | `sb ask` first asks the model for search words in the notes' language and in English (one small extra call). Finds notes whose words differ from the question's. Measured on 16 questions: right page in the top 6 for 88% without, 94% with |
| `nightly_time` | `"03:00"` | When the nightly job runs, `HH:MM` in 24 hours. Re-run `sb schedule install` after changing it. A bad value is rejected when the config is read |
| `max_sources_per_run` | `20` | Sources per run (`sb run --limit` overrides it) |
| `max_tokens_per_run` | `300000` | A run stops once the models have used this many tokens; what is left stays queued |
| `flag_contradictions` | `false` | When `true`, the model may flag contradictions between a new source and existing pages: they become notes in `wiki/review/` and a `[!warning]` on the page. Off because small models flag tenuous ones; turn it on with a stronger model |

## `[llm.<task>]`

One section per task. Each task can use a different model.

| Section | Used for | If absent |
|---|---|---|
| `[llm.summarize]` | **Required.** Takes notes on each chunk of a long source; writes the whole note when there is no `synthesize` | Every command that needs a model fails, saying there is no `[llm.summarize]` section |
| `[llm.synthesize]` | Writes the core note, the abstract and the connections (a few calls per source). Use a stronger model here: reading is cheap, synthesis is where quality is made | `summarize` does it |
| `[llm.ask]` | `sb ask`, question rewriting, `sb eval --rewrite/--answers` | `summarize` |
| `[llm.private]` | The only model that reads email. Must run on this machine | Emails are refused while a cloud model is set |
| `[llm.ocr]` | Reads images and scanned PDFs. Must be an Ollama vision model on this machine | Images are not read; scanned PDFs are rejected |
| `[llm.embed]` | Embeddings for search by meaning (hybrid search). Only `ollama/<model>` | Search is by keyword only |

Any `[llm.<task>]` section accepts these keys:

| Key | Default | Meaning |
|---|---|---|
| `model` | required | `<provider>/<name>`, see the providers below |
| `base_url` | the provider's usual address | Where the server is. For Ollama and LM Studio, an address that is not this machine is reported by `sb doctor` as sending text out, and email is kept off it |
| `api_key_env` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | The **name** of the environment variable that holds the key. Keys are never written in the file |
| `num_ctx` | `8192` | The context window, in tokens. Ollama only |
| `temperature` | `0.2` | Sampling temperature. Not used by `claude-cli` |
| `timeout` | `300` | Seconds to wait for one answer. A timeout fails that chunk or source; the run goes on |
| `max_tokens` | none | A cap on the length of an answer. Ollama only. Set it on the model that reads chunks: small models sometimes loop on one input, and the cap turns a 5-minute timeout into seconds |
| `fallback` | none | A second `<provider>/<name>` used when the main model cannot be reached (a spent usage window, a lost login, a server down). A timeout does not trigger it. `sb doctor` checks it too |

### Providers

| Provider | Talks to | Notes |
|---|---|---|
| `ollama/<name>` | Ollama's API, default `http://localhost:11434` | Nothing leaves your machine unless `base_url` points elsewhere or the name ends in `-cloud` |
| `lmstudio/<identifier>` | LM Studio's local server, default `http://localhost:1234/v1` | No key. The identifier is what `lms ls` shows |
| `openai/<name>` | Any OpenAI-compatible endpoint | Set `base_url` for OpenRouter and similar. Key from `OPENAI_API_KEY` or `api_key_env`. Text goes to that provider |
| `anthropic/<name>` | Anthropic's Messages API | Key from `ANTHROPIC_API_KEY` or `api_key_env`. Text goes to Anthropic |
| `claude-cli/<model>` | The official `claude` command, paid by your Claude Pro or Max subscription | `claude-cli/default` (your account's model) or `claude-cli/sonnet`. No key in any file; log in once with `claude auth login`. `max_tokens` and `num_ctx` do not apply |

A model that sends text away (`openai`, `anthropic`, `claude-cli`, and a remote Ollama or LM Studio) is never shown email. The rules are in [Safety and privacy](../explanation/safety-and-privacy.md#email-stays-local).

### Using a subscription

Log in once with `claude auth login` (Claude Code must be installed), then point a task at it. Three things to know. (1) Every call counts against your plan's usage windows (a session limit and a weekly one). When you hit one, the call fails with the tool's message, the run stops like any other model outage, nothing is lost, and the next run resumes. (2) The tool is started with its tools, settings, plugins and MCP servers switched off: otherwise one call carried about 450,000 tokens of your own setup (about 700 with them off). (3) How Anthropic counts non-interactive use against a plan has changed before; check your plan's terms.

## `[email]`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Fetch mail during `sb run` |
| `imap_host` | `"imap.gmail.com"` | The IMAP server |
| `mailbox` | `"esbi-cli"` | The mailbox name to read; for Gmail, the label |
| `user` | none | The mailbox address. The app password is not here: it lives in the macOS Keychain under the service `esbi-cli-imap` |

`sb setup email` or `sb email configure` writes this block for you.

## `[bench]`

Used only by `sb bench`; nothing here changes which model the worker uses.

| Key | Default | Meaning |
|---|---|---|
| `models` | none | The candidate models, `["ollama/qwen3:4b", ...]` |
| `cases` | `3` | Cases per task |
| `prices` | none | The `[bench.prices]` table: USD per million tokens (input and output blended) per model, for the cost estimate. Local models cost 0 |

```toml
[bench.prices]
"anthropic/claude-sonnet-5-5" = 9.0
```

## Environment variables

| Variable | Used for |
|---|---|
| `ESBI_CONFIG` | The config file, when `--config` is not given |
| `ANTHROPIC_API_KEY` | The key for `anthropic/...` models (or the variable named by `api_key_env`) |
| `OPENAI_API_KEY` | The key for `openai/...` models (or the variable named by `api_key_env`) |
| `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` | Honoured when fetching web pages; see [Safety and privacy](../explanation/safety-and-privacy.md) |
| `UV_PROJECT_ENVIRONMENT` | Only for development from a checkout: keeps the virtual environment out of an iCloud-synced folder |

## Setups

Each block is the whole `[llm.*]` part of the file for that setup. Everything else stays as it is.

### All local (Ollama)

```toml
[llm.summarize]
model = "ollama/llama3.2:latest"
timeout = 300
num_ctx = 8192
max_tokens = 1200
```

This is what `sb init --model local` writes. Nothing leaves your machine. Needs `ollama pull llama3.2`.

### All local (LM Studio)

```toml
[llm.summarize]
model = "lmstudio/qwen2.5-7b-instruct"
timeout = 300
```

Use the identifier `lms ls` shows. `sb init --model local --runtime lmstudio --local-model NAME` writes it. Add `base_url = "http://localhost:1234/v1"` only if the server runs on another port.

### Subscription, with a local fallback

```toml
[llm.summarize]
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"
timeout = 300

[llm.synthesize]
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"
timeout = 600

[llm.ask]
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"
timeout = 600

[llm.private]
model = "ollama/llama3.2:latest"
```

This is what `sb init --model subscription` writes. A good split is a local reading model (many small calls) and only the writing model on the subscription (a few calls per source): a 3-chunk source took about one minute that way, against several locally.

### API key

```toml
[llm.summarize]
model = "anthropic/claude-sonnet-5-5"
fallback = "ollama/llama3.2:latest"
timeout = 300

[llm.ask]
model = "anthropic/claude-sonnet-5-5"
fallback = "ollama/llama3.2:latest"
timeout = 600

[llm.private]
model = "ollama/llama3.2:latest"
```

Set the key in the environment (`export ANTHROPIC_API_KEY=...` in your shell profile; for the nightly job the variable must be visible to launchd, which does not read your shell profile, so prefer the subscription or a local model for unattended runs). For an OpenAI-compatible service use `model = "openai/gpt-4o-mini"`, and `base_url = "https://openrouter.ai/api/v1"` with `api_key_env = "OPENROUTER_API_KEY"` for OpenRouter.

### Ollama on another machine

```toml
[llm.summarize]
model = "ollama/qwen3:8b"
base_url = "http://192.168.1.50:11434"
timeout = 900
```

The notes' text goes to that machine, so email is kept off it (and `[llm.private]` must stay on this one). `sb init --base-url` writes the same and warns; `sb doctor` keeps a `WARN server summarize` line.

### Different models for different jobs

```toml
[llm.summarize]            # reads each chunk: many cheap calls
model = "ollama/llama3.2:latest"
max_tokens = 1200

[llm.synthesize]           # writes the note: a few calls
model = "claude-cli/default"
fallback = "ollama/llama3.2:latest"

[llm.ask]
model = "ollama/qwen3:4b"
```

### Images and scanned PDFs (OCR)

```toml
[llm.ocr]
model = "ollama/qwen3-vl:2b-instruct"
timeout = 600
```

`sb init --ocr` writes it. Run `ollama pull qwen3-vl:2b-instruct` once (1.9 GB). The model must run on this machine; another provider, another host, a `-cloud` model or a `fallback` is refused. See [Choosing the OCR model](../how-to/models.md#choosing-the-ocr-model).

### Search by meaning (embeddings)

```toml
[llm.embed]
model = "ollama/nomic-embed-text"
timeout = 60
```

Run `ollama pull nomic-embed-text` once (about 270 MB). Pages are embedded once, by section, in `.esbi/index.sqlite3`, and again only when they change. With the section absent, or the embedder unreachable, search is exactly the keyword search. Email is never sent to an embedder that is not on this machine. Details and measurements: [Hybrid retrieval](../explanation/rag-fit.md#hybrid-retrieval-built-m20).

### Without Obsidian

```toml
[notes]
viewer = "none"
```

See [Use it without Obsidian](../how-to/without-obsidian.md).
