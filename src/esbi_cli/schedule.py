"""launchd integration: `sb run --if-due` at the chosen time (or the next wake), at login, and hourly as a retry net."""

import plistlib
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

LABEL = "com.esbi-cli.nightly"
OLD_LABEL = "com.secondbrain.nightly"  # legacy: the name before esbi-cli
CHECK_EVERY_SECONDS = 3600

Launchctl = Callable[[list[str]], subprocess.CompletedProcess]


class ScheduleError(RuntimeError):
    pass


def run_launchctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def stable_prefix(prefix: Path) -> Path:
    """Under Homebrew the environment lives in `<brew prefix>/Cellar/esbi-cli/<version>/libexec`, a
    folder `brew upgrade` deletes. `<brew prefix>/opt/esbi-cli` is a symlink brew keeps pointing at
    the current version: that is the path a long-lived job must use. Any other prefix is unchanged."""
    parts = prefix.parts
    for i in range(len(parts) - 2):
        if parts[i : i + 2] == ("Cellar", "esbi-cli"):
            return Path(*parts[:i], "opt", "esbi-cli", *parts[i + 3 :])
    return prefix


def render_plist(config: Path, log_dir: Path, venv: Path, at: tuple[int, int] = (3, 0)) -> bytes:
    """`venv` is the environment that runs `sb`; it need not live inside the repo. `at` is the
    time of day, (hour, minute), the nightly job runs."""
    venv = stable_prefix(venv)
    command = (
        # macOS sometimes flags the venv as hidden, and Python 3.13 then ignores its .pth files
        f"chflags -R nohidden {shlex.quote(str(venv))} 2>/dev/null; "
        f"exec /usr/bin/caffeinate -i {shlex.quote(str(venv / 'bin' / 'sb'))} run --if-due "
        f"--config {shlex.quote(str(config))}"
    )
    log = str(log_dir / "nightly.log")
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": ["/bin/bash", "-c", command],
            # Not the repo: it usually lives in ~/Documents, and macOS privacy (TCC) then blocks the
            # job at start-up. Everything the job needs is passed as an absolute path.
            "WorkingDirectory": str(Path.home()),
            "StartInterval": CHECK_EVERY_SECONDS,
            # cron skips jobs while the Mac sleeps; launchd runs a calendar job at the next wake
            "StartCalendarInterval": {"Hour": at[0], "Minute": at[1]},
            "RunAtLoad": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
            "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        }
    )


def _plist_path(agents_dir: Path) -> Path:
    return agents_dir / f"{LABEL}.plist"


def _remove_old_job(agents_dir: Path, uid: int, launchctl: Launchctl) -> bool:
    """legacy: a job installed under the old label would run next to the new one."""
    old = agents_dir / f"{OLD_LABEL}.plist"
    unloaded = launchctl(["bootout", f"gui/{uid}/{OLD_LABEL}"]).returncode == 0
    existed = old.exists()
    old.unlink(missing_ok=True)
    return unloaded or existed


def cron_line(config: Path) -> str:
    """What to put in cron where there is no launchd (hourly is fine: it runs once a day)."""
    return f"0 * * * * sb run --if-due --config {config.resolve()}"


def install(plist: bytes, agents_dir: Path, uid: int, launchctl: Launchctl = run_launchctl) -> Path:
    """Write the LaunchAgent and (re)load it into the user's GUI session."""
    path = _plist_path(agents_dir)
    # first, so that a system without launchctl fails before anything is written
    _remove_old_job(agents_dir, uid, launchctl)
    launchctl(["bootout", f"gui/{uid}/{LABEL}"])  # a previous version may be loaded; ignore errors
    agents_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plist)
    result = launchctl(["bootstrap", f"gui/{uid}", str(path)])
    if result.returncode != 0:
        raise ScheduleError(result.stderr.strip() or f"launchctl exited with {result.returncode}")
    return path


def uninstall(agents_dir: Path, uid: int, launchctl: Launchctl = run_launchctl) -> bool:
    """Unload and delete the LaunchAgent. Returns False if there was nothing to remove."""
    path = _plist_path(agents_dir)
    unloaded = launchctl(["bootout", f"gui/{uid}/{LABEL}"]).returncode == 0
    existed = path.exists()
    path.unlink(missing_ok=True)
    return _remove_old_job(agents_dir, uid, launchctl) or unloaded or existed


def is_loaded(uid: int, launchctl: Launchctl = run_launchctl) -> bool:
    return launchctl(["print", f"gui/{uid}/{LABEL}"]).returncode == 0
