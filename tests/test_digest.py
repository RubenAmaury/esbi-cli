"""Long sources: the terms, quotes and diagram come from the chunk notes (code), the detailed
summary from a second, focused model call. Small models fail at one giant plan."""

import json

import pytest
from conftest import FakeLLM, make_plan
from pydantic import ValidationError

from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.chunks import split_chunks
from esbi_cli.ingest.digest import INSTRUCTIONS
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.llm.adapter import LLMTimeout
from esbi_cli.llm.schemas import Digest

QUOTE = "La verificación cierra el bucle entre el modelo y el mundo real"


def long_doc():
    paragraphs = [
        f"Sección {n}. El arnés de código gestiona el contexto y la memoria del agente. "
        f"{QUOTE}. " * 3
        for n in range(20)
    ]
    return ExtractedDoc("Un artículo largo", "\n\n".join(paragraphs), "article", "https://x.test/l")


def chunk_notes(n):
    return {
        "points": [f"Dato concreto {n}: el arnés mejora la fiabilidad."],
        "terms": [
            {"term": "arnés de código", "definition": "La capa de código que rodea al modelo."}
        ],
        "quotes": [QUOTE, "Esta frase no está en el texto original de ninguna manera."],
        "relations": [{"a": "Arnés", "relation": "gestiona", "b": f"Sección {n}"}],
    }


DIGEST = {
    "paragraphs": ["El problema: los modelos solos fallan. " * 4] * 3,
    "insights": [
        {"idea": "La verificación cierra el bucle.", "why": "Sin ella los errores se acumulan."}
    ],
    "open_questions": ["¿Cómo se mide la fiabilidad de un arnés?"],
}


def run(vault, cfg, llm, doc=None):
    doc = doc or long_doc()
    return ingest("x", vault=vault, llm=llm, cfg=cfg, extractor=lambda _: doc, today=None)


def n_chunks(cfg):
    return len(split_chunks(long_doc().text, cfg.chunk_chars, cfg.max_chunks))


def payloads(cfg, digest=DIGEST, plan=None):
    notes = [chunk_notes(i) for i in range(n_chunks(cfg))]
    return [*notes, plan or make_plan(title="Un artículo largo"), digest]


def body(vault, result):
    return vault.read_page(result.applied.source_path).body


def test_terms_quotes_and_the_diagram_come_from_the_chunk_notes_not_from_the_synthesis(vault, cfg):
    llm = FakeLLM(*payloads(cfg))

    result = run(vault, cfg, llm)

    text = body(vault, result)
    assert "**arnés de código**" in text and text.count("arnés de código**") == 1  # merged
    assert f'> "{QUOTE}"' in text and "Esta frase no está" not in text
    assert "```mermaid" in text and "gestiona" in text
    synthesis = llm.calls[n_chunks(cfg)]["system"]  # after the chunk notes: the core plan
    assert "`terms`" not in synthesis and "`abstract`" not in synthesis


def test_a_focused_second_call_writes_the_detailed_summary_and_the_key_ideas(vault, cfg):
    llm = FakeLLM(*payloads(cfg))

    result = run(vault, cfg, llm)

    text = body(vault, result)
    assert "## Resumen detallado" in text and "El problema: los modelos solos fallan." in text
    assert "## Ideas clave" in text and "**La verificación cierra el bucle.**" in text
    assert "## Preguntas abiertas" in text
    digest_prompt = llm.calls[n_chunks(cfg) + 1]["user"]
    assert "<chunk_notes " in digest_prompt and "Dato concreto 0" in digest_prompt
    assert "El artículo explica" not in digest_prompt  # the executive summary would be copied


def test_a_digest_that_stays_invalid_leaves_the_note_without_it_and_says_so(vault, cfg):
    llm = FakeLLM(*payloads(cfg, digest="no es json"), "otra vez mal", "y otra más")

    result = run(vault, cfg, llm)

    text = body(vault, result)
    assert result.status == "ingested" and "## Resumen detallado" not in text
    assert "## Puntos clave" in text  # the core plan's key points still carry the note
    assert any("detailed summary" in w and "JSON" in w for w in result.warnings)


def test_a_digest_that_times_out_is_a_warning_not_a_failure(vault, cfg):
    llm = FakeLLM(*payloads(cfg, digest=LLMTimeout("timed out")))

    result = run(vault, cfg, llm)

    assert result.status == "ingested" and any("detailed summary" in w for w in result.warnings)


def test_a_placeholder_one_liner_copied_from_the_prompt_is_replaced_by_the_summary(vault, cfg):
    plan = make_plan(title="Un artículo largo", one_liner="Resumen ejecutivo de la fuente")
    llm = FakeLLM(*payloads(cfg, plan=plan))

    result = run(vault, cfg, llm)

    assert (
        vault.read_page(result.applied.source_path)
        .meta["summary"]
        .startswith("El artículo explica")
    )


def test_the_digest_asks_for_the_language_and_retries_once_when_it_answers_in_english(vault, cfg):
    english = {
        **DIGEST,
        "paragraphs": ["The problem is that the models alone fail to do the work. " * 4] * 3,
    }
    llm = FakeLLM(*payloads(cfg, digest=english), DIGEST)

    result = run(vault, cfg, llm)

    assert "El problema: los modelos" in body(vault, result) and len(llm.calls) == n_chunks(cfg) + 3
    assert json.loads(json.dumps(DIGEST))  # sanity: fixture is plain JSON


def test_a_digest_cut_off_mid_answer_is_retried_asking_for_a_shorter_one(vault, cfg):
    """A small model sometimes loops inside the abstract until the token cap truncates the JSON."""
    llm = FakeLLM(
        *payloads(cfg, digest='{"paragraphs": ["El problema: los modelos solos fal'), DIGEST
    )

    result = run(vault, cfg, llm)

    assert "## Resumen detallado" in body(vault, result) and result.warnings == []
    retry = llm.calls[-1]["user"]
    assert "Be shorter" in retry and "3 short paragraphs" in retry


def test_the_abstract_is_asked_for_as_a_short_list_of_paragraphs_so_it_cannot_run_on():
    """Measured on llama3.2 (blog and wiki sources, 20 digest calls): the abstract as one string
    with no bound never closed in 5 of 20 calls (it repeated paragraphs until the token cap); as a
    list of at most 5 paragraphs the same prompts gave 0 failures in 10. (A `maxLength` on the
    string is no way out: Ollama's grammar for it crashed the model runner.)"""
    properties = Digest.model_json_schema()["properties"]

    assert properties["paragraphs"]["type"] == "array"
    assert properties["paragraphs"]["minItems"] == 3 and properties["paragraphs"]["maxItems"] == 4
    assert "abstract" not in properties
    abstract = Digest.model_validate(DIGEST).abstract
    assert abstract == "\n\n".join(p.strip() for p in DIGEST["paragraphs"])


def test_the_whole_digest_is_asked_for_in_a_size_that_fits_a_small_models_token_cap():
    """With a closed abstract and up to 8 key ideas, each a long sentence and its consequence, the
    digest of the Wikipedia article on Zettelkasten still hit llama3.2's 1200-token cap before the
    JSON closed in 5 of 10 calls; up to 6, one short sentence each, is what fits."""
    assert Digest.model_json_schema()["properties"]["insights"]["maxItems"] == 6
    assert "4-6 key ideas" in INSTRUCTIONS and "one short sentence" in INSTRUCTIONS


def test_a_digest_with_too_little_to_read_is_invalid_so_the_shorter_retry_cannot_hide_it():
    thin = {**DIGEST, "paragraphs": ["Corto.", "Corto.", "Corto."]}

    with pytest.raises(ValidationError, match="too short"):
        Digest.model_validate(thin)
