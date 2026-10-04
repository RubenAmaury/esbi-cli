# Update and uninstall

## Update

Read the [changelog](https://github.com/RubenAmaury/esbi-cli/blob/main/CHANGELOG.md) first: while the major version is 0, a minor version (0.4 to 0.5) may change a command or the config format, and it says so.

| Installed with | Update |
|---|---|
| Homebrew | `brew update`, then `brew upgrade esbi-cli` |
| `uv tool install git+...` | `uv tool upgrade esbi-cli` |
| A wheel | Download the new wheel, then `uv tool install --force ~/Downloads/esbi_cli-X.Y.Z-py3-none-any.whl` |
| A source checkout | `git pull` in the folder; the change is live at once. After a new dependency, `uv tool install --editable . --force` |

For a `uv` install the command prints what changed and ends with `Nothing to upgrade` when you are already current.

After an update, three commands:

```bash
sb version
```

```bash
sb doctor
```

```bash
sb schedule install
```

- `sb version` shows the new version.
- `sb doctor` shows anything the new version wants different.
- `sb schedule install` (only if you use the nightly job) rewrites the job so it points at the `sb` that is installed now. It is safe to repeat, and it matters because the job remembers where `sb` lives.

Your vault and config are not touched by an update. If a release says its notes have a new format, `sb reingest` rebuilds the old ones; see [Manage the queue and old notes](manage-the-queue.md#rebuild-old-notes). The page index in `.esbi/` is rebuilt by itself when its version changes.

## Uninstall

An uninstall removes the program. It does not touch your notes, and it leaves some small things behind on purpose. Do them in this order.

**1. Remove the nightly job** (macOS), while `sb` still exists:

```bash
sb schedule uninstall
```

```
Removed.
```

**2. Remove the program:**

```bash
brew uninstall esbi-cli
```

```bash
uv tool uninstall esbi-cli
```

Use the one that matches how you installed it. `uv` prints `Uninstalled 1 executable: sb`. Homebrew keeps the tap; remove it too with `brew untap rubenamaury/esbi-cli`. It also leaves Python 3.13, which other programs may use.

**3. Decide what to do with what is left behind.**

| Left behind | Where | Remove it with |
|---|---|---|
| Your vault, and its history | The folder you chose, for example `~/Documents/Obsidian/esbi` | Keep it: it is plain Markdown. To delete it, delete the folder |
| The worker's state | `<vault>/.esbi/` (queue, page index, logs); disposable | Goes with the vault. Delete the folder to start the queue afresh |
| The config file | `~/.config/esbi-cli/config.toml` | `rm ~/.config/esbi-cli/config.toml` |
| The nightly job, if you forgot step 1 | `~/Library/LaunchAgents/com.esbi-cli.nightly.plist` | `launchctl bootout gui/$(id -u)/com.esbi-cli.nightly`, then delete the file |
| The mailbox password | The macOS Keychain, service `esbi-cli-imap` | `security delete-generic-password -s esbi-cli-imap -a you@gmail.com` |
| The Gmail side of email capture | The `esbi-cli` label, its filter, the app password | Delete the label and filter in Gmail, and revoke the app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| The models | Ollama's store | `ollama rm llama3.2` (and any other you pulled) |
| The Web Clipper setup | Your browser, and Obsidian | Remove the extension and the two templates in its settings |
| The backup | Your git remote | Delete the repository there |

**Deleting the vault deletes your notes.** The notes and the originals in `raw/` live only in the vault (and its backup, if you made one). Everything else on this list is safe to delete.
