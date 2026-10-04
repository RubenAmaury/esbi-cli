"""The prompts are English; the language of the output is a sentence in them, per language."""

import json
import re

import pytest
from conftest import FakeLLM, add_source, english_plan
from conftest import make_plan as plan_dict

from esbi_cli import lang
from esbi_cli.ask.answer import answer_question, rewrite_question
from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.connect import connect
from esbi_cli.ingest.digest import make_digest
from esbi_cli.ingest.plan import build_prompt, make_plan
from esbi_cli.ingest.read import read_chunks
from esbi_cli.llm.schemas import ChunkNotes, ConnectionPlan, Digest, EditPlan

DOC = ExtractedDoc(
    "A title", "Some text about agents and harnesses. " * 20, "article", "https://x.test"
)
SPANISH_WORDS = re.compile(r"[áéíóúñ¿¡]|\b(?:fuente|páginas|resumen|escribe|pregunta)\b", re.I)


@pytest.mark.parametrize(("code", "name"), [("en", "English"), ("es", "Spanish")])
def test_the_plan_prompt_names_the_output_language_and_is_otherwise_english(code, name):
    system, user = build_prompt("# SCHEMA", DOC, [], 4000, language=code)
    assert f"Write ALL text in {name}" in system
    assert not SPANISH_WORDS.search(system)
    assert "<existing_pages>" in user and "(none yet)" in user and "<source " in user


def test_the_language_is_repeated_at_the_end_of_the_plan_request_where_a_small_model_listens():
    """Measured with llama3.2 3B: said only in the system prompt, an English source was answered in
    Spanish in 3 of 4 cases for English output; repeated after the source, in none."""
    for notes in (None, [ChunkNotes(points=["a fact about agents"])]):
        _, user = build_prompt("# SCHEMA", DOC, [], 4000, notes=notes, language="en")
        assert user.endswith(lang.instruction("en"))


def test_a_language_added_as_data_reaches_every_prompt(monkeypatch):
    monkeypatch.setitem(
        lang.LANGUAGES, "tlh", {**lang.LANGUAGES["en"], "name": "Klingon", "stopwords": ""}
    )
    system, _ = build_prompt("# SCHEMA", DOC, [], 4000, language="tlh")
    assert "Write ALL text in Klingon" in system

    llm = FakeLLM(json.dumps({"points": ["one", "two"]}))
    read_chunks(llm, "T", ["chunk"], language="tlh")
    assert "Klingon" in llm.calls[0]["system"]

    llm = FakeLLM(json.dumps({"terms": []}))
    rewrite_question(llm, "what?", language="tlh")
    assert "Klingon" in llm.calls[0]["system"]


def test_a_per_language_hint_is_appended_to_the_instruction(monkeypatch):
    monkeypatch.setitem(
        lang.LANGUAGES, "es", {**lang.LANGUAGES["es"], "hint": "Use natural Spanish."}
    )
    system, _ = build_prompt("# SCHEMA", DOC, [], 4000, language="es")
    assert "Use natural Spanish." in system


def test_the_chunk_reading_prompt_names_the_language():
    notes = {"points": ["a fact one", "a fact two"]}
    llm = FakeLLM(json.dumps(notes))
    read_chunks(llm, "T", ["chunk text"], language="es")
    system = llm.calls[0]["system"]
    assert "Write ALL text in Spanish" in system and "part 1 of 1" in system
    assert '"mejora"' in system or "amplía" in system  # the relation labels are in the language
    assert "<chunk part 1 of 1>" in llm.calls[0]["user"]


def test_the_digest_prompt_names_the_language_and_retries_in_the_right_one():
    english = json.dumps(
        {
            "abstract": "This is a long abstract about agents. " * 8,
            "insights": [{"idea": "An idea about the harness.", "why": "It matters for the user."}],
        }
    )
    spanish = json.dumps(
        {
            "abstract": "Este es un resumen largo sobre los agentes y el arnés de código. " * 6,
            "insights": [
                {"idea": "Una idea sobre el arnés de código.", "why": "Importa para el usuario."}
            ],
        }
    )
    llm = FakeLLM(spanish, english)
    plan = EditPlan.model_validate(english_plan())
    notes = [ChunkNotes(points=["something about agents"])]

    digest, warnings = make_digest(llm, DOC, plan, notes, "en")

    assert len(llm.calls) == 2 and warnings == [] and digest is not None
    assert "Write ALL text in English" in llm.calls[0]["system"]
    assert "must be written entirely in English" in llm.calls[1]["user"]


def test_the_connect_prompt_names_the_language(vault):
    add_source(vault, "Harness page", summary="About harnesses and agents.")
    plan = EditPlan.model_validate(english_plan())
    llm = FakeLLM(json.dumps({"connections": []}))
    connect(llm, vault, plan)
    assert "Write ALL text in Spanish" in llm.calls[0]["system"]  # the fixture vault is Spanish
    assert "<new_source" in llm.calls[0]["user"] and "(no summary)" not in llm.calls[0]["user"]


@pytest.mark.parametrize(
    ("code", "example"), [("en", '"cited_pages": ["Graph"'), ("es", '"cited_pages": ["Grafo"')]
)
def test_the_ask_prompt_shows_the_worked_example_in_the_output_language(vault, code, example):
    vault.language = code
    add_source(
        vault, "Harness", summary="About harnesses.", body="# Harness\n\nAgents use a harness."
    )
    page = vault.read_page(vault.page_path("sources", "Harness"))
    page.meta["title"] = "Harness"
    vault.write_page(page)
    answer = json.dumps(
        {
            "title": "Harness",
            "one_liner": "A harness runs the agent.",
            "answer": "A harness runs the agent [[Harness]], as the page says.",
            "cited_pages": ["Harness"],
        }
    )
    llm = FakeLLM(answer)
    answer_question(vault, llm, "What is a harness?")
    system = llm.calls[0]["system"]
    assert example in system and f"Write ALL text in {lang.name(code)}" in system
    assert "<question>What is a harness?</question>" in llm.calls[0]["user"]


def test_the_rewrite_prompt_asks_for_the_notes_language_and_english():
    llm = FakeLLM(json.dumps({"terms": ["a", "b"]}), json.dumps({"terms": []}))
    rewrite_question(llm, "¿Qué es un juez?", language="es")
    rewrite_question(llm, "q", language="en")
    assert "translation into Spanish and English," in llm.calls[0]["system"]
    assert "translation into English," in llm.calls[1]["system"]


def test_the_wrong_language_retry_names_the_wanted_language_and_is_given_up_after_one():
    spanish = json.dumps(plan_dict())
    llm = FakeLLM(spanish, spanish)
    plan, warnings = make_plan(llm, "sys", "user", "en")
    assert plan.title and len(llm.calls) == 2
    assert "must be written entirely in English" in llm.calls[1]["user"]
    assert len(warnings) == 1 and warnings[0].startswith(
        "The model answered in the wrong language (wanted English):"
    )


def test_a_language_without_stopwords_is_not_checked_so_there_is_no_retry(monkeypatch):
    monkeypatch.setitem(
        lang.LANGUAGES, "tlh", {**lang.LANGUAGES["en"], "name": "Klingon", "stopwords": ""}
    )
    llm = FakeLLM(json.dumps(plan_dict()))
    _, warnings = make_plan(llm, "sys", "user", "tlh")
    assert len(llm.calls) == 1 and warnings == []


@pytest.mark.parametrize("model", [EditPlan, ChunkNotes, Digest, ConnectionPlan])
def test_what_the_schemas_tell_the_model_is_english_and_names_no_output_language(model):
    text = json.dumps(model.model_json_schema())
    assert not SPANISH_WORDS.search(text)
    assert "English" not in text and "Spanish" not in text
