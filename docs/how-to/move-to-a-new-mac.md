# Move to a new Mac

Moving takes four things: the program, a model, your vault, and your settings. The vault and the config are plain files, so this is a copy and a check. Work through it in order.

## On the old Mac

### 1. Stop the nightly job

So two Macs do not work on one vault at once:

```bash
sb schedule uninstall
```

### 2. Make sure the vault is current

Run `sb index`: it commits, and pushes if you have a remote.

### 3. Copy these

To a drive, a cloud folder or the git remote:

| What | Where |
|---|---|
| The whole vault folder | The `vault` path in your config, for example `~/Documents/Obsidian/esbi` |
| The config file | `~/.config/esbi-cli/config.toml` (`sb info` prints its path) |
| Your golden questions, if any | `<vault>/.esbi/golden.jsonl`: inside the vault folder, so it comes with it if you copy the folder |

With a git remote the notes, `SCHEMA.md` and your golden questions travel through it, but your other own files (`inbox/`, `.obsidian/`) do not: copy the whole folder, or read [Back up and restore](backup.md#from-a-git-remote).

### 4. Email only

Note the Gmail address. You will store the app password again; it stays in the Keychain and is not copied.

## On the new Mac

### 1. Install the program

See [Install](install.md).

### 2. Get a model

For a local model, install Ollama and pull the same models (`ollama list` on the old Mac shows which): [Install Ollama and a model](models.md#install-ollama-and-a-model). For your subscription: `claude auth login`.

### 3. Copy the vault and the config

Put the vault in the same place (or any place) and the config at `~/.config/esbi-cli/config.toml`. If the vault's path is different, edit `vault` in the config.

### 4. Check everything

```bash
sb doctor
```

Fix what it says: a model to pull, a login, the Obsidian vault to open (*Open folder as vault*).

### 5. Email only

```bash
sb email set-password
```

Then `sb email fetch` to test.

### 6. Install the nightly job

```bash
sb schedule install
```

Allow Documents access when macOS asks ([Run it every night](nightly-job.md#first-run-macos-asks-for-permission)).

### 7. Web Clipper only

Install the extension again and import the templates with `sb setup clipper`: they are not stored in the vault.

## What does not move

- **The queue.** It lives in `<vault>/.esbi/` and comes along if you copy the folder. If you moved through git it is gone: sources not yet processed need adding again.
- **The Keychain password.** Store it again.
- **Ollama's models.** Pull them again.
- **launchd's job.** Install it again on the new Mac.

Do not run the nightly job on both Macs against a vault in a synced folder at the same time: the run lock is a file lock on one machine, so it cannot protect two.
