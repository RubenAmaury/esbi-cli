# Install

Pick one route. They install the same program; every command after this page is identical. If you are new, the [getting started](../tutorials/getting-started.md) tutorial uses this page and then goes on to a first note.

| Route | Command |
|---|---|
| [Homebrew (macOS)](#homebrew-macos) | `brew install rubenamaury/esbi-cli/esbi-cli` |
| [`uv` from git](#uv-macos-and-linux) | `uv tool install git+https://github.com/RubenAmaury/esbi-cli` |
| [A built wheel](#a-built-wheel) | `uv tool install esbi_cli-0.1.0-py3-none-any.whl` |
| [From a source checkout](#from-a-source-checkout) | `uv tool install --editable .` |
| [Linux](#linux) | The `uv` route, plus git and a cron line |

You need Python 3.12 or later, which Homebrew and `uv` install for you, and `git` if you want version history (optional).

## Homebrew (macOS)

```bash
brew install rubenamaury/esbi-cli/esbi-cli
```

This adds the project's tap, installs Python 3.13 and `sb`. Check it:

```bash
sb version
```

The caveats Homebrew prints at the end tell you the next commands: `sb init`, `sb doctor`, `sb schedule install`, and `brew install ollama` for local models.

## `uv`, macOS and Linux

[`uv`](https://docs.astral.sh/uv/) installs command-line tools into their own environments. If you do not have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal, then:

```bash
uv tool install git+https://github.com/RubenAmaury/esbi-cli
```

It ends with:

```
Installed 1 executable: sb
```

```bash
sb version
```

```
0.1.0
```

## A built wheel

Every [GitHub release](https://github.com/RubenAmaury/esbi-cli/releases) has a wheel attached (`esbi_cli-X.Y.Z-py3-none-any.whl`; note the underscore). Download it, then:

```bash
uv tool install ~/Downloads/esbi_cli-0.1.0-py3-none-any.whl
```

You can build one yourself from a checkout with `uv build` (the wheel appears in `dist/`).

## From a source checkout

For development, or to run the latest code. Changes to the code take effect at once.

```bash
git clone https://github.com/RubenAmaury/esbi-cli
```

Then, inside the folder:

```bash
uv tool install --editable .
```

If you develop with `uv sync` and the folder lives in an iCloud-synced location such as `~/Documents`, see [Troubleshooting](troubleshooting.md#the-package-cannot-be-imported-macos-hidden-files); [CONTRIBUTING](https://github.com/RubenAmaury/esbi-cli/blob/main/CONTRIBUTING.md) covers the development setup.

## Linux

Linux works with the same program, but it is less tested than macOS. What differs:

1. Install `uv` and `git` with your package manager and the line above, then use the `uv` route.
2. Install [Ollama](https://ollama.com/download) (or use your Claude subscription or an API key). On most distributions the Ollama installer starts it as a service; check with `curl http://localhost:11434`.
3. There is no launchd. `sb init --nightly 03:00` prints a cron line instead, and [Run it every night](nightly-job.md#linux-and-other-systems-cron) explains it.
4. There is no Keychain. Email capture stores the app password with the `keyring` library, which on Linux needs a working secret service (GNOME Keyring or KWallet). Email capture on Linux is untested.
5. `sb today` cannot open Obsidian links without an `open` command; set `viewer = "none"` and open the printed path yourself, or use Obsidian directly.

## If `sb` is not found

`sb: command not found` means the folder `uv` puts tools in is not on your `PATH`. `uv` printed a warning when it installed; the fix is:

```bash
uv tool update-shell
```

Then open a new terminal. `sb doctor` prints a `WARN global install` line with the same cause. Homebrew puts `sb` in `/opt/homebrew/bin`, which is on the `PATH` of a normal Homebrew install.

## What an installed copy needs

Nothing from a source checkout: the starter configuration, the schema, the setup wizards and the Web Clipper templates are inside the package.

## Next

```bash
sb init
```

then `sb doctor`. The walk-through is [Getting started](../tutorials/getting-started.md#step-4-run-sb-init); the way to a model is [Choose how the notes are written](models.md). To remove it, see [Update and uninstall](update-and-uninstall.md).

## Updates

Once a day esbi-cli asks GitHub whether a newer release exists, and a command run in a terminal prints one line when there is one. Nothing installs by itself: `sb update` shows the command for the way you installed it and asks first. [Update esbi-cli](update.md) explains it, and how to turn the check off (`[update] check = false`).
