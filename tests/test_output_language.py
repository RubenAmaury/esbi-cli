"""The language of the wiki is a setting: English notes, and vaults that mix both languages."""

from datetime import date, datetime

import pytest
from conftest import FakeLLM, add_source, english_plan, make_plan

from esbi_cli.ask.answer import Answer, answer_question, page_context, save_answer
from esbi_cli.bench.report import render_report
from esbi_cli.export import export_site
from esbi_cli.extract import ExtractedDoc, Figure
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.lint.checks import lint_vault
from esbi_cli.lint.report import write_lint_report
from esbi_cli.mail.convert import email_to_clip
from esbi_cli.privacy import public_body
from esbi_cli.reingest import reingest_all
from esbi_cli.report.daily_index import build_daily_index
from esbi_cli.report.index_md import rebuild_index
from esbi_cli.report.readstate import sync_read_state

TODAY = date(2026, 10, 3)
TEXT = (
    "Agents use a code harness to plan and run tools. The harness manages context, memory and "
    "the verification of results. Anthropic publishes examples of agent harnesses. " * 4
)
QUOTE = "The harness manages context, memory and the verification of results."


@pytest.fixture
def en(vault, cfg):
    vault.language = cfg.language = "en"
    return vault


def english_doc():
    return ExtractedDoc("Agent harness", TEXT, "article", "https://x.test/a")


def run(vault, cfg, llm, doc=None):
    doc = doc or english_doc()
    return ingest(
        "x", vault=vault, llm=llm, cfg=cfg, extractor=lambda _: doc, today=TODAY, force=True
    )


def headings(page):
    return [line[3:] for line in page.body.splitlines() if line.startswith("## ")]


def test_an_english_vault_writes_english_headings_labels_and_index(en, cfg):
    run(en, cfg, FakeLLM(english_plan()))

    note = en.read_page(en.page_path("sources", "Agent harness"))
    assert headings(note) == [
        "Executive summary",
        "Detailed summary",
        "Key ideas",
        "Key terms",
        "Key quotes",
        "Open questions",
        "Concepts",
    ]
    assert "> Original source: https://x.test/a" in note.body
    concept = en.read_page(en.page_path("concepts", "Code harness"))
    assert "## From [[Agent harness]]" in concept.body
    assert (en.root / "index.md").read_text().startswith("# Index\n")
    assert "## Sources (1)" in (en.root / "index.md").read_text()
    assert "created: Agent harness" in (en.root / "log.md").read_text()


def test_the_spanish_note_keeps_its_spanish_headings(vault, cfg, doc):
    ingest("x", vault=vault, llm=FakeLLM(make_plan()), cfg=cfg, extractor=lambda _: doc)
    note = vault.read_page(vault.page_path("sources", "Arnés de agentes"))
    assert "## Resumen ejecutivo" in note.body and "> Fuente original: " in note.body


def test_a_model_that_answers_in_the_other_language_is_retried_once(en, cfg):
    spanish = make_plan()  # the Spanish plan of the fixtures, for an English vault
    llm = FakeLLM(spanish, english_plan())
    result = run(en, cfg, llm)
    assert len(llm.calls) == 2 and "must be written entirely in English" in llm.calls[1]["user"]
    assert result.warnings == []


def test_email_sections_are_stripped_whichever_language_wrote_them():
    body = (
        "# C\n\n## Desde [[Correo A]]\nsecreto uno\n\n## From [[Correo B]]\nsecret two\n\n"
        "## From [[Public]]\nopen text"
    )
    stripped = public_body(body, {"Correo A", "Correo B"})
    assert "secreto" not in stripped and "secret" not in stripped
    assert "open text" in stripped


def test_reingest_into_another_language_swaps_that_notes_sections_and_keeps_the_others(vault, cfg):
    shared = {"title": "Compartido", "aliases": [], "description": "Una idea que usan los agentes."}
    for name in ("Fuente A", "Fuente B"):
        doc = ExtractedDoc(name, f"Texto de la {name} sobre agentes. " * 30, "article", name)
        plan = make_plan(title=name, concepts=[shared], entities=[])
        ingest("x", vault=vault, llm=FakeLLM(plan), cfg=cfg, extractor=lambda _, d=doc: d)

    vault.language = cfg.language = "en"  # the user switches the setting...
    english = {**shared, "description": "An idea that the agents use for the user."}
    plan = english_plan(title="Fuente A", concepts=[english])
    result = reingest_all(vault, FakeLLM(plan), None, cfg, only=["Fuente A"])  # ...and rebuilds one

    assert result.done == ["Fuente A"], result
    note = vault.read_page(vault.page_path("sources", "Fuente A"))
    assert "## Executive summary" in note.body and "Resumen ejecutivo" not in note.body
    body = vault.read_page(vault.page_path("concepts", "Compartido")).body
    assert body.count("[[Fuente A]]") == 1 and "## From [[Fuente A]]" in body
    assert "## Desde [[Fuente B]]" in body  # the other note is still the Spanish one it was
    assert "## Desde [[Fuente A]]" not in body


def test_sb_ask_picks_the_most_useful_sections_of_a_note_written_in_either_language():
    body = (
        "# N\n\n## Detailed summary\n" + "filler " * 60 + "\n\n## Ideas clave\n- idea\n\n"
        "## Executive summary\nThe point.\n\n## Key terms\n- **x**: y"
    )
    context = page_context(body, 150)
    assert "The point." in context and "- idea" in context and "filler" not in context


def test_a_tick_in_a_daily_note_marks_the_source_read_whatever_language_its_headings_are(vault):
    add_source(vault, "Nota A")
    add_source(vault, "Nota B")
    (vault.wiki / "daily" / "2026-10-01.md").write_text("## Processed today\n- [x] [[Nota A]]\n")
    (vault.wiki / "daily" / "2026-10-02.md").write_text("## Procesado hoy\n- [x] [[Nota B]]\n")
    assert sync_read_state(vault, TODAY) == ["Nota A", "Nota B"]


def test_the_daily_index_and_home_follow_the_language(en, queue):
    add_source(en, "New one", summary="About agents.", processed="2026-10-03")
    text = build_daily_index(en, queue, TODAY).read_text(encoding="utf-8")
    for heading in (
        "# Index of 2026-10-03",
        "## Read",
        "## Processed today",
        "## Tomorrow's queue",
        "## To review",
        "## Revisit",
        "## Runs",
        "## Statistics",
    ):
        assert heading in text
    assert "- [ ] [[New one]] — About agents." in text
    assert "_The queue is empty._" in text and "- Orphans (no incoming links): " in text
    assert "- Today's index: [[2026-10-03]]" in (en.root / "Home.md").read_text()


def test_the_lint_report_follows_the_language(en):
    add_source(en, "Lonely")
    path = write_lint_report(en, lint_vault(en), TODAY)
    text = path.read_text(encoding="utf-8")
    assert "# Lint report (2026-10-03)" in text and "## Orphan pages" in text
    assert "El worker" not in text and "The worker only reports" in text


def test_the_bench_report_follows_the_language():
    text = render_report([], {"ingest": None, "ask": None}, datetime(2026, 10, 3, 9, 0), "en")
    assert "# Model benchmark (2026-10-03 09:00)" in text
    assert "## Routing recommendation" in text and "no recommendation" in text


def test_an_answer_refuses_and_a_saved_answer_is_written_in_the_language(en):
    llm = FakeLLM()
    answer = answer_question(en, llm, "What is a quantum flux?")
    assert not answer.grounded and answer.text == "I find nothing about this in the wiki."

    add_source(en, "Source one")
    grounded = Answer(
        "What is it?", True, "It is a thing [[Source one]].", "A thing", "A thing.", ["Source one"]
    )
    page = en.read_page(save_answer(en, grounded, TODAY))
    assert "> Question: What is it?" in page.body and "## Sources" in page.body


def test_the_exported_site_names_its_language_and_its_sections(en, tmp_path):
    add_source(en, "Source one")
    export_site(en, tmp_path / "site")
    index = (tmp_path / "site" / "index.html").read_text()
    assert '<html lang="en">' in index and "<h2>Sources (1)</h2>" in index


def test_the_index_title_follows_the_language(en):
    rebuild_index(en)
    assert (en.root / "index.md").read_text().startswith("# Index")
    en.language = "es"
    rebuild_index(en)
    assert (en.root / "index.md").read_text().startswith("# Índice")


def test_a_picture_and_a_mail_without_a_subject_get_their_default_names_in_the_language(en, cfg):
    doc = ExtractedDoc("Agent harness", TEXT, "article", "https://x.test/a")
    doc.figures = [Figure(data=b"png", page=0)]  # an image source: it is not a page of anything
    doc.image_links = [("", "https://x.test/pic.png")]
    run(en, cfg, FakeLLM(english_plan()), doc)
    body = en.read_page(en.page_path("sources", "Agent harness")).body
    assert "*Image*" in body and "![Image](https://x.test/pic.png)" in body

    raw = b"From: a@x.test\nMessage-ID: <1@x.test>\nDate: Fri, 03 Oct 2026 10:00:00 +0000\n\nHello there."
    assert email_to_clip(raw, "en").filename.endswith("No subject.md")
    assert email_to_clip(raw, "es").filename.endswith("Sin asunto.md")
