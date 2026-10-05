import subprocess
from pathlib import Path

# What the worker commits. SCHEMA.md and the golden questions are the user's own, but they are
# versioned so that a restore from the remote does not lose them.
VAULT_MANAGED = (
    "wiki",
    "raw",
    "attachments",
    "index.md",
    "log.md",
    "Home.md",
    "SCHEMA.md",
    ".gitignore",  # the rules that keep the state folder out: they travel with the vault
    ".esbi/golden.jsonl",
)
# The state folder is ignored, but for the golden questions.
STATE_IGNORE = (".esbi/*", "!.esbi/golden.jsonl")
GIT_PUSH_TIMEOUT_SECONDS = 120  # an unreachable remote must not hold a run


class GitError(RuntimeError):
    pass


def has_git() -> bool:
    """Is a working `git` installed? (On a Mac without the developer tools, /usr/bin/git exists
    but fails, so asking it is the only honest test.)"""
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        raise GitError("git is not installed") from None


def _identity_args(root: Path) -> list[str]:
    """`-c` settings that give a commit a name and email only where git has none (a fresh Linux
    user, a container): without them git refuses to commit and the vault never gets any history."""
    if all(
        _git(root, "config", "--get", key).stdout.strip() for key in ("user.name", "user.email")
    ):
        return []
    return ["-c", "user.name=esbi-cli", "-c", "user.email=esbi-cli@localhost"]


def _has_files(path: Path) -> bool:
    """A managed path is committable only if it holds a file: git cannot track an empty folder,
    and naming one in `git commit -- <path>` fails ("pathspec did not match")."""
    return path.is_file() or (path.is_dir() and any(f.is_file() for f in path.rglob("*")))


def ignore_state(root: Path) -> None:
    """Make `.gitignore` ignore the state folder except the golden questions. A vault from before
    this (a plain `.esbi/` line, or none after the `.secondbrain` rename) is upgraded in place."""
    ignore = root / ".gitignore"
    if not ignore.exists():
        return
    lines = ignore.read_text().splitlines()
    if STATE_IGNORE[0] in lines:
        return
    at = lines.index(".esbi/") if ".esbi/" in lines else len(lines)
    lines[at : at + 1] = STATE_IGNORE
    ignore.write_text("\n".join(lines) + "\n")


def commit_vault(root: Path, message: str) -> bool:
    """Commit only worker-managed paths, leaving the user's own edits (.obsidian etc.) alone.

    Returns True if a commit was made, False if there was nothing to commit.
    """
    if not (root / ".git").exists():  # history is optional: no repository, nothing to commit
        return False
    ignore_state(root)
    paths = [p for p in VAULT_MANAGED if _has_files(root / p)]
    # a path the user's own rules ignore would make `git add` fail and stop every commit
    hidden = _git(root, "check-ignore", "--", *paths).stdout.split() if paths else []
    paths = [p for p in paths if p not in hidden]
    if not paths:
        return False
    added = _git(root, "add", "--", *paths)
    if added.returncode != 0:
        raise GitError(added.stderr.strip())
    if _git(root, "diff", "--cached", "--quiet", "--", *paths).returncode == 0:
        return False
    done = _git(root, *_identity_args(root), "commit", "-m", message, "--", *paths)
    if done.returncode != 0:
        raise GitError(done.stderr.strip() or done.stdout.strip())
    return True


def push_vault(root: Path) -> str | None:
    """Back the vault up to its `origin`, if it has one. Returns None when done or when there is
    no remote, else the reason: a backup that is unreachable must never stop a run."""
    if not (root / ".git").exists() or _git(root, "remote", "get-url", "origin").returncode != 0:
        return None
    try:
        done = subprocess.run(
            ["git", "push", "origin", "HEAD", "--tags"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GIT_PUSH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "git push timed out"
    return None if done.returncode == 0 else (done.stderr.strip() or done.stdout.strip())
