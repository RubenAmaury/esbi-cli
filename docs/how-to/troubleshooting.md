# Troubleshooting

Find your symptom, read the message exactly as it appears, and follow the fix. Start with the command that checks everything:

```bash
sb doctor
```

Each line says `ok`, `WARN` or `FAIL`, and what to do under anything that is not fine. Most problems on this page show up there first. If yours is not here, [open an issue](https://github.com/RubenAmaury/esbi-cli/issues) and paste the output of `sb doctor` (it contains no secrets).

On this page: [install and start](#install-and-start), [the model](#the-model), [sources](#sources), [asking](#asking), [the nightly job](#the-nightly-job), [mail](#mail), [git and backup](#git-and-backup).

## Install and start

### sb is not found

```
sb: command not found
```

The folder that holds `sb` is not on your `PATH`. With `uv`, run `uv tool update-shell` and open a new terminal. `sb doctor` shows `WARN global install: sb is not on your PATH` for the same reason. See [Install](install.md#if-sb-is-not-found).

### The package cannot be imported (macOS hidden files)

```
ModuleNotFoundError: No module named 'esbi_cli'
```

This only happens when you run from a source checkout with `uv sync`, and the environment lives in `~/Documents`, where iCloud keeps marking `.venv` files hidden (Python 3.13 then skips them). Keep the environment outside it, for good:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.local/share/venvs/esbi-cli"
```

then `uv sync` again. The quick fix is `chflags -R nohidden .venv`. A normal install with Homebrew or `uv tool install` is not affected.

### No config file is found

```
error: No config.toml found (looked in: ...)
```

`sb doctor` shows `FAIL config`. You have not run `sb init`, or the config is somewhere else. Run `sb init`, or point at the file with `--config PATH` or the `ESBI_CONFIG` variable. `sb info` prints the file in use. A `config.toml` in the current folder is never read, on purpose. If you pass `--config` (or set `ESBI_CONFIG`) with a path that does not exist, the command stops with `error: config file not found: PATH`; only the default places are tried one after the other.

### The config has a mistake

| Message | Fix |
|---|---|
| `error: config.toml needs [paths].vault` | Add `vault = "..."` under `[paths]` |
| `error: [run].nightly_time must look like HH:MM (24 hours), got '25:00'` | Write the time as `"03:00"` |
| `error: [notes].language must be one of: en, es, got 'fr'` | Use a language the program has; to add one, see [Add a language](add-a-language.md) |
| `error: [notes].viewer must be "obsidian" or "none", got ...` | Use one of the two |
| `error: Expected ']' at the end of a table declaration (at line 2, column 7)` | A TOML syntax error: the line and column are in the message |
| `error: [llm.summarize] has an unknown key 'num_ctxx' (did you mean 'num_ctx'?). Valid keys: ...` | A key is misspelled. The message names the section, the key and the valid keys. The same check covers every section |
| `error: [run].max_chunks must be a whole number, got 'ten'` | A value has the wrong type (text where a number goes, `"true"` where `true` goes). Fix the value as the message says |
| `error: config file not found: PATH` | The file given with `--config` (or `ESBI_CONFIG`) does not exist. Check the path |

### The vault is not recognised

```
  FAIL vault: ~/Documents/Obsidian/esbi is not a esbi-cli vault (SCHEMA.md or wiki/ missing)
         fix: fix [paths].vault in config.toml
```

`vault` points at a folder that `sb init` did not make. Fix the path, or run `sb init --vault PATH` to create what is missing. After a restore from git the same message appears until you run `sb init` ([Back up and restore](backup.md#from-a-git-remote)).

### The shell says no matches found

```
zsh: no matches found: https://example.com/post?id=7
```

A link with `?` or `&` must be in quotes: `sb add "https://example.com/post?id=7"`.

## The model

### The model is not reachable

```
The LLM is unreachable (is Ollama running?). Nothing was lost; sources stay queued.
```

```
  FAIL model summarize: Ollama is not reachable at http://localhost:11434
         fix: brew services start ollama (or open the Ollama app)
```

Ollama is not running, or `base_url` is wrong. Start it (`brew services start ollama`, or open the app; on Linux `systemctl start ollama`) and check `curl http://localhost:11434` answers `Ollama is running`. The run stopped and **nothing was counted against your sources**: run `sb run` again. The daily index is still rebuilt after a failed run.

### The model is not installed

```
  FAIL model summarize: ollama/llama3.2:latest is not installed
         fix: ollama pull llama3.2:latest
```

Download it: `ollama pull llama3.2`. `ollama list` shows what you have.

### LM Studio does not answer

```
  FAIL model summarize: LM Studio is not reachable at http://localhost:1234/v1
         fix: open LM Studio, load a model, and start the local server (Developer tab)
```

```
  FAIL model summarize: LM Studio does not serve 'x'
         fix: use one of: qwen2.5-7b-instruct
```

Start the server, and use the identifier `lms ls` shows in `model = "lmstudio/..."`.

### The subscription does not work

| Message | Fix |
|---|---|
| `FAIL model ...: the claude command is not installed` | Install [Claude Code](https://claude.com/code) |
| `FAIL model ...: claude is not logged in` | `claude auth login` |
| `claude: ... Run claude auth login.` (during a run) | Your login expired: `claude auth login` |
| `claude: ...` with a usage-limit message | You spent a usage window of your plan. The run stopped like any model outage, nothing is lost, and the next run resumes. Set a local `fallback` to keep going meanwhile |
| `claude gave no answer within 300s` | A timeout for one source; raise `timeout_seconds` in that `[llm.*]` section |
| `claude returned no JSON (exit 1): ...` | The `claude` tool failed to start; run `claude` by hand to see why |

### An API key is missing

```
  FAIL model summarize: anthropic/claude-sonnet-5-5: $ANTHROPIC_API_KEY is not set
         fix: export ANTHROPIC_API_KEY=...
```

During a run the message is `Environment variable ANTHROPIC_API_KEY is not set`. Set the variable in your shell profile and open a new terminal. A nightly job started by launchd does not read your profile, so for unattended runs prefer a local model or the subscription. A rejected key shows `HTTP 401` in the message.

### The model name is not understood

```
  FAIL model summarize: unknown provider in 'foo/bar'
         fix: use ollama/, lmstudio/, openai/, anthropic/ or claude-cli/
```

Other forms: `Model must look like '<provider>/<name>'`, and `Unknown LLM provider 'x'; use one of [...]`. Write the model as `provider/name`.

### There is no summarize section

```
No [llm.summarize] section in config
```

`[llm.summarize]` is required. Add it ([Configuration](../reference/configuration.md#llmtask)), or run `sb init` for a fresh config.

### The model is too slow, or times out

A line like `.../api/chat gave no answer within 300s` means one chunk or source took longer than `timeout_seconds`. It fails that source, not the run. Options: raise `timeout_seconds`; set `max_tokens` on the model that reads chunks (small models sometimes loop, and the cap turns a 5-minute timeout into seconds); use a smaller `max_source_chars`; or a faster model. Expect 3 to 15 minutes per source with a small local model.

### Notes come out in the wrong language or thin

The model is too small. The worker already retries once when the note comes out in the wrong language, and says `The model answered in the wrong language (wanted English)` when the second try fails too. Try a larger model for `[llm.synthesize]` ([Choose how the notes are written](models.md)) and compare with `sb bench`. Rebuild old notes with `sb reingest`.

## Sources

### A source keeps failing

`sb run` prints one `!` line per failed source with the attempt and the reason; `sb status` shows each parked source and its last error. A source is tried three times (it is `queued` while it is being retried), then parked as `failed` and listed under **To review** in the daily note. Fix the cause, then `sb retry`; or `sb drop` it.

| Last error | What it means and what to do |
|---|---|
| `No readable article content found at URL` | The page is a login wall, mostly scripts, or very short. Clip it with the [Web Clipper](web-clipper.md) |
| `Could not fetch URL: Client error '404 Not Found' ...` | A dead link: `sb drop` it |
| `Could not fetch URL: ...` (a connection error) | No network, or the site is down. `sb retry` later |
| `Could not fetch URL: Cannot resolve HOST: ...` | The name does not exist, or DNS failed |
| `Refused to fetch URL: localhost resolves to a non-public address (127.0.0.1)` | By design, only public addresses are fetched. Save the page as a Markdown file and drop it in `inbox/` |
| `Refused to fetch URL: Only http(s) URLs are fetched, not 'ftp'` | Only `http` and `https` |
| `Refused to fetch URL: The response is larger than 20 MB` or `...: The download took more than 120 s` | Downloads are capped; download the file yourself and add it by path |
| `Refused to fetch URL: Too many redirects (more than N)` | The link loops |
| `PDF has almost no extractable text (scanned?): add an [llm.ocr] model ...` | A scan: turn on [OCR](getting-sources-in.md#images-and-scanned-pdfs-ocr) |
| `PDF has no readable text, even with OCR` | The OCR model found nothing on any page |
| `NAME has no readable text (a photo or a diagram?)` | An image with fewer than 40 characters of text. The worker does not describe pictures. `sb drop` it |
| `The OCR model could not read NAME: ...` | The vision model failed: check `sb doctor` (`model ocr`) |
| `Could not open PDF: ...` / `Could not open NAME as an image: ...` | The file is damaged or not what its extension says |
| `NAME has almost no text (N chars)` | A clip with under 40 characters of text |
| `Unsupported file type: .docx` | Only `.pdf`, `.md` and images (with OCR) are read; convert it |
| `the run died while reading this` | The process was killed while reading this source three times in a row (a huge PDF running out of memory). Try a smaller file |

### Another run is in progress

```
Another run is in progress; skipping.
```

Another `sb run` (or the nightly job, or `sb reingest`) holds the lock. It ends by itself, and the lock is released even after a crash. `sb run` exits 0 here; `sb reingest` says `Another run is in progress; try again when it finishes.` and exits 1.

### Files in inbox are not read

```
Not read, esbi-cli cannot read these files in inbox/: letter.docx, slide.png
  Images: add an [llm.ocr] model to config.toml to read images and scanned PDFs (`sb init --ocr`, docs/reference/configuration.md)
```

Those files stay in `inbox/` and are listed on every scan. Images need OCR; HEIC, Word and other types are not supported: convert them to JPG, PDF or Markdown.

### A source says it is already in the wiki

```
Already in the vault as [[Zettelkasten]] (use --force to redo).
```

Not an error: the same URL or the same text is already a note. See [If a source already exists](getting-sources-in.md#if-a-source-already-exists). `sb add` says `Skipped URL: already in the wiki as [[...]]`.

### An email is refused

```
an email cannot be written by a model that sends text away: add a local model as [llm.private] in config.toml
```

You have a cloud model and no local `[llm.private]`. Add it ([Keep email local](email.md#keep-email-local)). The related `[llm.private] must be a model that runs on this machine, not one that sends text away` means your private model is remote.

## Asking

### sb ask finds nothing but you expect an answer

```
No encuentro nada sobre esto en la wiki.
```

The model cited no page that exists, so the answer was refused rather than guessed. Try the words your notes use; turn on `rewrite_questions` or [search by meaning](ask-your-wiki.md#search-by-meaning); measure with `sb eval`. A different model in `[llm.ask]` can help (`qwen3:4b` cites the right page more often than `llama3.2`, but is about ten times slower).

### Embeddings are unavailable

```
warning: embeddings unavailable (...); searching by keyword only
```

`[llm.embed]` is set but Ollama cannot be reached or the model is not pulled (`ollama pull nomic-embed-text`). Search falls back to keywords; nothing breaks.

### Ticks are not registered

Run `sb index` after ticking. The tick must be `- [x] [[Source title]]` on the line of the source, in a daily note under `wiki/daily/`. A source that is already `read` stays read. See [Read your notes](read-your-notes.md#tick-what-you-have-read).

## The nightly job

### The job stays running and never finishes

The log shows `getcwd: Operation not permitted`, or nothing at all. macOS privacy is waiting for, or has denied, access to `~/Documents`. Click **Allow** on the dialog, or enable the Python framework under System Settings, Privacy & Security, Files & Folders. Then:

```bash
launchctl kickstart -k gui/$(id -u)/com.esbi-cli.nightly
```

An agent cannot click that dialog for you. See [Run it every night](nightly-job.md#first-run-macos-asks-for-permission).

### sb doctor complains about the job

| Line | Meaning and fix |
|---|---|
| `WARN nightly job: not installed` | `sb schedule install` |
| `WARN nightly job: installed for 03:00 but config.toml says 04:30` | Install again for the new time: `sb schedule install` |
| `WARN nightly job: launchd is not available here` | Not macOS: use [cron](nightly-job.md#linux-and-other-systems-cron) |
| `error: the nightly job uses launchd, which only macOS has` | You ran `sb schedule ...` on Linux. The message includes the cron line to add with `crontab -e`; see [cron](nightly-job.md#linux-and-other-systems-cron) |
| `WARN last run: no scheduled run yet` | The job has not run since you installed it |
| `WARN last run: ...; the model was unreachable` | The last attempt stopped because the model was down; the hourly check retries |
| `error: no .../bin/sb (run uv sync if this is a checkout)` | `schedule install` could not find `sb` in the running environment: reinstall it |

Nothing happened overnight? Read `<vault>/.esbi/logs/nightly.log`. `Not due: the nightly run already happened.` is normal for the hourly checks.

## Mail

Messages from email capture, with fixes, are in [Capture email](email.md#when-something-goes-wrong).

## Git and backup

| Message | Meaning and fix |
|---|---|
| `warning: git commit failed: ...` | A commit failed (a git identity not set, a lock). The notes are written; fix git (`git config user.name`, `user.email`) and the next run commits |
| `warning: vault backup not pushed: ...` | The remote cannot be reached or refused the push. The run is fine; fix the remote (`git -C VAULT remote -v`) |
| `error: reingest rewrites every note and relies on the vault's git history to undo it; install git and run sb init first.` | `sb reingest` needs a git history: install git and run `sb init` |
| `History: git is not installed, so the vault has no version history.` | Optional. Install git and run `sb init` again |
| `error: ... is not an export of this wiki and has other files: not touching it` | `sb export --out` pointed at a folder that is not an export; pick an empty one |
