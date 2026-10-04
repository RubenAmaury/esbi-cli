"""Knowing that a newer version exists, and how to install it. Nothing here installs by itself:
`sb update` asks first, and the check is one anonymous HTTPS GET to the GitHub releases API."""

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import httpx

from esbi_cli import __version__, netguard

REPO_URL = "https://github.com/RubenAmaury/esbi-cli"
RELEASES_API = "https://api.github.com/repos/RubenAmaury/esbi-cli/releases/latest"
TIMEOUT_SECONDS = 5  # an update check must never hold a command up
HEADERS = {
    "User-Agent": f"esbi-cli/{__version__} (update check; +{REPO_URL})",
    "Accept": "application/vnd.github+json",
}
CHECK_INTERVAL_SECONDS = 86400  # the network is asked at most once a day...
RETRY_AFTER_FAILURE_SECONDS = 3600  # ...and an offline Mac does not retry on every command
CACHE_FILE = "update.json"
MAX_FIELD_CHARS = 200  # a longer field is refused

_VERSION = re.compile(
    r"v?([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})(?:\.?(dev|a|b|rc)([0-9]{1,6}))?", re.ASCII
)
_TAG = re.compile(r"v?[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}", re.ASCII)
_URL = re.compile(re.escape(REPO_URL) + r"/[A-Za-z0-9._~/%-]*", re.ASCII)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_STAGES = {"dev": 0, "a": 1, "b": 2, "rc": 3}
_FINAL = 4


class Release(NamedTuple):
    version: str  # "0.2.0", no leading v
    url: str  # the release page


def parse_version(text: str) -> tuple | None:
    """A sortable key for `X.Y.Z` (leading `v` allowed) with an optional `.devN`, `aN`, `bN` or `rcN`
    that sorts before the final release. None for anything else."""
    match = _VERSION.fullmatch(text)
    if not match:
        return None
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch), _STAGES.get(stage, _FINAL), int(number or 0))


def is_newer(candidate: str, current: str) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def _clean(value) -> str:
    """Text from the network is hostile: a string, not long, with no control characters."""
    if not isinstance(value, str) or len(value) > MAX_FIELD_CHARS:
        return ""
    return _CONTROL.sub("", value)


def _release(tag, url) -> Release | None:
    """A Release from untrusted text (the network, or the cache file), or None."""
    tag, url = _clean(tag), _clean(url)
    if not _TAG.fullmatch(tag):
        return None
    return Release(tag.removeprefix("v"), url if _URL.fullmatch(url) else f"{REPO_URL}/releases")


def latest_release(fetch=None) -> Release | None:
    """The newest published release, or None when it cannot be known (offline, rate limited,
    anything unexpected). Only the tag and the page URL are read, and both are checked."""
    fetch = fetch or netguard.safe_get
    try:
        response = fetch(RELEASES_API, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        if response.status_code != 200:
            return None
        data = response.json()
        return _release(data.get("tag_name"), data.get("html_url"))
    except (httpx.HTTPError, netguard.UnsafeURL, ValueError, AttributeError):
        return None


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "esbi-cli"


def _read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _age_seconds(data: dict, key: str, now: datetime) -> float:
    """Seconds since data[key]; infinite when missing, unreadable or in the future."""
    try:
        age = (now - datetime.fromisoformat(data[key])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return float("inf")
    return age if age >= 0 else float("inf")


def cached_latest(
    *,
    force: bool = False,
    directory: Path | None = None,
    now: Callable[[], datetime] | None = None,
    check: Callable[[], Release | None] | None = None,
) -> Release | None:
    """The latest release, asking the network only when the cache is older than a day (and the last
    failure older than an hour). `force` always asks and then answers only what was just learned:
    a failed check is None, not stale news. The cache is a convenience: if it cannot be read or
    written, the check still works."""
    path = (directory or cache_dir()) / CACHE_FILE
    moment = (now or (lambda: datetime.now(UTC)))()
    data = _read_cache(path)
    known = _release(data.get("latest"), data.get("url"))
    if not force and (
        _age_seconds(data, "checked_at", moment) < CHECK_INTERVAL_SECONDS
        or _age_seconds(data, "failed_at", moment) < RETRY_AFTER_FAILURE_SECONDS
    ):
        return known
    fresh = (check or latest_release)()
    if fresh:
        record = {"checked_at": moment.isoformat(), "latest": fresh.version, "url": fresh.url}
    else:
        record = {k: data[k] for k in ("checked_at", "latest", "url") if k in data}
        record["failed_at"] = moment.isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    except OSError:
        pass
    return fresh if force else fresh or known
