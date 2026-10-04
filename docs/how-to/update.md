# Update esbi-cli

How you find out that a new version exists, and how to install it. Nothing updates by itself: you see a line, you run `sb update`, and it asks before it does anything.

## How you learn there is a new version

Three places tell you, and none of them slows a command down:

- **A line after a command.** When you run a command in a terminal and a newer release is known, one line appears at the end, on stderr (so a pipe is not affected):

  ```
  esbi-cli 0.2.0 is available (you have 0.1.0). Update with: sb update
  ```

  It never appears after `sb run` (the nightly job), `sb schedule`, `sb update`, `sb setup`, `sb init`, `sb version` or `sb doctor`, when the output goes to a file or a script instead of a terminal, or after a command that failed.
- **`sb doctor`** has a `version` line: `ok   version: 0.1.0 (latest)`, or `WARN version: 0.2.0 is available, run `sb update``.
- **`sb version --check`** asks right now and prints the installed and the latest version. A plain `sb version` stays offline and instant.

The check asks GitHub at most once a day, remembers the answer in `~/.cache/esbi-cli/update.json` (`$XDG_CACHE_HOME/esbi-cli` if you set it), and after a failure waits an hour before it tries again, so being offline costs nothing. It gives up after 5 seconds.

## Update with `sb update`

```bash
sb update
```

```
installed: 0.1.0
latest:    0.2.0
method:    brew
Will run: brew upgrade rubenamaury/esbi-cli/esbi-cli
Run it now? [y/N]
```

It works out how esbi-cli was installed, shows the exact command and waits for a `y`. The command runs as it is shown, with no shell in between, and its output appears as it comes. When it ends successfully:

```
Updated. Run `sb version` to confirm.
```

| Option | Meaning |
|---|---|
| `--dry-run` | Only print the command |
| `--yes`, `-y` | Do not ask (for a script). Without a terminal and without `--yes`, `sb update` refuses and runs nothing |

Read the [changelog](https://github.com/RubenAmaury/esbi-cli/blob/main/CHANGELOG.md) first when the minor version changes: while the major version is 0, it may change a command or the config format, and it says so.

### What it runs for each install method

| Installed with | `sb update` runs |
|---|---|
| Homebrew | `brew upgrade rubenamaury/esbi-cli/esbi-cli` |
| `uv tool install git+...` | `uv tool upgrade esbi-cli` |
| `pipx` | `pipx upgrade esbi-cli` |
| `pip` in a virtual environment | `python -m pip install --upgrade <the release's archive on GitHub>`, using the Python that runs `sb` |
| A source checkout | Nothing: it says `git pull`, then `uv sync` |
| A `uv` tool pinned to a git tag or a wheel | Nothing: `uv tool upgrade` cannot move a pinned install, so it prints the reinstall command to run |
| Something it does not recognise | Nothing: it lists the commands above |

## By hand

The same updates without `sb update`:

```bash
brew upgrade rubenamaury/esbi-cli/esbi-cli
```

```bash
uv tool upgrade esbi-cli
```

```bash
pipx upgrade esbi-cli
```

A wheel from a [GitHub release](https://github.com/RubenAmaury/esbi-cli/releases): download the new one, then `uv tool install --force ~/Downloads/esbi_cli-X.Y.Z-py3-none-any.whl`. A source checkout: `git pull`, then `uv sync` (or `uv tool install --editable . --force` after a new dependency).

Afterwards, `sb version` shows the new version and `sb doctor` shows anything the new version wants different. Your vault and config are not touched.

## The nightly job keeps working

On macOS the nightly job is a launchd agent that remembers where `sb` lives. Homebrew keeps each version in its own folder (`.../Cellar/esbi-cli/0.1.0/...`) and deletes the old one on an upgrade, so a job that pointed there would stop. `sb schedule install` now writes the stable path Homebrew keeps pointing at the current version (`.../opt/esbi-cli/libexec`), and an upgrade needs nothing more.

If you installed the job with an older version, `sb doctor` shows `WARN nightly job: points into a versioned Homebrew folder`. Run `sb schedule install` once to fix it; it is safe to repeat.

## Turn the check off

In `config.toml`:

```toml
[update]
check = false
```

Or, in your shell profile, `export ESBI_NO_UPDATE_CHECK=1`, which wins over the config. Then no line appears, `sb doctor` says `(update check is off)`, and nothing asks GitHub. `sb update` and `sb version --check` still do, because you asked them to.

## What the check sends

One anonymous HTTPS `GET` to `https://api.github.com/repos/RubenAmaury/esbi-cli/releases/latest`, with a `User-Agent` that names esbi-cli and its version. No vault data, no config, no identifier of you or your machine. GitHub sees your IP address, as any website does. The answer is read as untrusted text: only the version tag and the release page address are used, and only when they have the expected shape. The scheduled run never checks. More on what leaves your machine: [Safety and privacy](../explanation/safety-and-privacy.md#what-leaves-your-machine).

To remove the program, see [Update and uninstall](update-and-uninstall.md#uninstall).
