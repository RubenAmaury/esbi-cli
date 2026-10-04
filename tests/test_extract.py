import re

import pymupdf
import pytest

from esbi_cli.extract import ExtractError, extract_source, is_url
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


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontsize=11)
    return doc.tobytes()


def test_extract_html_returns_title_and_body_without_boilerplate():
    doc = extract_html(ARTICLE, "https://x.test/a")
    assert doc.title == "Un gran artículo" and doc.kind == "article"
    assert "Párrafo número 3" in doc.text and "menu menu" not in doc.text


def test_extract_html_rejects_pages_without_content():
    with pytest.raises(ExtractError):
        extract_html("<html><body><p>hola</p></body></html>", "https://x.test/")


def test_extract_pdf_returns_text_and_keeps_bytes():
    data = make_pdf("Attention is all you need. " * 30)
    doc = extract_pdf_bytes(data, fallback_title="attention-paper")
    assert doc.kind == "paper" and "Attention" in doc.text and doc.pdf_bytes == data
    assert doc.title == "attention paper"


def test_extract_source_reads_local_pdf_and_rejects_other_files(tmp_path):
    pdf = tmp_path / "Mi_Paper.pdf"
    pdf.write_bytes(make_pdf("Contenido del paper. " * 30))
    assert extract_source(str(pdf)).title == "Mi Paper"
    with pytest.raises(ExtractError):
        extract_source(str(tmp_path / "missing.pdf"))
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(ExtractError, match="Unsupported"):
        extract_source(str(txt))


def test_is_url():
    assert is_url("https://a.b/c") and not is_url("/tmp/a.pdf") and not is_url("file:///a")


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

    def fake_safe_get(url, **kwargs):
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
