import re
from pathlib import Path

import pytest
from injection_corpus import _pdf_with
from pdf_fixtures import pdf_bytes

from esbi_cli.extract import ExtractError, extract_source, is_url, with_scheme
from esbi_cli.extract.html import extract_html
from esbi_cli.extract.pdf import extract_pdf_bytes

ARTICLE = (
    "<html><head><title>Un gran artículo</title></head><body><nav>menu menu</nav>"
    "<article><h1>Un gran artículo</h1>"
    + "".join(
        f"<p>Párrafo número {i} con bastante texto para que el extractor lo considere contenido real de la página.</p>"
        for i in range(12)
    )
    + "</article><footer>pie</footer></body></html>"
)


def test_extract_html_returns_title_and_body_without_boilerplate():
    doc = extract_html(ARTICLE, "https://x.test/a")
    assert doc.title == "Un gran artículo" and doc.kind == "article"
    assert "Párrafo número 3" in doc.text and "menu menu" not in doc.text


def test_extract_html_rejects_pages_without_content():
    with pytest.raises(ExtractError):
        extract_html("<html><body><p>hola</p></body></html>", "https://x.test/")


def test_extract_pdf_returns_text_and_keeps_bytes():
    data = pdf_bytes("plain-text.pdf")
    doc = extract_pdf_bytes(data, fallback_title="attention-paper")
    assert doc.kind == "paper" and "Attention" in doc.text and doc.pdf_bytes == data
    assert doc.title == "attention paper"


BODY = "\n".join(f"Line {n} of the lecture about agents, tools and planning." for n in range(12))


def test_a_pdf_title_that_the_document_shows_is_used():
    data = _pdf_with(
        "Agent R1: A Modular Framework\n" + BODY, title="Agent R1: A Modular Framework"
    )
    assert (
        extract_pdf_bytes(data, fallback_title="agent-r1-v2").title
        == "Agent R1: A Modular Framework"
    )


def test_a_pdf_title_left_over_from_a_template_is_ignored_for_the_file_name():
    """Slide decks made from one template carry its old Title: 16 course decks were all called
    "Machine Learning Landscape & Python Basics". A title the pages never show is not trusted."""
    data = _pdf_with(
        "Week 9 From Chains to Graphs\n" + BODY, title="Machine Learning Landscape & Python Basics"
    )
    title = extract_pdf_bytes(data, fallback_title="Week9_From-Chains-to-Graphs").title
    assert title == "Week9 From Chains to Graphs"


def test_a_file_name_with_spaces_keeps_its_hyphens_and_loses_extra_spaces():
    data = _pdf_with(BODY, title="Week2_PE_Slides.pptx")
    title = extract_pdf_bytes(data, fallback_title="Session 2 -  Multi-Agent  Teams").title
    assert title == "Session 2 - Multi-Agent Teams"
    exported = extract_pdf_bytes(data, fallback_title="Week2_Generative_AI_Landscape.pptx").title
    assert exported == "Week2 Generative AI Landscape"  # a deck saved as name.pptx.pdf


def test_extract_source_reads_local_pdf_and_rejects_other_files(tmp_path):
    pdf = tmp_path / "Mi_Paper.pdf"
    pdf.write_bytes(pdf_bytes("plain-text.pdf"))
    assert extract_source(str(pdf)).title == "Mi Paper"
    with pytest.raises(ExtractError):
        extract_source(str(tmp_path / "missing.pdf"))
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(ExtractError, match="Unsupported"):
        extract_source(str(txt))


def test_is_url():
    assert is_url("https://a.b/c") and not is_url("/tmp/a.pdf") and not is_url("file:///a")


def test_a_url_has_a_host_and_no_whitespace():
    """Several links pasted as one argument must not become one glued-together "URL"."""
    assert not is_url("https://a.test/x\nhttps://b.test/y")
    assert not is_url("https://a.test/x https://b.test/y")
    assert not is_url("https://a.test/x\t")
    assert not is_url("https://")
    assert is_url("https://web.archive.org/web/2020/https://a.test/x")  # a URL inside a URL is fine


def test_extract_source_reads_a_web_clipper_note_from_its_own_body(tmp_path):
    clip = tmp_path / "Post.md"
    clip.write_text(
        "---\nsource: https://www.linkedin.com/posts/abc\ntitle: Mi post\n---\n"
        + "Texto del post. " * 10,
        encoding="utf-8",
    )
    doc = extract_source(str(clip))
    assert doc.url == "https://www.linkedin.com/posts/abc"
    assert doc.title == "Mi post" and doc.kind == "article"
    assert doc.text.startswith("Texto del post.") and "source:" not in doc.text


def test_extract_source_accepts_a_plain_markdown_note_and_rejects_an_empty_one(tmp_path):
    plain = tmp_path / "Idea suelta.md"
    plain.write_text("Una idea sobre agentes que quiero guardar para más tarde, sin frontmatter.")
    doc = extract_source(str(plain))
    assert doc.title == "Idea suelta" and doc.url is None

    empty = tmp_path / "Vacío.md"
    empty.write_text("---\nsource: https://x.test\n---\nhola")
    with pytest.raises(ExtractError, match="almost no text"):
        extract_source(str(empty))


def test_a_clip_can_declare_its_kind_and_unknown_kinds_fall_back_to_article(tmp_path):
    mail = tmp_path / "Mail.md"
    mail.write_text("---\nsource: mail:abc\nkind: email\ntitle: Asunto\n---\n" + "x" * 60)
    doc = extract_source(str(mail))
    assert (doc.kind, doc.url, doc.title) == ("email", "mail:abc", "Asunto")

    odd = tmp_path / "Odd.md"
    odd.write_text("---\nkind: rumor\n---\n" + "x" * 60)
    assert extract_source(str(odd)).kind == "article"


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9/x", "http://localhost/admin", "http://169.254.169.254/latest/"]
)
def test_extract_source_refuses_urls_that_point_at_internal_addresses(url):
    with pytest.raises(ExtractError, match="non-public"):
        extract_source(url)


def test_pages_are_fetched_with_an_honest_identifying_user_agent(monkeypatch):
    """Regression (found in the test drive): Wikipedia answers 403 to a generic
    'Mozilla/5.0 (compatible; ...)' agent but accepts a descriptive one with a contact URL."""
    import httpx

    from esbi_cli import extract

    sent = {}

    def fake_safe_get(url, **kwargs):
        sent.update(kwargs.get("headers", {}))
        return httpx.Response(
            200,
            text=ARTICLE,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(extract, "safe_get", fake_safe_get)

    extract_source("https://example.test/articulo")

    agent = sent["User-Agent"]
    assert re.fullmatch(r"esbi-cli/\S+ \(.*; \+https://github\.com/RubenAmaury/esbi-cli\)", agent)
    assert not agent.startswith("Mozilla/")


def test_a_host_that_does_not_resolve_is_reported_as_unreachable_not_as_refused():
    with pytest.raises(ExtractError) as error:
        extract_source("https://no-such-host.invalid/page")

    assert "Could not fetch" in str(error.value) and "Refused" not in str(error.value)


def _fake_web(monkeypatch, pages):
    """Serve `pages` {url: (status, text)} through extract.safe_get; records what was asked."""
    import httpx

    from esbi_cli import extract

    asked = []

    def fake_safe_get(url, *, client=None, resolver=None, headers=None, timeout_seconds=30):
        asked.append(url)
        status, text = pages.get(url, (404, "not found"))
        return httpx.Response(
            status,
            text=text,
            headers={"content-type": "text/markdown" if url.endswith(".md") else "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(extract, "safe_get", fake_safe_get)
    return asked


README = "# Academy\n\n" + "Un recurso sobre diseño de sistemas con ejemplos reales. " * 30


def test_a_github_repository_url_is_read_through_its_readme_and_titled_owner_slash_repo(
    monkeypatch,
):
    asked = _fake_web(
        monkeypatch,
        {"https://raw.githubusercontent.com/acme/academy/HEAD/README.md": (200, README)},
    )

    doc = extract_source("https://github.com/acme/academy/")

    assert doc.title == "acme/academy" and "diseño de sistemas" in doc.text
    assert doc.url == "https://github.com/acme/academy/"  # the link the user saved
    assert asked == ["https://raw.githubusercontent.com/acme/academy/HEAD/README.md"]


def test_a_github_repository_without_a_readme_falls_back_to_the_page_itself(monkeypatch):
    asked = _fake_web(monkeypatch, {"https://github.com/acme/empty": (200, ARTICLE)})

    doc = extract_source("https://github.com/acme/empty")

    assert doc.title == "Un gran artículo"
    assert asked[-1] == "https://github.com/acme/empty"


def test_other_github_urls_are_left_to_the_normal_page_reader(monkeypatch):
    asked = _fake_web(monkeypatch, {"https://github.com/acme/academy/issues/3": (200, ARTICLE)})

    extract_source("https://github.com/acme/academy/issues/3")

    assert asked == ["https://github.com/acme/academy/issues/3"]


YOUTUBE_CLIP = """---
title: "Un vídeo sobre agentes."
source: "https://www.youtube.com/watch?v=abc123"
channel: "Un canal"
published: 2026-10-01
duration: "499S"
kind: "video"
---
# Un vídeo sobre agentes.

Una descripción del vídeo.

## Transcript

**0:00** · What would you do if I were not real? This is the opening line of the video.
**0:03** · The agent harness is the code around the model, and it decides what the agent can do.
**1:02:03** · Near the end an hour in, the speaker closes the argument about verification.
"""


def test_a_youtube_clip_keeps_its_kind_and_gets_one_paragraph_per_transcript_line(tmp_path):
    clip = tmp_path / "Un vídeo.md"
    clip.write_text(YOUTUBE_CLIP, encoding="utf-8")

    doc = extract_source(str(clip))

    assert doc.kind == "video" and doc.url == "https://www.youtube.com/watch?v=abc123"
    # blank lines between transcript lines: the chunker then cuts between lines, never inside one
    assert "**0:00** · What would you do" in doc.text
    assert "\n\n**0:03** ·" in doc.text and "\n\n**1:02:03** ·" in doc.text


LINKEDIN = Path(__file__).parent / "fixtures" / "linkedin"
POST_HTML = (LINKEDIN / "post.html").read_text()
POST_URL = "https://www.linkedin.com/posts/marta-ejemplo_queues-activity-7300000000000000001-AbCd"
POST_KEY = "https://www.linkedin.com/feed/update/urn:li:activity:7300000000000000001"


def test_a_linkedin_post_is_read_as_the_post_and_its_author_without_the_comments(monkeypatch):
    _fake_web(monkeypatch, {POST_URL: (200, POST_HTML)})

    doc = extract_source(POST_URL)

    assert "Marta Ejemplo" in doc.title and "small queues beat big batches" in doc.title
    assert doc.text.startswith("By Marta Ejemplo\n")
    assert "A small queue that runs every hour" in doc.text
    for comment in ("bakery", "growth hacks", "Pat Sample", "Lee Testcase"):
        assert comment not in doc.text
    assert doc.warnings == []
    assert doc.url == POST_KEY  # the key the queue and the vault's duplicate check use


SHARE_URL = (
    "https://www.linkedin.com/posts/marta-ejemplo_queues-share-7300000000000000002-AbCd/"
    "?highlightedUpdateUrn=urn:li:activity:7300000000000000009&utm_medium=ios_app&rcm=AbC"
)


def test_a_linkedin_post_shared_from_the_iphone_app_is_read_as_the_post(monkeypatch):
    _fake_web(monkeypatch, {SHARE_URL: (200, POST_HTML)})

    doc = extract_source(SHARE_URL)

    assert doc.text.startswith("By Marta Ejemplo\n")
    assert "bakery" not in doc.text
    assert doc.url == "https://www.linkedin.com/feed/update/urn:li:share:7300000000000000002"


def test_a_linkedin_post_records_its_links_with_short_links_expanded(monkeypatch):
    body = (
        "The paper behind this: https://example.org/queues-paper\\n"
        "My notes: https://lnkd.in/eXmpl01 and my course: https://lnkd.in/eDead00."
    )
    html = POST_HTML.replace("The paper behind this: https://example.org/queues-paper", body)
    blog = INTERSTITIAL.replace("https://example.org/queues-paper", "https://blog.example/queues")
    asked = _fake_web(monkeypatch, {POST_URL: (200, html), LNKD: (200, blog)})

    doc = extract_source(POST_URL)

    # in the post's order; a short link that cannot be expanded is kept as it is
    assert doc.links == [
        "https://example.org/queues-paper",
        "https://blog.example/queues",
        "https://lnkd.in/eDead00",
    ]
    assert asked == [POST_URL, LNKD, "https://lnkd.in/eDead00"]  # all through safe_get


def test_a_page_that_is_not_a_linkedin_post_records_no_links(monkeypatch):
    _fake_web(monkeypatch, {"https://x.test/a": (200, ARTICLE)})

    assert extract_source("https://x.test/a").links == []


def test_a_linkedin_post_page_without_structured_data_is_still_read_with_a_warning(monkeypatch):
    bare = re.sub(r'<script type="application/ld\+json">.*?</script>', "", POST_HTML, flags=re.S)
    _fake_web(monkeypatch, {POST_URL: (200, bare)})

    doc = extract_source(POST_URL)

    assert "A small queue that runs every hour" in doc.text
    assert doc.warnings and "comments" in doc.warnings[0]
    assert doc.url == POST_KEY


LNKD = "https://lnkd.in/eXmpl01"
INTERSTITIAL = (LINKEDIN / "lnkd_interstitial.html").read_text()


def test_a_lnkd_in_link_is_followed_past_linkedins_leaving_page(monkeypatch):
    paper = "https://example.org/queues-paper"
    asked = _fake_web(monkeypatch, {LNKD: (200, INTERSTITIAL), paper: (200, ARTICLE)})

    doc = extract_source(LNKD)

    assert asked == [LNKD, paper]  # both through safe_get
    assert "Párrafo número 3" in doc.text and doc.url == paper


def test_a_lnkd_in_page_without_an_outbound_link_is_an_error_not_a_document(monkeypatch):
    no_link = re.sub(r"<a [^>]*external_url_click.*?</a>", "", INTERSTITIAL, flags=re.S)
    _fake_web(monkeypatch, {LNKD: (200, no_link)})

    with pytest.raises(ExtractError, match="no outbound link"):
        extract_source(LNKD)


def test_a_lnkd_in_link_to_a_linkedin_post_is_read_as_a_post(monkeypatch):
    to_post = INTERSTITIAL.replace("https://example.org/queues-paper", POST_URL)
    _fake_web(monkeypatch, {LNKD: (200, to_post), POST_URL: (200, POST_HTML)})

    doc = extract_source(LNKD)

    assert doc.text.startswith("By Marta Ejemplo\n") and "bakery" not in doc.text


def test_a_lnkd_in_link_that_comes_back_to_lnkd_in_is_an_error_not_a_loop(monkeypatch):
    """The outbound page redirects to a short link again: following it would never end."""
    import httpx

    from esbi_cli import extract

    bounce = INTERSTITIAL.replace("https://example.org/queues-paper", "https://example.org/bounce")
    asked = []

    def fake_safe_get(url, *, client=None, resolver=None, headers=None, timeout_seconds=30):
        asked.append(url)
        # safe_get follows redirects itself: /bounce ends on the short link it came from
        final = LNKD if url == "https://example.org/bounce" else url
        return httpx.Response(200, text=bounce, request=httpx.Request("GET", final))

    monkeypatch.setattr(extract, "safe_get", fake_safe_get)

    with pytest.raises(ExtractError, match="short link"):
        extract_source(LNKD)
    assert len(asked) == 2


@pytest.mark.parametrize(
    "target, expected",
    [
        ("linkedin.com/posts/a-share-1/?x=1", "https://linkedin.com/posts/a-share-1/?x=1"),
        ("www.example.test/page", "https://www.example.test/page"),
        ("https://example.test/page", "https://example.test/page"),
        ("notes.md", "notes.md"),  # a file name, not a host
        ("paper.pdf/", "paper.pdf/"),
        ("docs/paper.pdf", "docs/paper.pdf"),
        ("example.test", "example.test"),  # no path: too likely a file name
    ],
)
def test_a_link_pasted_without_https_is_read_as_one(target, expected):
    assert with_scheme(target) == expected


def test_an_existing_file_that_looks_like_a_link_stays_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "example.test").mkdir()
    (tmp_path / "example.test" / "page").write_text("x")

    assert with_scheme("example.test/page") == "example.test/page"
