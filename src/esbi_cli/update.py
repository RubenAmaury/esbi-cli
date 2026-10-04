"""Knowing that a newer version exists, and how to install it. Nothing here installs by itself:
`sb update` asks first, and the check is one anonymous HTTPS GET to the GitHub releases API."""

import re
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


def latest_release(fetch=None) -> Release | None:
    """The newest published release, or None when it cannot be known (offline, rate limited,
    anything unexpected). Only the tag and the page URL are read, and both are checked."""
    fetch = fetch or netguard.safe_get
    try:
        response = fetch(RELEASES_API, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        if response.status_code != 200:
            return None
        data = response.json()
        tag = _clean(data.get("tag_name"))
        url = _clean(data.get("html_url"))
    except (httpx.HTTPError, netguard.UnsafeURL, ValueError, AttributeError):
        return None
    if not _TAG.fullmatch(tag):
        return None
    return Release(tag.removeprefix("v"), url if _URL.fullmatch(url) else f"{REPO_URL}/releases")
