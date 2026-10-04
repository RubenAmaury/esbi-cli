"""English leaking into notes written in another language: every field is checked, not only the
abstract, and the retry says which field to fix."""

import json

from conftest import FakeLLM
from conftest import make_plan as plan_dict

from esbi_cli import lang
from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.digest import make_digest
from esbi_cli.ingest.plan import make_plan
from esbi_cli.llm.schemas import ChunkNotes, EditPlan

EN = "The model is used for this task and the results are good for the users in that case."
ES = "El modelo se usa para esta tarea y los resultados son buenos para los usuarios en ese caso."
DOC = ExtractedDoc("Un título", "Texto sobre agentes y arneses. " * 20, "article", "https://x.test")
NOTES = [ChunkNotes(points=["algo sobre agentes"])]
PLAN = EditPlan.model_validate(plan_dict())


def digest(**overrides) -> str:
    fields = {
        "abstract": (ES + "\n\n") * 4,
        "insights": [{"idea": ES, "why": "Importa para el usuario y para los resultados."}],
        "open_questions": [ES],
    }
    return json.dumps({**fields, **overrides})


def test_a_short_field_is_judged_with_fewer_stopwords_and_each_field_on_its_own():
    assert lang.leaking([("insights", EN), ("abstract", ES), ("insights", EN)], "es") == [
        "insights"
    ]
    assert lang.leaking([("glossary", "A short English definition for the term.")], "es") == [
        "glossary"
    ]


def test_a_language_without_a_word_list_is_skipped_not_guessed(monkeypatch):
    monkeypatch.setitem(lang.LANGUAGES, "xx", {**lang.LANGUAGES["en"], "stopwords": ""})
    assert lang.leaking([("insights", ES)], "xx") == []


def test_one_english_paragraph_in_a_spanish_abstract_is_caught_and_the_retry_names_it():
    leaky = digest(abstract=ES + "\n\n" + EN + "\n\n" + ES + "\n\n" + ES)
    llm = FakeLLM(leaky, digest())

    result, warnings = make_digest(llm, DOC, PLAN, NOTES, "es")

    assert result is not None and warnings == [] and len(llm.calls) == 2
    retry = llm.calls[1]["user"]
    assert "`abstract`" in retry and "entirely in Spanish" in retry and "`insights`" not in retry


def test_english_key_ideas_and_open_questions_are_caught_too():
    english = {"idea": EN, "why": "It matters for the user and for the results of this."}
    llm = FakeLLM(digest(insights=[english], open_questions=[EN]), digest())

    result, warnings = make_digest(llm, DOC, PLAN, NOTES, "es")

    assert warnings == [] and result.insights[0].idea == ES
    assert "`insights`" in llm.calls[1]["user"] and "`open_questions`" in llm.calls[1]["user"]


def test_a_field_that_keeps_leaking_after_the_retries_is_named_in_the_warning():
    llm = FakeLLM(*[digest(open_questions=[EN])] * 3)

    result, warnings = make_digest(llm, DOC, PLAN, NOTES, "es")

    assert result is not None and len(llm.calls) == 3  # kept: the rest of the digest is fine
    assert (
        len(warnings) == 1 and "wrong language" in warnings[0] and "open_questions" in warnings[0]
    )


def test_a_digest_in_a_language_without_a_word_list_is_not_retried(monkeypatch):
    monkeypatch.setitem(lang.LANGUAGES, "xx", {**lang.LANGUAGES["en"], "stopwords": ""})
    llm = FakeLLM(digest(open_questions=[EN]))

    _, warnings = make_digest(llm, DOC, PLAN, NOTES, "xx")

    assert len(llm.calls) == 1 and warnings == []


def test_an_english_executive_summary_among_spanish_text_is_caught_and_named():
    """Joined with the long Spanish concept descriptions, the English summary used to pass."""
    long_es = " ".join([ES] * 6)
    leaky = plan_dict(
        summary=EN + " " + EN,
        key_points=[ES, ES],
        concepts=[{"title": "Arnés", "aliases": [], "description": long_es}],
    )
    llm = FakeLLM(json.dumps(leaky), json.dumps(plan_dict()))

    plan, warnings = make_plan(llm, "sys", "user", "es")

    assert warnings == [] and len(llm.calls) == 2 and plan.summary.startswith("El artículo")
    assert "`summary`" in llm.calls[1]["user"] and "`key_points`" not in llm.calls[1]["user"]


def test_a_plan_that_keeps_leaking_names_the_fields_in_the_warning():
    leaky = json.dumps(plan_dict(summary=EN + " " + EN))

    _, warnings = make_plan(FakeLLM(leaky, leaky), "sys", "user", "es")

    assert len(warnings) == 1 and "wrong language" in warnings[0] and "summary" in warnings[0]
