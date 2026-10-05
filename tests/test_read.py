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


LONG = (
    "Primer párrafo del fragmento, con bastante texto.\n\n"
    + "Segundo párrafo, igual de largo. " * 8
)


def halves_of(llm):
    """The text of the two calls that read the halves of a chunk, in order."""
    return [c["user"].split("\n", 1)[1].rsplit("\n</chunk>", 1)[0] for c in llm.calls[2:4]]


def test_a_chunk_that_stays_invalid_is_read_again_in_two_halves_before_it_is_given_up():
    llm = FakeLLM("no es json", "otra vez mal", notes("a"), notes("b"), notes("c"))

    result, warnings = read_chunks(llm, "Un artículo", [LONG, "dos"], language="es")

    assert len(result) == 3 and warnings == [] and len(llm.calls) == 5
    first, second = halves_of(llm)
    assert all(len(h) < len(LONG) * 0.75 for h in (first, second))
    assert " ".join((first + " " + second).split()) == " ".join(LONG.split())  # nothing lost
    assert all("part 1 of 2" in c["user"] for c in llm.calls[2:4])  # still the same chunk


def test_a_chunk_is_lost_with_a_warning_only_when_both_halves_fail_too():
    llm = FakeLLM("mal", "mal", "mal", "mal")

    result, warnings = read_chunks(llm, "Un artículo", [LONG], language="es")

    assert result == [] and len(llm.calls) == 4  # two tries, then one try per half
    assert len(warnings) == 1 and "chunk 1 of 1" in warnings[0] and "skipped" in warnings[0]


def test_a_chunk_read_in_one_half_only_says_so():
    llm = FakeLLM("mal", "mal", notes("a"), "mal")

    result, warnings = read_chunks(llm, "Un artículo", [LONG], language="es")

    assert len(result) == 1
    assert len(warnings) == 1 and "chunk 1 of 1" in warnings[0] and "half" in warnings[0]


def test_a_chunk_too_short_to_split_is_not_split():
    llm = FakeLLM("mal", "mal")

    result, warnings = read_chunks(llm, "Un artículo", ["corto"], language="es")

    assert result == [] and len(llm.calls) == 2 and "skipped" in warnings[0]


def test_a_long_chunk_that_times_out_is_not_split_either():
    llm = FakeLLM(LLMTimeout("timed out"))

    result, warnings = read_chunks(llm, "Un artículo", [LONG], language="es")

    assert result == [] and len(llm.calls) == 1  # two more calls could be two more timeouts
    assert warnings == ["Could not read chunk 1 of 1; skipped (the model took too long)."]
