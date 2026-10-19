"""LinkedIn posts: the post and its author, without the public comments the page carries."""

import json
import re
from urllib.parse import unquote, urlparse

import lxml.html

from esbi_cli.extract import ExtractedDoc, is_url

_ACTIVITY = re.compile(r"/(?:posts/[^/]*-activity-|feed/update/urn:li:activity:)(\d+)(?:[-/]|$)")


def post_url(url: str) -> str | None:
    """The one address of a LinkedIn post, from its activity id: a `/posts/...-activity-<id>-...`
    share and a `/feed/update/urn:li:activity:<id>` link are the same post. None for anything
    else."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (
        host == "linkedin.com" or host.endswith(".linkedin.com")
    ):
        return None
    if match := _ACTIVITY.match(unquote(parsed.path)):
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{match[1]}"
    return None


def _xpath(html: str, path: str) -> list:
    try:
        return lxml.html.fromstring(html).xpath(path)
    except (lxml.etree.ParserError, ValueError):
        return []


def outbound_url(html: str) -> str | None:
    """Where a lnkd.in short link's interstitial page points."""
    for href in _xpath(html, '//a[@data-tracking-control-name="external_url_click"]/@href'):
        if is_url(href := href.strip()):
            return href
    return None


def _posting(html: str) -> dict | None:
    """The page's JSON-LD SocialMediaPosting, if it has one with a body."""
    for script in _xpath(html, '//script[@type="application/ld+json"]'):
        try:
            data = json.loads(script.text or "")
        except json.JSONDecodeError:
            continue
        if (
            isinstance(data, dict)
            and data.get("@type") == "SocialMediaPosting"
            and str(data.get("articleBody") or "").strip()
        ):
            return data
    return None


def read_post(html: str, url: str) -> ExtractedDoc | None:
    """The post from its structured data (the comments sit in their own field, left out), or None
    when the page has none."""
    data = _posting(html)
    if data is None:
        return None
    body = data["articleBody"].strip()
    author = data.get("author")
    author = str(author.get("name") or "").strip() if isinstance(author, dict) else ""
    headline = str(data.get("headline") or "").strip() or body.splitlines()[0]
    return ExtractedDoc(
        title=f"{author} on LinkedIn: {headline}" if author else headline,
        text=f"By {author}\n\n{body}" if author else body,
        kind="article",
        url=url,
    )
