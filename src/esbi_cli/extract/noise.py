"""Strip well-known page chrome (navigation, cookie banners, sidebars, footers) from Web Clipper notes.

Deliberately conservative: a false removal of real content is worse than leaving noise. So a line goes
only when the WHOLE line is a known chrome string (never a sentence that merely contains one), a bare
navigation word goes only as a link to the same site, and a sidebar heading goes only with the shape
of body that sidebar has. Only five sites are known; anything else is returned untouched.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_TIMESTAMP_LINE = re.compile(
    r"^\s*\*\*\d+(?::\d{2}){1,2}\*\* ·"
)  # a YouTube transcript row: never touched
_MAX_BLOCK_LINE_CHARS = 160  # a longer line is a paragraph, which ends any chrome block
# the short lines a GitHub sidebar section holds: links, avatars, "v1.2.3", "Latest", "+ 12 releases"
_SIDEBAR_BODY = re.compile(r"(?:[-*+]\s+)?!?\[.*|\S+(?: \S+){0,3}")


@dataclass
class Block:
    """A heading that opens a chrome section, plus the shape of lines that belong to it (None: any short line)."""

    head: re.Pattern
    body: re.Pattern | None = None


@dataclass
class Site:
    domains: tuple[str, ...]
    signature: re.Pattern  # only used when the clip has no source URL
    plain: set[str] = field(
        default_factory=set
    )  # distinctive: removed as a whole line, plain or linked
    link_words: set[str] = field(
        default_factory=set
    )  # bare words: removed only as a same-site link
    heads: set[str] = field(default_factory=set)  # removed when the whole line is this heading
    line_res: list[re.Pattern] = field(
        default_factory=list
    )  # whole-line patterns on the cleaned text
    blocks: list[Block] = field(default_factory=list)


def _re(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_COUNTED = (
    r"\s+[\d.,]+k?"  # GitHub sidebar headings carry a count: "Releases 14", "Contributors 28"
)

GITHUB = Site(
    domains=("github.com",),
    signature=_re(r"© \d{4} GitHub, Inc\."),
    plain={
        "skip to content",
        "sign in",
        "sign up",
        "navigation menu",
        "search or jump to",
        "saved searches",
        "use saved searches to filter your results more quickly",
        "appearance settings",
        "dismiss alert",
        "footer",
        "footer navigation",
        "you can't perform that action at this time",
        "you signed in with another tab or window. reload to refresh your session",
        "you signed out in another tab or window. reload to refresh your session",
        "you switched accounts on another tab or window. reload to refresh your session",
        "no releases published",
        "no packages published",
        "create a new release",
        "publish your first package",
        "report repository",
        "sign up for free to join this conversation on github",
        "already have an account? sign in to comment",
        "you're not receiving notifications from this thread",
        "there was an error while loading. please reload this page",
    },
    link_words={
        "product",
        "solutions",
        "resources",
        "open source",
        "enterprise",
        "pricing",
        "code",
        "issues",
        "pull requests",
        "actions",
        "projects",
        "security",
        "insights",
        "wiki",
        "go to file",
        "add file",
        "fork",
        "star",
        "watch",
        "terms",
        "privacy",
        "status",
        "docs",
        "contact",
        "manage cookies",
        "do not share my personal information",
        "new issue",
        "notifications",
        "sponsor",
        "github sponsors",
        "community",
        "training",
    },  # fmt: skip
    heads={"navigation menu", "footer", "footer navigation"},
    line_res=[
        _re(r"© \d{4} github, inc"),
        _re(r"[\d.,]+k? (stars?|watching|forks?|watchers)"),
        _re(r"\+ ?\d+ (contributors?|releases|languages)"),
        _re(r"(activity|custom properties)"),
        _re(
            r"sign up for free to join this conversation on github\.? already have an account\? sign in to comment"
        ),
    ],
    blocks=[
        Block(_re(r"languages"), _re(r"[\w#+.\- ]+ \d+(?:\.\d+)?%")),
        Block(
            _re(rf"(releases|contributors|packages|used by|deployments|environments){_COUNTED}"),
            _SIDEBAR_BODY,
        ),
        Block(
            _re(r"assignees|labels|projects|milestone|development|notifications|participants"),
            _re(
                r"no one assigned|none yet|no milestone|no branches or pull requests|customize"
                r"|subscribe|unsubscribe|you're not receiving notifications from this thread\.?"
            ),
        ),
    ],
)

LINKEDIN = Site(
    domains=("linkedin.com",),
    signature=_re(r"linkedin corporation ©|agree & join linkedin"),
    plain={
        "skip to main content",
        "sign in",
        "join now",
        "sign in to view more content",
        "join now to see what you are missing",
        "new to linkedin? join now",
        "agree & join linkedin",
        "continue to join or sign in",
        "by clicking continue to join or sign in, you agree to linkedin's user agreement, "
        "privacy policy, and cookie policy",
        "report this post",
        "add a comment",
        "see more comments",
        "sign in to view more comments",
    },
    link_words={
        "like",
        "comment",
        "share",
        "repost",
        "send",
        "about",
        "accessibility",
        "user agreement",
        "privacy policy",
        "cookie policy",
        "copyright policy",
        "brand policy",
        "guest controls",
        "community guidelines",
        "sign in",
        "join now",
        "forgot password?",
        "help center",
    },  # fmt: skip
    line_res=[
        _re(r"(like|comment|repost|share|send)(?: (?:like|comment|repost|share|send))+"),
        _re(r"[\d.,]+k? (reactions?|comments?|reposts?)"),
        _re(r"linkedin( corporation)? © \d{4}"),
    ],
    blocks=[
        Block(_re(r"people also viewed|others also viewed|similar pages|explore topics")),
        Block(_re(r"more (articles|posts) by .*|insights from the community")),
    ],
)

TWITTER = Site(
    domains=("x.com", "twitter.com"),
    signature=_re(r"don'?t miss what'?s happening"),
    plain={
        "don't miss what's happening",
        "people on x are the first to know",
        "new to x?",
        "sign up now to get your own personalized timeline",
        "something went wrong. try reloading",
        "log in",
        "sign up",
        "create account",
        "sign up with google",
        "sign up with apple",
        "see new posts",
        "post your reply",
    },
    link_words={
        "home",
        "explore",
        "notifications",
        "messages",
        "grok",
        "bookmarks",
        "communities",
        "premium",
        "profile",
        "more",
        "post",
        "lists",
        "jobs",
        "privacy policy",
        "cookie policy",
        "accessibility",
        "ads info",
        "terms of service",
        "help center",
        "log in",
        "sign up",
    },  # fmt: skip
    line_res=[
        _re(r"terms of service\s*\|.*"),
        _re(r"© \d{4} x corp"),
        _re(r"read \d+ repl(?:y|ies)"),
        _re(r"(?:[\d.,]+[km]? (?:views?|replies|reposts?|likes?|bookmarks?|quotes?)\s*)+"),
        _re(r"\d{1,2}:\d{2} (?:am|pm) · .*· [\d.,]+[km]? views?"),
    ],
    blocks=[Block(_re(r"relevant people|trending now|what's happening"))],
)

REDDIT = Site(
    domains=("reddit.com", "redd.it"),
    signature=_re(r"reddit, inc\. ©"),
    plain={
        "skip to main content",
        "open menu",
        "open navigation",
        "go to reddit home",
        "log in",
        "sign up",
        "log in / sign up",
        "get app",
        "get the reddit app",
        "expand user menu",
        "open settings menu",
        "open comment sort options",
        "add a comment",
        "join the conversation",
        "continue this thread",
        "load more comments",
        "give award",
    },
    link_words={
        "share",
        "reply",
        "award",
        "save",
        "report",
        "follow",
        "join",
        "home",
        "popular",
        "all",
        "explore",
        "communities",
        "reddit rules",
        "privacy policy",
        "user agreement",
    },  # fmt: skip
    line_res=[
        _re(r"sort by:? \w+"),
        _re(r"\d+ more repl(?:y|ies)"),
        _re(r"[\d.,]+k? (?:comments?|upvotes?|points?)"),
        _re(r"reddit,? inc\.? © \d{4}.*"),
        _re(r"reddit rules.*user agreement.*"),
    ],
    blocks=[Block(_re(r"related answers|more posts you may like|top posts|related posts"))],
)

YOUTUBE = Site(
    domains=("youtube.com", "youtu.be"),
    signature=_re(r"skip navigation"),
    plain={
        "skip navigation",
        "sign in",
        "sign in to confirm you're not a bot",
        "subscribe",
        "subscribed",
        "share",
        "save",
        "download",
        "clip",
        "show more",
        "show less",
        "add a comment",
        "up next",
        "autoplay",
        "show chat replay",
    },
    line_res=[_re(r"[\d.,]+[kmb]? (?:views|subscribers|likes)")],
    blocks=[Block(_re(r"up next|comments?(?:\s+[\d.,]+[km]?)?|recommended"))],
)

SITES = (GITHUB, LINKEDIN, TWITTER, REDDIT, YOUTUBE)


def _host_in(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _site_for(url: str | None, text: str) -> Site | None:
    if url and url.startswith(("http://", "https://")):
        return next((s for s in SITES if _host_in(url, s.domains)), None)
    if url:  # mail:..., or something else that is not a page: not ours to clean
        return None
    return next((s for s in SITES if s.signature.search(text)), None)


def _clean(text: str) -> str:
    text = _LINK.sub(r"\1", text).replace("’", "'")
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip().lstrip("…").rstrip(".:!…").strip().lower()


def _same_site(target: str, site: Site) -> bool:
    return not target.startswith(("http://", "https://")) or _host_in(target, site.domains)


def _is_chrome_line(site: Site, line: str) -> bool:
    if heading := _HEADING.match(line):
        return _clean(heading.group(1)) in site.heads
    bare = re.sub(r"^\s*(?:[-*+]\s+)?", "", line)
    links = _LINK.findall(bare)
    if links and not re.sub(r"[\s|·•-]+", "", _LINK.sub("", bare)):
        # a line made only of links (a nav bar, a footer): chrome if every link is a known word and on-site
        words = site.link_words | site.plain
        return all(_clean(text) in words and _same_site(target, site) for text, target in links)
    text = _clean(line)  # a plain bullet keeps its "- " here, so it never equals a chrome string
    return bool(text) and (text in site.plain or any(r.fullmatch(text) for r in site.line_res))


def _block_end(site: Site, lines: list[str], i: int) -> int | None:
    """Index just past the chrome block that starts at lines[i], or None if none starts there."""
    heading = _HEADING.match(lines[i])
    text = _clean(heading.group(1) if heading else lines[i])
    block = next((b for b in site.blocks if b.head.fullmatch(text)), None)
    if block is None:
        return None
    end, j = i + 1, i + 1
    while j < len(lines):
        raw = lines[j].strip()
        if raw:
            if (
                _HEADING.match(raw)
                or raw.startswith(("```", "~~~"))
                or _TIMESTAMP_LINE.match(raw)
                or len(raw) > _MAX_BLOCK_LINE_CHARS
                or (block.body and not block.body.fullmatch(raw))
            ):
                break
            end = j + 1
        j += 1
    return end if end > i + 1 or block.body is None else None


def strip_chrome(text: str, url: str | None) -> tuple[str, int]:
    """Return (text without the page chrome of a known site, number of non-blank lines removed)."""
    site = _site_for(url, text)
    if site is None:
        return text, 0
    lines, kept, removed, i, in_fence = text.split("\n"), [], 0, 0, False
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        end = None if in_fence else _block_end(site, lines, i)
        if end is None and not in_fence and _is_chrome_line(site, line):
            end = i + 1
        if end is None:
            kept.append(line)
            i += 1
            continue
        removed += sum(1 for dropped in lines[i:end] if dropped.strip())
        i = end
    if not removed:
        return text, 0
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), removed
