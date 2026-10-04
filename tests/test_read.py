import json

from conftest import FakeLLM

from esbi_cli.ingest.read import read_chunks
from esbi_cli.llm.adapter import LLMTimeout


def notes(tag):
    return {
        "points": [f"Dato concreto {tag}: el método mejora el resultado en un 12%."],
        "terms": [{"term": f"Término {tag}", "definition": "Una definición corta en una frase."}],
        "quotes": [f"Frase textual {tag} del fragmento."],
        "relations": [{"a": f"Idea {tag}", "relation": "mejora", "b": "Resultado"}],
    }


def test_every_chunk_is_read_in_order_and_its_position_is_told_to_the_model():
    llm, steps = FakeLLM(notes("a"), notes("b"), notes("c")), []

    result, warnings = read_chunks(
        llm,
        "Un artículo",
        ["texto uno", "texto dos", "texto tres"],
        on_step=steps.append,
        language="es",
    )

    assert [n.points[0][:16] for n in result] == [
        "Dato concreto a:",
        "Dato concreto b:",
        "Dato concreto c:",
    ]
    assert warnings == [] and len(steps) == 3 and steps[1] == "chunk 2 of 3"
    assert "part 2 of 3" in llm.calls[1]["user"] and "texto dos" in llm.calls[1]["user"]
    assert "Un artículo" in llm.calls[0]["system"] + llm.calls[0]["user"]


def test_a_bad_answer_is_retried_once_and_a_chunk_that_keeps_failing_is_skipped_not_fatal():
    llm = FakeLLM(
        "no es json",  # chunk 1, first try
        notes("a"),  # chunk 1, retry: fine
        json.dumps({"points": []}),  # chunk 2, first try: invalid (needs at least one point)
        "otra vez mal",  # chunk 2, retry: still bad
        notes("c"),  # chunk 3
    )

    result, warnings = read_chunks(llm, "Un artículo", ["uno", "dos", "tres"], language="es")

    assert [n.points[0][-30:] for n in result] == [
        notes("a")["points"][0][-30:],
        notes("c")["points"][0][-30:],
    ]
    assert len(warnings) == 1 and "chunk 2 of 3" in warnings[0]  # tells which chunk
    assert "otra vez mal" not in warnings[0] and "JSON" in warnings[0]  # and why, in short


def test_a_chunk_that_times_out_is_skipped_at_once_and_the_rest_are_still_read():
    llm = FakeLLM(notes("a"), LLMTimeout("timed out"), notes("c"))

    result, warnings = read_chunks(llm, "Un artículo", ["uno", "dos", "tres"], language="es")

    assert len(result) == 2 and len(llm.calls) == 3  # no retry: it would burn another timeout
    assert warnings == ["Could not read chunk 2 of 3; skipped (the model took too long)."]
