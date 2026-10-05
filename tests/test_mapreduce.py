"""A source longer than the chunk reader's limit is read in full: chunk notes are merged into
section notes, and the final note is written from those, never from raw text."""

import hashlib
import json
import json as _json
import os
import re
import signal
from dataclasses import replace
from datetime import date

import pytest
from conftest import FakeLLM, make_plan
from typer.testing import CliRunner

from esbi_cli import cli, jsonout
from esbi_cli.cli import app
from esbi_cli.extract import ExtractedDoc
from esbi_cli.ingest.pipeline import ingest
from esbi_cli.interrupts import Interrupted, handling, interruptible
from esbi_cli.queue import Queue
from esbi_cli.run import RunLimits, run_queue

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
    """`sections` paragraphs of about 430 characters each, one per chunk when chunk_chars=600."""
    text = "\n\n".join(
        f"Sección {n}. El arnés de código gestiona el contexto y la memoria del agente. "
        f"{QUOTE}. " * 3
        for n in range(sections)
    )
    return ExtractedDoc("Un libro largo", text, "article", "https://x.test/libro")


def chunk_notes(n):
    return {
        "points": [f"Dato concreto {n}: el arnés mejora la fiabilidad."],
        "terms": [
            {"term": "arnés de código", "definition": "La capa de código que rodea al modelo."}
        ],
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


class Reader(FakeLLM):
    """Answers by the schema it is asked for, so a test does not depend on the order of calls.
    A section note says which data points it covers, so a test can follow them to the final prompt."""

    def __init__(self, *, section=None):
        super().__init__()
        self.section = section  # a payload for every SectionNotes call, e.g. "mal"

    def kinds(self, kind):
        return [c for c in self.calls if c["schema"]["title"] == kind]

    def complete_json(self, *, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        self.tokens_used += 100
        kind = schema["title"]
        if kind == "ChunkNotes":
            return json.dumps(chunk_notes(int(re.search(r"Sección (\d+)", user)[1])))
        if kind == "SectionNotes":
            if self.section is not None:
                return self.section
            numbers = [int(n) for n in re.findall(r"(?:Dato concreto|datos|-)\s?(\d+)", user)]
            points = [f"Cubre los datos {min(numbers or [0])}-{max(numbers or [0])} con detalle."]
            return json.dumps({"points": points})
        if kind == "Digest":
            return json.dumps(DIGEST)
        if kind == "ConnectionPlan":
            return json.dumps({"connections": []})
        return json.dumps(make_plan(title="Un libro largo"))


@pytest.fixture
def long_cfg(cfg):
    """Chunks of one paragraph each; the final plan takes at most 16 notes."""
    return replace(
        cfg, max_source_chars=1000, chunk_chars=600, max_chunks=16, max_calls_per_source=500
    )


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
    assert (sha(prompts), sha(body), result.warnings) == (
        "c315ae52f2a522e1",
        "69ae4e57397c6ab2",
        [],
    )


def test_a_source_that_fits_is_not_merged_even_when_a_chunk_had_to_be_read_in_halves(vault, cfg):
    cfg = replace(cfg, max_source_chars=1000, chunk_chars=600, max_chunks=16)
    llm = FakeLLM(
        "mal", "mal", chunk_notes(0), chunk_notes(0),  # chunk 1: invalid twice, then two halves
        *[chunk_notes(n) for n in range(1, 16)],
        make_plan(title="Un libro largo"), DIGEST,
    )  # fmt: skip

    result, steps = run(vault, cfg, llm, book(16))

    assert len(llm.calls) == 2 + 2 + 15 + 2  # 17 notes for 16 chunks, and no merge call
    assert not any(s.startswith("merging") for s in steps) and result.status == "ingested"


def test_a_source_of_more_chunks_than_the_limit_is_read_in_full_and_merged_into_sections(
    vault, long_cfg
):
    llm = Reader()

    result, steps = run(vault, long_cfg, llm, book(40))

    assert (len(llm.kinds("ChunkNotes")), len(llm.kinds("SectionNotes"))) == (40, 8)
    read = "\n".join(c["user"] for c in llm.kinds("ChunkNotes"))
    assert all(f"Sección {n}." in read for n in range(40))  # nothing sampled away
    first_group = llm.kinds("SectionNotes")[0]["user"]
    assert "Dato concreto 4:" in first_group and "Dato concreto 5:" not in first_group
    plan_prompt = llm.kinds("EditPlan")[0]["user"]
    assert "datos 35-39" in plan_prompt and "<chunk_notes " in plan_prompt  # the end is in it
    assert "Sección 39." not in plan_prompt  # the plan reads notes, never the raw text again
    assert "Sección 39." not in llm.kinds("Digest")[0]["user"]
    assert steps[:2] == ["chunk 1 of 40", "chunk 2 of 40"]
    assert steps[40:] == [
        *(f"merging section {k} of 8" for k in range(1, 9)),
        "synthesis",
        "detailed summary",
    ]
    assert result.warnings == [] and len(llm.calls) == 40 + 8 + 2
    assert "[!warning]" not in vault.read_page(result.applied.source_path).body


def test_a_source_of_hundreds_of_chunks_is_merged_in_levels_until_the_plan_can_take_it(
    vault, long_cfg
):
    llm = Reader()

    result, steps = run(vault, long_cfg, llm, book(100))

    assert (len(llm.kinds("ChunkNotes")), len(llm.kinds("SectionNotes"))) == (100, 20 + 4)
    assert [s for s in steps if s.startswith("merging")][-1] == "merging section 4 of 4"
    plan_prompt = llm.kinds("EditPlan")[0]["user"]
    assert plan_prompt.count("[chunk ") == 4 and "datos 75-99" in plan_prompt
    assert result.warnings == []


def test_the_quotes_and_terms_of_every_chunk_survive_the_merge_and_are_still_checked(
    vault, long_cfg
):
    """Section notes take them from the chunk notes by code, so the model cannot make one up; the
    note still keeps only what `apply_plan` finds in the source."""

    class Liar(Reader):
        def complete_json(self, *, system, user, schema):
            raw = super().complete_json(system=system, user=user, schema=schema)
            if schema["title"] != "ChunkNotes":
                return raw
            note = json.loads(raw)
            note["quotes"].append("Una frase que el modelo se inventó y que no está en el texto.")
            note["terms"].append({"term": "quimera", "definition": "Un término que no aparece."})
            return json.dumps(note)

    result, _ = run(vault, long_cfg, Liar(), book(40))

    body = vault.read_page(result.applied.source_path).body
    assert f'> "{QUOTE}"' in body and "arnés de código" in body
    assert "se inventó" not in body and "quimera" not in body
    assert result.applied.unsupported_terms == ["quimera"]


def test_a_section_that_the_model_cannot_merge_is_merged_by_code_and_reported(vault, long_cfg):
    llm = Reader(section="mal")

    result, _ = run(vault, long_cfg, llm, book(20))

    assert (
        len(llm.kinds("SectionNotes")) == 4 * 2
    )  # each section is asked twice, then merged by code
    assert sum("merged without the model" in w for w in result.warnings) == 4
    plan_prompt = llm.kinds("EditPlan")[0]["user"]
    assert all(f"Dato concreto {n}:" in plan_prompt for n in (0, 5, 10, 15))  # every part is in
    assert result.status == "ingested"


def test_a_group_of_long_notes_never_makes_a_prompt_bigger_than_the_reduce_budget(vault, long_cfg):
    from esbi_cli.ingest import mapreduce

    class Fat(Reader):
        def complete_json(self, *, system, user, schema):
            raw = super().complete_json(system=system, user=user, schema=schema)
            if schema["title"] != "ChunkNotes":
                return raw
            return json.dumps(
                {
                    "points": [f"Punto {i}. " + "largo " * 70 for i in range(8)],
                    "terms": [
                        {"term": f"término {i}", "definition": "una definición " * 8}
                        for i in range(6)
                    ],
                    "quotes": [QUOTE] * 3,
                    "relations": [],
                }
            )

    llm = Fat()
    run(vault, long_cfg, llm, book(20))

    sections = llm.kinds("SectionNotes")
    assert sections and max(len(c["user"]) for c in sections) <= mapreduce.REDUCE_BUDGET_CHARS + 200


def test_the_call_limit_stops_the_reading_and_the_note_says_which_part_was_not_read(
    vault, long_cfg
):
    cfg = replace(long_cfg, max_calls_per_source=30)
    llm = Reader()

    result, steps = run(vault, cfg, llm, book(40))

    # 7 calls stay for the plan, the summary and the connections; the merging of what was read too
    assert (len(llm.kinds("ChunkNotes")), len(llm.kinds("SectionNotes"))) == (19, 4)
    assert len(llm.calls) == 19 + 4 + 2 <= 30
    assert "datos 15-18" in llm.kinds("EditPlan")[0]["user"]  # the last part that was read
    assert not any("Sección 19." in c["user"] for c in llm.calls)
    (warning,) = [w for w in result.warnings if "Not read" in w]
    assert "21 of 40 parts" in warning and "[run].max_calls_per_source" in warning
    assert "Sección 19." in warning  # where the unread part starts
    body = vault.read_page(result.applied.source_path).body
    assert "> [!warning] No leído: 21 de 40 partes" in body and "Sección 19." in body
    assert "chunk 20 of 40" not in steps


def test_the_limit_is_hard_even_when_every_answer_is_invalid(vault, long_cfg):
    cfg = replace(long_cfg, max_calls_per_source=20)
    llm = FakeLLM(*["mal"] * 13, make_plan(title="Un libro largo"))

    result, _ = run(vault, cfg, llm, book(40))

    assert (
        len(llm.calls) == 14 <= 20
    )  # 13 answers to chunks, then the plan from the head of the text
    assert result.status == "ingested"


def test_with_a_limit_big_enough_nothing_is_reported_missing(vault, long_cfg):
    cfg = replace(long_cfg, max_calls_per_source=40 + 8 + 7)  # room for all 40 chunks
    result, _ = run(vault, cfg, Reader(), book(40))

    assert not any("Not read" in w for w in result.warnings)


def test_a_signal_in_the_middle_of_the_many_calls_leaves_the_vault_untouched(vault, long_cfg):
    class SignalledAt(Reader):
        def complete_json(self, *, system, user, schema):
            if len(self.calls) == 44:  # in the merging, after all chunks were read
                os.kill(os.getpid(), signal.SIGINT)
            return super().complete_json(system=system, user=user, schema=schema)

    with pytest.raises(Interrupted), handling(), interruptible():
        run(vault, long_cfg, SignalledAt(), book(40))

    assert list((vault.wiki / "sources").glob("*.md")) == []
    assert list((vault.root / "raw").glob("*")) == []


def test_the_run_token_budget_counts_every_call_of_a_long_source(vault, long_cfg, tmp_path):
    llm = Reader()
    queue = Queue(tmp_path / "q.sqlite3")
    queue.add("https://x.test/uno", "test")
    queue.add("https://x.test/dos", "test")
    docs = {"https://x.test/uno": book(40), "https://x.test/dos": book(40)}

    def ingest_fn(target):
        return ingest(target, vault=vault, llm=llm, cfg=long_cfg, extractor=docs.__getitem__)

    summary = run_queue(queue, ingest_fn, RunLimits(5, max_tokens=1000), lambda: llm.tokens_used)

    assert summary.ingested == 1 and summary.stopped_by == "token_budget"
    assert summary.tokens_used == 100 * len(llm.calls) > 1000  # 50 calls, all counted


def test_the_step_of_a_merge_is_an_event_with_an_index_and_a_total_like_a_chunk_step():
    assert jsonout.step_fields("merging section 2 of 8") == {
        "name": "merging section",
        "index": 2,
        "total": 8,
    }
    assert jsonout.step_fields("chunk 2 of 6") == {"name": "chunk", "index": 2, "total": 6}


def test_sb_run_json_reports_the_chunk_and_merge_steps_of_a_long_source(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: Reader())
    text = "\n\n".join(f"Sección {n}. " + "Texto largo. " * 600 for n in range(24))
    (vault.root / "inbox" / "Long.md").write_text(
        f"---\nsource: https://x.test/long\ntitle: Largo\n---\n{text}"
    )

    run = CliRunner().invoke(app, ["run", "--json", "--config", str(config_file)])

    steps = [e for e in map(json.loads, run.stdout.splitlines()) if e["event"] == "step"]
    merges = [s for s in steps if s["name"] == "merging section"]
    assert merges and all(
        isinstance(s["index"], int) and isinstance(s["total"], int) for s in merges
    )
    assert [s["index"] for s in merges] == list(range(1, len(merges) + 1))
    assert {s["name"] for s in steps} <= {
        "chunk",
        "merging section",
        "synthesis",
        "detailed summary",
        "connections",
    }


def test_the_call_counter_wraps_a_real_adapter_and_changes_nothing_it_sends_or_reports(
    vault, long_cfg, monkeypatch
):
    """A fake takes any arguments; the real adapter is called with keywords, reports its own
    tokens and says where it sends text. Run the real one over a fake transport."""
    import httpx

    from esbi_cli.config import LLMConfig
    from esbi_cli.ingest.mapreduce import CallBudget, counted
    from esbi_cli.llm import adapter
    from esbi_cli.privacy import sends_text_out

    seen = []
    answers = {"ChunkNotes": chunk_notes(0), "EditPlan": make_plan(), "Digest": DIGEST}

    def post(url, headers, json, timeout):  # noqa: A002 - mirrors httpx.post
        seen.append(json)
        body = {"message": {"content": _json.dumps(answers[json["format"]["title"]])}}
        body["eval_count"] = 10
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(adapter.httpx, "post", post)
    llm = adapter.make_llm(LLMConfig(model="ollama/m", num_ctx=4096))

    result, _ = run(vault, replace(long_cfg, chunk_chars=2000), llm, book(8))

    assert result.status == "ingested" and len(seen) == llm.tokens_used // 10 > 3
    assert {c["options"]["num_ctx"] for c in seen} == {4096}
    remote = adapter.make_llm(LLMConfig(model="ollama/m", base_url="http://example.test:11434"))
    assert sends_text_out(counted(remote, CallBudget(20))) is True
    assert sends_text_out(counted(llm, CallBudget(20))) is False
