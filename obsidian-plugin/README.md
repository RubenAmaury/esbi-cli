# esbi-cli for Obsidian

A thin, desktop-only plugin that drives the [esbi-cli](https://github.com/RubenAmaury/esbi-cli) command line tool (`sb`) from inside Obsidian. esbi-cli turns the links, PDFs and emails you save into a wiki of Markdown notes in your vault; this plugin adds buttons for the things you do every day.

**This plugin does nothing without esbi-cli.** It does not contain the worker, it does not install it, and it never talks to a model. Everything goes through the `sb` program on your computer.

## What you can do

All commands are in the command palette (type "esbi-cli"):

| Command | What it does |
| --- | --- |
| Add the selected link or this note's source to the queue | Runs `sb add`. Takes the selected link (a bare URL, `<url>` or `[text](url)`); with nothing selected it takes the note's `source` property. Only web links (http, https) are sent, and only the URL, never the text of the note. |
| Run the queue | Runs `sb run` and shows live progress: which source, which step (for example "chunk 2/6"), what was added and what failed. **Cancel** stops it (see "Cancelling" below). Closing the window does not stop the run; the status bar keeps showing it and clicking it brings the window back. |
| Ask your wiki | Asks a question with `sb ask`. The answer is shown with the pages it used as links to your notes. Only pages that exist in this vault are links. |
| Open today's index | Opens `wiki/daily/YYYY-MM-DD.md` with Obsidian itself (no program is run). |
| Check setup | Runs `sb doctor` and lists every check with its fix. |

The status bar shows the queue ("esbi: 3 queued, 1 failed", or "esbi: running 2/5"). It refreshes every 60 seconds by default (never faster than 30) and after each command. Clicking it opens the queue window.

## Requirements

- Obsidian 1.8.7 or later on **macOS or Linux**, desktop. It is marked desktop-only because it starts a program; it does not load on mobile. Windows is not supported (esbi-cli itself does not support it yet).
- esbi-cli installed, in a version that has `--json` output ("contract" 1). **Test connection** in the plugin settings tells you.

Install esbi-cli yourself, in a terminal (the plugin never installs or updates it):

```bash
brew install rubenamaury/esbi-cli/esbi-cli                  # macOS (Homebrew)
uv tool install git+https://github.com/RubenAmaury/esbi-cli   # any system with uv
```

Then set it up as described in the [esbi-cli documentation](https://rubenamaury.github.io/esbi-cli/).

## Install the plugin

Not yet in the community plugin directory.

- **BRAT** (recommended while it is in testing): install the BRAT plugin, choose "Add beta plugin" and enter the repository that holds this plugin's release.
- **By hand**: download `main.js`, `manifest.json` and `styles.css` from a release, put them in `<your vault>/.obsidian/plugins/esbi/` and turn the plugin on in **Settings, Community plugins**.

## Settings

- **Path to the sb command.** Found automatically the first time (see "How sb is found"). Stored on this device only, because it is different on every computer; it does not travel with the vault when the vault is synced.
- **Config file** (optional). Passed to `sb` as `--config`. Leave empty to use the one `sb` finds by itself. Stored on this device only.
- **Status bar refresh.** 30 seconds or more.
- **Test connection.** Runs `sb version --json` and shows the version and the contract number, and warns if `sb` is set up for a different vault than the one open in Obsidian.

When `sb` is missing, or speaks a newer contract than the plugin understands, you get one notice that says what to do. The plugin does not crash.

## How sb is found, and why a login shell

Obsidian started from the Dock or Finder has a minimal `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`), so `sb` (usually in `~/.local/bin` or `/opt/homebrew/bin`) is not found by a plain program start, and the tools `sb` itself uses are not found either. The plugin therefore starts `sb` through your **login shell**: `/bin/zsh -lc` on macOS, `/bin/sh -lc` elsewhere. The command is built from an argument list, never from a string: the shell is told to `exec "$0" "$@"` and receives the path to `sb` and every argument as separate values, so a link or a question containing quotes, `;`, `$(...)` or backticks is only ever text.

To detect `sb`, the plugin asks the login shell (`command -v sb`) and then looks in `~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin`.

## Privacy and disclosures

These are the disclosures Obsidian's developer policies ask for.

- **It runs an external program.** The plugin starts the `sb` command of esbi-cli on your computer (through your login shell). It starts nothing else. It does not download, install or update any program, including `sb`.
- **Network.** The plugin itself makes **no network request** and has no telemetry or analytics. `sb`, the program it starts, uses the network on your behalf: it fetches the web pages you queue and it talks to the language model you chose in esbi-cli (a local one such as Ollama, or a cloud one if you configured that). See the esbi-cli documentation for what is sent where. Email notes are never sent to a model that sends text away; that rule lives in `sb`, which the plugin cannot bypass.
- **Files outside the vault.** The plugin itself reads only your vault through Obsidian's own API (the note's `source` property, the selected text and today's index note) and its own settings. The `sb` program it starts reads esbi-cli's `config.toml` and the files and folders that configuration points to (the vault, the Keychain entry for a mailbox if you set one up, PDFs you queue).
- **What the plugin passes to `sb`.** The URL you chose to queue, the question you typed, and the options above. Never the body of a note.
- **No account, no payment, no ads.** Open source (MIT).
- **Answers are shown without images.** An answer is written by a model from pages you saved; a hostile page could make it contain an image whose address leaks text when Obsidian loads it. The plugin removes images and raw HTML from an answer before showing it. Links in an answer open only when you click them, and only notes that exist in your vault open.
- It does not touch the `.esbi` folder or any file of your vault directly; all changes to your wiki are made by `sb`.

## Cancelling a run

**Cancel** sends the interrupt signal (SIGINT, like Ctrl-C) to `sb run`. If `sb` does not stop within five seconds, the plugin sends SIGTERM. When `sb` confirms it was interrupted, the window says the item in progress was put back in the queue; otherwise it says esbi-cli will recover the item on the next run. Closing Obsidian or turning the plugin off also cancels a running job this way.

## Troubleshooting

- **"esbi-cli is not installed, or the plugin cannot find it."** Install it (above), then press **Test connection**. If it is installed, run `which sb` in a terminal and paste that path into **Path to the sb command**.
- **It works in the terminal but not in the plugin.** A login shell reads `~/.zprofile` (zsh) or `~/.profile`, not `~/.zshrc`. If you add `~/.local/bin` to your `PATH` only in `~/.zshrc`, put the full path to `sb` in the plugin settings, or move the `export PATH=...` line to `~/.zprofile`.
- **"This version of esbi-cli is too old."** It has no `--json` output. Update it (`sb update`).
- **"esbi-cli is newer than this plugin understands."** Update the plugin.
- **"A run is already in progress."** Another `sb run` (for example the nightly one) holds the lock. Try again when it ends.
- **The warning "set up for another vault".** `sb` uses a config file that points to a different vault than the one open. Set **Config file** to the right one.
- **The status bar says "status unavailable".** `sb status` failed; run **Check setup**.
- **Two things write to the vault's git history.** `sb run` commits each batch in the vault; if another plugin (for example Obsidian Git) commits at the same moment, git can report an index lock. Let one of them do the committing.

## Development

```bash
cd obsidian-plugin
npm ci
npm test          # Vitest; no Obsidian needed (a fake `sb` script plays the CLI)
npm run lint
npm run build     # type check, then main.js
```

The tests run the real process helper against `test/fixtures/fake-sb`, a shell script that speaks the `--json` contract (including a slow `run` that honours SIGINT). `child_process` is also mocked in one test file to pin how it is called. The contract itself is defined in esbi-cli; `src/contract.ts` is the plugin's reading of it.

A sample CI workflow is in `ci.example.yml` (not active; copy it to `.github/workflows/` of the repository that releases the plugin).

## Releasing

Update `manifest.json` and `versions.json` with `npm version <x.y.z>`, then publish a GitHub release whose **tag equals the version with no leading `v`** and attach `main.js`, `manifest.json` and `styles.css`. The directory reads `manifest.json` at the root of the repository, so listing it publicly needs a repository whose root is this folder.

## License

MIT, see [LICENSE](LICENSE).
