"""A source longer than the chunk reader's limit is read in full: chunk notes are merged into
section notes, and the final note is written from those, never from raw text."""

import hashlib
from dataclasses import replace
from datetime import date

from conftest import FakeLLM, make_plan

from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest

TODAY = date(2026, 9, 29)
QUOTE = "La verificación cierra el bucle entre el modelo y el mundo real"
DIGEST = {
    "paragraphs": ["El problema: los modelos solos fallan. " * 4] * 3,
    "insights": [
        {"idea": "La verificación cierra el bucle.", "why": "Sin ella los errores se acumulan."}
    ],
    "open_questions": ["¿Cómo se mide la fiabilidad de un arnés?"],
}


def book(sections: int) -> ExtractedDoc:
    """`sections` paragraphs of about 520 characters each, one per chunk when chunk_chars=600."""
    text = "\n\n".join(
        f"Sección {n}. El arnés de código gestiona el contexto y la memoria del agente. "
        f"{QUOTE}. " * 3
        for n in range(sections)
    )
    return ExtractedDoc("Un libro largo", text, "article", "https://x.test/libro")


def chunk_notes(n):
    return {
        "points": [f"Dato concreto {n}: el arnés mejora la fiabilidad."],
        "terms": [{"term": "arnés de código", "definition": "La capa de código que rodea al modelo."}],
        "quotes": [QUOTE],
        "relations": [{"a": "Arnés", "relation": "gestiona", "b": f"Sección {n}"}],
    }


def run(vault, cfg, llm, doc, **kw):
    steps = []
    result = ingest(
        "x", vault=vault, llm=llm, cfg=cfg, extractor=lambda _: doc, today=TODAY,
        on_step=steps.append, **kw,
    )  # fmt: skip
    return result, steps


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_a_source_that_fits_the_chunk_limit_is_read_exactly_as_before(vault, cfg):
    """Pins the behaviour of 0.3.0 for a source of at most `max_chunks` chunks: one call per chunk,
    then the plan and the digest, the same prompts, the same steps, the same note."""
    cfg = replace(cfg, max_source_chars=1000, chunk_chars=600, max_chunks=16)
    doc = book(10)
    llm = FakeLLM(*[chunk_notes(n) for n in range(10)], make_plan(title="Un libro largo"), DIGEST)

    result, steps = run(vault, cfg, llm, doc)

    prompts = "\n".join(f"{c['system']}\n{c['user']}" for c in llm.calls)
    body = vault.read_page(result.applied.source_path).body
    assert (len(llm.calls), steps[0], steps[-2:]) == (
        12,
        "chunk 1 of 10",
        ["synthesis", "detailed summary"],
    )
    assert (sha(prompts), sha(body), result.warnings) == ("c315ae52f2a522e1", "69ae4e57397c6ab2", [])
