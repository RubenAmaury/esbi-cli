# Run it every night

A nightly job runs `sb run` for you at a time you choose, so the queue is worked through while you sleep and the morning index is waiting. It is optional: `sb run` by hand does the same.

The job runs `sb run --if-due`. **`--if-due` does real work only once a day, after `nightly_time`** (default `03:00`, set under `[run]`): a run that already happened today makes it print `Not due: the nightly run already happened.` and stop. That is why it is safe to ask for it every hour. A run stopped by a model outage does not count as the nightly run, so the next check retries it; manual `sb run`s never count.

Pick your system: [macOS (launchd)](#macos-launchd) or [Linux and other systems (cron)](#linux-and-other-systems-cron).

## macOS (launchd)

Install it once:

```bash
sb schedule install
```

```
Installed ~/Library/LaunchAgents/com.esbi-cli.nightly.plist
Runs every day at 03:00 (or at the next wake). Log: ~/Documents/Obsidian/esbi/.esbi/logs/nightly.log
```

(Or answer yes to the nightly question in `sb init`, or run `sb init --nightly 03:00` on a new config.) Check it:

```bash
sb schedule status
```

```
installed: yes
loaded: yes
```

What it installs is a launchd agent that runs `sb run --if-due` at the time you set, at login, and every hour as a safety net. If the Mac is asleep at the set time, launchd starts the job at the next wake (unlike cron, which skips it). The run is wrapped in `caffeinate -i`, so the Mac cannot idle-sleep in the middle of it. The hourly timer alone would not be enough, because launchd drops interval ticks that fall while the Mac sleeps.

### First run: macOS asks for permission

The job reads `~/Documents` (your vault, the config). macOS's privacy protection shows a dialog the first time, like "Python would like to access files in your Documents folder". Click **Allow**. Until you do, the job waits silently and looks "running" forever. If you missed the dialog: System Settings, Privacy & Security, Files & Folders (or Full Disk Access), enable the Python framework (`/Library/Frameworks/Python.framework/.../Python.app`), then restart the job:

```bash
launchctl kickstart -k gui/$(id -u)/com.esbi-cli.nightly
```

An agent or script cannot click that dialog for you.

### Choose the time

Set `nightly_time = "HH:MM"` (24 hours) under `[run]` in `config.toml`, then install again so launchd is set for the new time:

```bash
sb schedule install
```

The due check follows the config at once, but launchd only fires at the time it was installed for. `sb doctor` warns when the two differ:

```
  WARN nightly job: installed for 03:00 but config.toml says 04:30
         fix: sb schedule install
```

### Wake the Mac for it

The Mac only works while awake. To have it awake for the run, wake it at the same time or a minute later. For 04:30:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 04:30:00
```

It needs `sudo`, so it is yours to run. Never wake it earlier than `nightly_time`: a run is only due from that moment, so an earlier wake finds nothing to do and the Mac goes back to sleep. Check it with `pmset -g sched`. Ollama must also be running (the Homebrew service starts it at login).

### Check that it works

```bash
sb doctor
```

```
  ok   last run: 2026-10-03 03:00: 2 ingested, 0 failed
  ok   nightly job: installed and loaded, runs at 03:00
```

- `WARN last run: no scheduled run yet`: the job has not run since you installed it.
- `WARN last run: ...; the model was unreachable`: the last attempt stopped because the model was down; the hourly check retries.
- The log is `<vault>/.esbi/logs/nightly.log`; it is trimmed by itself. A healthy hourly check ends in `Not due: the nightly run already happened.`
- Every run, manual or scheduled, is listed under **Ejecuciones** in the daily note.
- `launchctl print gui/$(id -u)/com.esbi-cli.nightly | grep -E "state|last exit"` shows launchd's own view.

### Remove it

```bash
sb schedule uninstall
```

```
Removed.
```

### After you update or move `sb`

The job remembers where `sb` lives and which config it uses. After updating, reinstalling or moving `sb`, or moving the config, run `sb schedule install` again.

## Linux and other systems (cron)

There is no launchd, so use cron (or any scheduler that can run a command every hour). `sb init --nightly 03:00` prints the line to use, and so do `sb schedule install`, `status` and `uninstall`, which stop with exit code 1 and `error: the nightly job uses launchd, which only macOS has` when there is no `launchctl`:

```
Nightly job: this system has no launchd. Add this to cron (hourly is fine, it runs once a day):
  0 * * * * sb run --if-due --config /home/you/.config/esbi-cli/config.toml
```

Add it with:

```bash
crontab -e
```

Two details that cron needs and a terminal does not:

1. **Use the full path of `sb`.** cron has a minimal `PATH`. Find it with `command -v sb` (for example `/home/you/.local/bin/sb`) and write that.
2. **Give it what the model needs.** For Ollama running as a service there is nothing to add. For your subscription, `claude` must be on cron's `PATH`; for an API key, the key must be set in the crontab (a variable line above the job), which stores it in plain text.

A full line, with a log:

```
0 * * * * /home/you/.local/bin/sb run --if-due --config /home/you/.config/esbi-cli/config.toml >> /home/you/esbi-cli.log 2>&1
```

Hourly is intentional: `--if-due` means only the first check after `nightly_time` does the work, and if the machine was off at 03:00 the first check after it comes back does it. `nightly_time` still decides when a run counts as due. Cron on Linux is less tested than launchd on macOS.

## Does the job need my machine to be on?

Yes: it runs on your machine, with your models. With a subscription or an API the model is elsewhere, but the worker still runs here. See [Use it offline](use-offline.md) for what works without a network.
