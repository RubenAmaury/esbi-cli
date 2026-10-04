# Back up and restore your vault

The vault is a plain folder of Markdown files. You never need GitHub, and you do not need git at all. This page covers backing up with and without git, restoring, and what is not in the vault.

## What to back up

| What | Where | Back it up? |
|---|---|---|
| The notes and the originals | The vault folder: `wiki/`, `raw/`, `attachments/`, `index.md`, `log.md`, `Home.md` | Yes. `raw/` holds the only copy of what you saved |
| Your own files in the vault | `inbox/` (until scanned), `.obsidian/` (Obsidian's settings) | Yes, if you changed them. The worker's git history does **not** include them. `SCHEMA.md` is versioned, see below |
| Your questions for `sb eval` | `<vault>/.esbi/golden.jsonl` | Versioned with the vault when git is on (see below); otherwise yes, back it up |
| Benchmark reports | `<vault>/.esbi/bench/` | No: `sb bench` can make them again |
| The settings | `~/.config/esbi-cli/config.toml` | Yes: it is outside the vault |
| The mailbox password | The macOS Keychain | No: store it again after a restore |
| The queue, the page index, run history, logs | `<vault>/.esbi/` | No: the page index is rebuilt; the queue only remembers what was done |

If you back up the whole vault folder with a normal backup tool (Time Machine, a copy to a drive), you get everything in the second and third rows too. That is the simplest way and it needs no git.

## With git (recommended, optional)

If `git` is installed, `sb init` makes the vault a repository and every ingested source becomes one commit: you can read what changed, and undo it.

```bash
git -C ~/Documents/Obsidian/esbi log --oneline
```

```
83a0b9d index: 2026-10-03
1f1eec2 ingest: Spaced Repetition y Note-Taking
efab0eb ingest: Zettelkasten
```

To undo a change, `git -C <vault> reset --hard <commit>`. `sb reingest` relies on this and refuses to run without it.

The worker commits only these paths: `wiki/`, `raw/`, `attachments/`, `index.md`, `log.md`, `Home.md`, and two files that are yours but that you would hate to lose, `SCHEMA.md` and `.esbi/golden.jsonl` (your `sb eval` questions). It never commits anything else of yours (`inbox/`, `.obsidian/`, `.gitignore`), and the rest of the state folder `.esbi/` (the queue, the index, logs) stays ignored. The vault's `.gitignore` says so with two lines, `.esbi/*` and `!.esbi/golden.jsonl`. A vault made by an older version, whose `.gitignore` has `.esbi/`, is upgraded to them the first time the worker commits (the change in `.gitignore` itself is left uncommitted, as the file is yours).

If your own ignore rules hide one of these paths (for example a `SCHEMA.md` line in `.gitignore`), the worker skips that path and commits the rest.

A **backup** is one more step: give the repository a remote. Any git remote works: a private repository on GitHub or GitLab, or a bare repository on a NAS, a USB drive or another computer.

```bash
sb init --remote git@example.com:you/vault.git
```

or answer the remote question when you run `sb init`. After each index refresh (every `sb run`, `sb index` and `sb reingest`) the vault is pushed there. A failed push is a warning (`warning: vault backup not pushed: ...`), never a failed run. Use a **private** repository: notes made from email are in the vault ([Safety and privacy](../explanation/safety-and-privacy.md)).

## Without git

Everything else works: ingest, the queue, the index, `sb ask`, the nightly job, `sb export`. `sb init` says the vault has no history, and `sb doctor` shows `vault history: off`. Back the folder up the way you back up your documents: Time Machine, iCloud Drive, Dropbox, a copy to an external disk. `sb reingest` asks for git because its undo depends on it.

To turn history on later, install git (on macOS: `xcode-select --install`, or `brew install git`) and run `sb init` again: it only creates what is missing.

## Restore

### From a folder or disk backup

Copy the vault folder back where you want it, copy `config.toml` to `~/.config/esbi-cli/` (if the vault is at a new path, change `vault` in it), and check:

```bash
sb doctor
```

### From a git remote

Clone the remote into the place the vault should live:

```bash
git clone git@example.com:you/vault.git ~/Documents/Obsidian/esbi
```

The clone has your notes, your originals, `SCHEMA.md` and your golden questions, but not the files the worker never commits (`inbox/`, `.gitignore`, the rest of the state folder). `sb init` makes them again and writes a config if there is none; it never overwrites anything that exists:

```bash
sb init --vault ~/Documents/Obsidian/esbi
```

```
Vault ~/Documents/Obsidian/esbi: inbox/, .gitignore
Config ~/.config/esbi-cli/config.toml: written
```

Then check, and look at the restored wiki:

```bash
sb doctor
```

What a restore from git loses, and what it costs:

- The queue is empty. Sources you had queued but not processed need adding again; sources already processed are in the wiki, and `sb add` of one says `already in the wiki as [[...]]`.
- The page index and the run history are rebuilt as you go.
- Your `SCHEMA.md` and `.esbi/golden.jsonl` come back with the clone, as of the last commit. A vault whose history began before the worker committed them has no copy of them in it: restore those from wherever you kept them.
- If you use email: `sb email set-password` again.

### Undo a bad change without restoring

A wrong `sb reingest`: `git -C <vault> reset --hard pre-reingest-<date>` (the tag it printed). A wrong ingest: find its commit with `git log` and reset to the commit before it. A note you deleted by mistake: if no run has happened since, `git -C <vault> checkout -- "wiki/sources/Title.md"` brings it back; otherwise the deletion is already committed, so find it with `git -C <vault> log --diff-filter=D --oneline -- "wiki/sources/Title.md"` and restore it from the commit before: `git -C <vault> checkout <commit>^ -- "wiki/sources/Title.md"`.

## Move to a new Mac

See [Move to a new Mac](move-to-a-new-mac.md).
