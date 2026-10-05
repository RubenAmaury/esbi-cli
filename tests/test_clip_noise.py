"""Page chrome in Web Clipper notes is stripped on the way to the model; article content never is.

The fixtures are synthetic but shaped like real clips of each site. The seam is `extract_source` on a
clip file (what the queue hands the worker), then the ingest pipeline for what the model is shown.
"""

from datetime import date

import pytest
from conftest import FakeLLM, make_plan

from esbi_cli.capture.inbox import scan_inbox
from esbi_cli.extract import extract_source
from esbi_cli.extract.noise import strip_chrome
from esbi_cli.ingest.pipeline import ingest

GITHUB_README = """\
## Navigation Menu

[Skip to content](https://github.com/org/tool#start-of-content)

- [Sign in](https://github.com/login?return_to=x)
- [Pricing](https://github.com/pricing)

You signed in with another tab or window. Reload to refresh your session.

# org/tool

A fast linter for configuration files. It reads YAML and TOML and reports every
mistake with a line number, so you can fix a pipeline before it runs.

## Installation

Run `pip install tool`, then Sign in to the registry with your token.

## Releases

The project follows semantic versioning; every release is tagged and signed.

### Languages

- Python 85.3%
- Shell 14.7%

## Releases 14

[v2.1.0 Latest](https://github.com/org/tool/releases/tag/v2.1.0)

[+ 13 releases](https://github.com/org/tool/releases)

## Contributors 28

[![alice](https://avatars.githubusercontent.com/u/1)](https://github.com/alice)

## Footer

© 2026 GitHub, Inc.

[Terms](https://docs.github.com/site-policy) [Privacy](https://github.com/privacy) [Security](https://github.com/security)
"""

GITHUB_ISSUE = """\
# Crash when the config has a tab character

Opened by bob. Running `tool check` on a file with a literal tab raises a
traceback instead of reporting the line.

Assignees

No one assigned

Labels

None yet

Milestone

No milestone

Sign up for free to join this conversation on GitHub. Already have an account? Sign in to comment

You're not receiving notifications from this thread.
"""

LINKEDIN_POST = """\
[Skip to main content](https://www.linkedin.com/posts/x#main-content)

[Sign in](https://www.linkedin.com/login)

Join now

Ana Pérez wrote that retrieval quality depends more on chunking than on the model,
and that she saw a 30% jump after splitting documents by section instead of by size.

Like Comment Share

41 reactions

Add a comment...

## People also viewed

- [Another profile](https://www.linkedin.com/in/other)
- Some headline text

LinkedIn Corporation © 2026
"""

X_THREAD = """\
Don't miss what's happening

People on X are the first to know.

[Log in](https://x.com/login)

Post

Conversation

Thread on evals: the first rule is to look at the data. Most teams skip it and
build dashboards on numbers they never read.

10:42 AM · Oct 3, 2026 · 1.2M Views

12 Replies 34 Reposts 100 Likes

New to X?

Sign up now to get your own personalized timeline!

Terms of Service | Privacy Policy | Cookie Policy | Accessibility | Ads info | More

© 2026 X Corp.
"""

REDDIT_THREAD = """\
[Skip to main content](https://www.reddit.com/r/x/comments/1/t/#main-content)

Open menu

Log in

# Is a local model enough for note summaries?

I tried llama3.2 on my notes and the summaries were fine for short texts, but
long ones lose the thread unless I split them first.

Sort by: Best

Join the conversation

[Share](https://www.reddit.com/r/x/comments/1/t/)

[Reply](https://www.reddit.com/r/x/comments/1/t/c1)

Splitting by section worked for me too, and a bigger model only helped a little.

3 more replies

Reddit, Inc. © 2026. All rights reserved.
"""

YOUTUBE_DESCRIPTION = """\
---
title: "Agent harnesses explained"
source: "https://www.youtube.com/watch?v=abc123"
kind: "video"
---
Skip navigation

Sign in

# Agent harnesses explained

A walk through the code that wraps a model and decides what it may do.

Show more

## Transcript

**0:00** · Sign in
**0:03** · The agent harness is the code around the model, and it decides what the agent can do.
**0:09** · Share
"""


def write_clip(tmp_path, source, body, name="clip.md"):
    path = tmp_path / name
    path.write_text(f"---\nsource: {source}\ntitle: Un clip\n---\n{body}", encoding="utf-8")
    return path


def test_github_repo_page_loses_its_chrome_and_keeps_the_readme(tmp_path):
    doc = extract_source(str(write_clip(tmp_path, "https://github.com/org/tool", GITHUB_README)))

    for chrome in (
        "Navigation Menu",
        "Skip to content",
        "Sign in](https",
        "Pricing",
        "another tab or window",
        "Languages",
        "Python 85.3%",
        "Releases 14",
        "v2.1.0",
        "Contributors 28",
        "alice",
        "Footer",
        "© 2026 GitHub",
        "Terms",
    ):
        assert chrome not in doc.text, chrome
    assert "A fast linter for configuration files" in doc.text
    assert "Run `pip install tool`, then Sign in to the registry with your token." in doc.text
    # a README section that merely shares a sidebar's name, with prose under it, stays whole
    assert "## Releases\n\nThe project follows semantic versioning" in doc.text
    assert doc.stripped_lines == 16


def test_github_issue_loses_the_sidebar_and_keeps_the_report(tmp_path):
    doc = extract_source(
        str(write_clip(tmp_path, "https://github.com/org/tool/issues/7", GITHUB_ISSUE))
    )

    assert "Crash when the config has a tab character" in doc.text
    assert "raises a\ntraceback instead of reporting the line." in doc.text
    for chrome in ("Assignees", "No one assigned", "Labels", "None yet", "No milestone", "Sign up"):
        assert chrome not in doc.text, chrome
    assert "receiving notifications" not in doc.text


def test_linkedin_post_loses_chrome_and_keeps_the_post(tmp_path):
    doc = extract_source(
        str(write_clip(tmp_path, "https://www.linkedin.com/posts/ana_x", LINKEDIN_POST))
    )

    assert "retrieval quality depends more on chunking than on the model" in doc.text
    assert "30% jump" in doc.text
    for chrome in (
        "Skip to main",
        "Sign in",
        "Join now",
        "Like Comment Share",
        "41 reactions",
        "Add a comment",
        "People also viewed",
        "Another profile",
        "Some headline text",
        "LinkedIn Corporation",
    ):
        assert chrome not in doc.text, chrome


def test_x_thread_loses_chrome_and_keeps_the_thread(tmp_path):
    doc = extract_source(str(write_clip(tmp_path, "https://x.com/someone/status/1", X_THREAD)))

    assert "Thread on evals: the first rule is to look at the data." in doc.text
    assert "build dashboards on numbers they never read." in doc.text
    for chrome in (
        "Don't miss",
        "People on X",
        "Log in",
        "New to X",
        "Terms of Service",
        "X Corp",
        "Views",
        "Replies",
    ):
        assert chrome not in doc.text, chrome


def test_twitter_dot_com_is_the_same_site_as_x(tmp_path):
    doc = extract_source(
        str(write_clip(tmp_path, "https://twitter.com/someone/status/1", X_THREAD))
    )
    assert "Don't miss" not in doc.text and "Thread on evals" in doc.text


def test_reddit_thread_loses_chrome_and_keeps_post_and_comments(tmp_path):
    doc = extract_source(
        str(write_clip(tmp_path, "https://www.reddit.com/r/x/comments/1/t/", REDDIT_THREAD))
    )

    assert "I tried llama3.2 on my notes" in doc.text
    assert "Splitting by section worked for me too" in doc.text
    for chrome in (
        "Skip to main",
        "Open menu",
        "Log in",
        "Sort by",
        "Join the conversation",
        "[Share]",
        "[Reply]",
        "3 more replies",
        "Reddit, Inc.",
    ):
        assert chrome not in doc.text, chrome


def test_youtube_description_loses_chrome_and_the_transcript_is_never_touched(tmp_path):
    path = tmp_path / "video.md"
    path.write_text(YOUTUBE_DESCRIPTION, encoding="utf-8")

    doc = extract_source(str(path))

    assert "A walk through the code that wraps a model" in doc.text
    assert "Skip navigation" not in doc.text and "Show more" not in doc.text
    assert "# Agent harnesses explained" in doc.text
    # transcript rows stay even when their words are chrome words: they are what was said
    assert "**0:00** · Sign in" in doc.text and "**0:09** · Share" in doc.text
    assert "The agent harness is the code around the model" in doc.text


def test_a_chrome_phrase_inside_a_sentence_or_a_plain_bullet_is_content(tmp_path):
    body = (
        "To use the service you must Sign in with your account, then Share the link.\n\n"
        "Steps:\n\n- Sign in\n- Create a project\n- Share\n\n"
        "He said: Skip to content is a link, not a chapter. Join now or never.\n\n"
        "Sign in to view more content is what the paywall said, which annoyed everyone.\n\n"
        "It got 41 reactions, 12 replies, 3 more replies and 1.2K views in a day."
    )
    for source in (
        "https://github.com/o/r/issues/1",
        "https://www.linkedin.com/posts/x",
        "https://x.com/a/status/1",
        "https://www.reddit.com/r/a/comments/1",
        "https://www.youtube.com/watch?v=1",
    ):
        doc = extract_source(str(write_clip(tmp_path, source, body)))
        assert doc.text == body, source
        assert doc.stripped_lines == 0


def test_a_bare_nav_word_is_chrome_only_as_a_link_on_the_same_site():
    body = (
        "[Pricing](https://github.com/pricing)\n\n[Pricing](https://evil.test/pricing)\n\nPricing"
    )
    text, removed = strip_chrome(body + "\n\n" + "Real text. " * 10, "https://github.com/o/r")
    assert removed == 1 and "evil.test" in text and text.count("Pricing") == 2


def test_a_line_of_several_links_goes_only_when_every_link_is_chrome():
    mixed = "[Pricing](https://github.com/pricing) [Why us](https://github.com/why-us)"
    text = mixed + "\n\n" + "Real text. " * 10
    assert strip_chrome(text, "https://github.com/o/r") == (text, 0)


def test_a_sidebar_heading_without_the_sidebar_shape_stays():
    text = (
        "## Releases 14\n\n" + "This paragraph is long enough to be prose, not a sidebar list. " * 4
    )
    assert strip_chrome(text, "https://github.com/o/r") == (text, 0)
    text = "Languages\n\nThe tool speaks English and Spanish, among others, in its messages."
    assert strip_chrome(text, "https://github.com/o/r") == (text, 0)


def test_a_chrome_block_stops_at_the_next_heading_and_at_a_paragraph():
    text = (
        "## People also viewed\n\nShort item\n\n"
        "A long paragraph of the article continues here and it is certainly more than "
        "one hundred and sixty characters, so it cannot be an item of a related list at all, never.\n\n"
        "## Next section\n\nKept."
    )
    out, removed = strip_chrome(text, "https://www.linkedin.com/posts/x")
    assert removed == 2
    assert out.startswith("A long paragraph") and out.endswith("## Next section\n\nKept.")


def test_a_chrome_block_stops_at_a_heading_even_with_short_lines_before_it():
    text = "## People also viewed\n\nShort item\n\n## Next section\n\nKept."
    assert strip_chrome(text, "https://www.linkedin.com/posts/x") == ("## Next section\n\nKept.", 2)


def test_a_chrome_block_never_swallows_transcript_rows():
    text = "Comments\n\n**0:03** · Short row of what was said.\n**0:09** · Another row."
    out, removed = strip_chrome(text, "https://www.youtube.com/watch?v=1")
    assert removed == 1 and out.startswith("**0:03** · Short row")


def test_code_fences_are_never_cleaned():
    text = "```\nSign in\nSkip to content\n```\n\n" + "Text. " * 10
    assert strip_chrome(text, "https://github.com/o/r") == (text, 0)


def test_unknown_hosts_and_mail_are_left_alone():
    text = "Skip to content\n\nSign in\n\nSomething real."
    assert strip_chrome(text, "https://blog.example.com/p") == (text, 0)
    assert strip_chrome(text, "mail:abc") == (text, 0)
    footer = "A forwarded notice.\n\n© 2026 GitHub, Inc.\n\nSign in"
    assert strip_chrome(footer, "mail:abc") == (footer, 0)
    assert strip_chrome(text, "https://notgithub.com/p") == (text, 0)


def test_a_clip_without_a_source_is_recognised_by_its_footer():
    text = "Real content here.\n\n© 2026 GitHub, Inc.\n\nSign in"
    assert strip_chrome(text, None) == ("Real content here.", 2)
    plain = "Real content here.\n\nSign in"
    assert strip_chrome(plain, None) == (plain, 0)


def test_the_raw_copy_of_the_clip_stays_untouched_and_the_note_records_what_was_stripped(
    vault, queue, cfg
):
    clip = f"---\nsource: https://github.com/org/tool\ntitle: org/tool\n---\n{GITHUB_README}"
    (vault.root / "inbox" / "org-tool.md").write_text(clip, encoding="utf-8")
    scan_inbox(vault, queue)
    kept = vault.root / "raw" / "inbox" / "org-tool.md"
    llm = FakeLLM(make_plan(title="org tool"))

    result = ingest(str(kept), vault=vault, llm=llm, cfg=cfg, today=date(2026, 10, 3))

    assert kept.read_text(encoding="utf-8") == clip  # raw/inbox keeps the page exactly as clipped
    prompt = "".join(call["user"] for call in llm.calls)
    assert "A fast linter for configuration files" in prompt
    assert "Skip to content" not in prompt and "Contributors 28" not in prompt
    note = vault.read_page(vault.page_path("sources", "org tool"))
    assert note.meta["stripped_lines"] == 16
    assert any("page chrome" in w for w in result.warnings)


def test_a_note_from_a_clean_clip_has_no_stripped_lines_key(vault, cfg, doc):
    ingest("x", vault=vault, llm=FakeLLM(make_plan()), cfg=cfg, extractor=lambda _: doc)
    note = vault.read_page(vault.page_path("sources", "Arnés de agentes"))
    assert "stripped_lines" not in note.meta


@pytest.mark.parametrize("source", ["https://github.com/o/r", "https://x.com/a/status/1"])
def test_a_clip_that_is_all_chrome_is_rejected_as_empty(tmp_path, source):
    from esbi_cli.extract import ExtractError

    path = write_clip(tmp_path, source, "Skip to content\n\nSign in\n\nSign up\n\nFooter")
    with pytest.raises(ExtractError, match="almost no text"):
        extract_source(str(path))


@pytest.mark.parametrize(
    "hostile",
    ["[" * 40000, "# " + "#" * 40000 + " x", "[a](" + "x" * 40000],
    ids=["brackets", "hashes", "open-link"],
)
def test_a_hostile_very_long_line_is_not_a_slowdown(hostile):
    import time

    text = f"People also viewed\n\n{hostile}\n\n" + "Real text. " * 10
    start = time.monotonic()
    out, _ = strip_chrome(text, "https://www.linkedin.com/posts/x")
    assert time.monotonic() - start < 1 and hostile in out
