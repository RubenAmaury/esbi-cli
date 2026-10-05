"""`--json`: the machine contract (version 1) an editor plugin reads. Shapes below are the golden
copy of the contract table: every key and its type per command, and an emitted key that is not
listed here fails the test. An additive change keeps the contract number but is written down here
(and in the contract document) in the same commit."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FakeLaunchctl, FakeLLM, make_plan
from test_cli import _clip, _harness_wiki, _priced, _two_clips
from test_doctor import healthy
from typer.testing import CliRunner

from esbi_cli import __version__, cli, jsonout
from esbi_cli import schedule as launchd
from esbi_cli.ingest.pipeline import IngestResult
from esbi_cli.llm.adapter import LLMError
from esbi_cli.queue import Queue
from esbi_cli.run import RunLimits, run_queue

NULLABLE = type(None)

SHAPES = {
    "version": {"contract": int, "version": str},
    "status": {
        "contract": int,
        "vault": str,
        "queue": {"queued": int, "processing": int, "done": int, "failed": int},
        "failed": [{"target": str, "attempts": int, "error": str}],
        "retrying": [{"target": str, "attempts": int, "error": str}],
    },
    "info": {
        "contract": int,
        "version": str,
        "config": str,
        "vault": str,
        "viewer": str,
        "language": str,
        "models": {"summarize": str, "ask": str},
        "sends_text_out": {"summarize": bool, "ask": bool},
        "nightly": {"installed": bool, "time": str},
    },
    "doctor": {
        "contract": int,
        "ok": bool,
        "checks": [{"level": str, "name": str, "text": str, "fix": str}],
    },
    "add": {
        "contract": int,
        "queued": int,
        "already_known": int,
        "in_wiki": [{"target": str, "title": str}],
    },
    "ask": {
        "contract": int,
        "answer": str,
        "cited": [str],
        "refused": bool,
        "saved": (str, NULLABLE),
        "unsupported": [{"sentence": str, "missing": [str]}],
    },
    "error": {"contract": int, "error": str, "code": str},
    "started": {"contract": int, "event": str, "queued": int},
    "source_started": {"contract": int, "event": str, "target": str, "title": str},
    "step": {"contract": int, "event": str, "target": str, "name": str},
    "source_done": {"contract": int, "event": str, "target": str, "title": str, "note": str},
    "source_failed": {
        "contract": int,
        "event": str,
        "target": str,
        "attempt": int,
        "max_attempts": int,
        "parked": bool,
        "reason": str,
    },
    "finished": {
        "contract": int,
        "event": str,
        "ingested": int,
        "failed": int,
        "skipped": int,
        "tokens": int,
        "stopped_by": (str, NULLABLE),
    },
}


def check_shape(value, shape, where="$"):
    if isinstance(shape, dict):
        assert isinstance(value, dict), f"{where} is not an object: {value!r}"
        undeclared = sorted(set(value) - set(shape))
        assert not undeclared, f"{where} has undeclared keys {undeclared}: {value!r}"
        for key, sub in shape.items():
            assert key in value, f"{where} lacks {key!r}: {value!r}"
            check_shape(value[key], sub, f"{where}.{key}")
    elif isinstance(shape, list):
        assert isinstance(value, list), f"{where} is not a list: {value!r}"
        for n, item in enumerate(value):
            check_shape(item, shape[0], f"{where}[{n}]")
    else:
        types = shape if isinstance(shape, tuple) else (shape,)
        assert isinstance(value, types) and not (isinstance(value, bool) and bool not in types), (
            f"{where} should be {types}, got {value!r}"
        )


def test_a_key_that_the_golden_shape_does_not_list_fails_the_check():
    with pytest.raises(AssertionError, match="undeclared keys.*extra"):
        check_shape({"contract": 1, "version": "x", "extra": 1}, SHAPES["version"])
    with pytest.raises(AssertionError, match="undeclared keys.*why"):
        check_shape(
            {
                "contract": 1,
                "queued": 0,
                "already_known": 0,
                "in_wiki": [{"target": "t", "title": "T", "why": 1}],
            },
            SHAPES["add"],
        )


def invoke(config_file, *args, **kwargs):
    return CliRunner().invoke(cli.app, [*args, "--config", str(config_file)], **kwargs)


def only_object(result) -> dict:
    """stdout must be exactly one JSON object on one line and nothing else."""
    assert result.stdout.count("\n") == 1, result.stdout
    return json.loads(result.stdout)


def lines(result) -> list[dict]:
    return [json.loads(line) for line in result.stdout.splitlines()]


def test_the_contract_number_is_the_one_in_the_contract_document():
    assert jsonout.CONTRACT == 1  # bump together with JSON-CONTRACT.md and a breaking change


def test_version_json_says_the_installed_version_and_the_contract_it_speaks():
    result = CliRunner().invoke(cli.app, ["version", "--json"])

    assert result.exit_code == 0, result.output
    data = only_object(result)
    check_shape(data, SHAPES["version"])
    assert data == {"contract": 1, "version": __version__}


def test_status_json_lists_the_counts_the_parked_failures_and_the_ones_being_retried(
    vault, config_file
):
    queue = Queue(vault.root / ".esbi" / "queue.sqlite3")
    for name in ("done", "queued", "retrying", "parked"):
        queue.add(f"https://x.test/{name}", "cli")
    queue.complete(queue.get("https://x.test/done").id)
    queue.fail(queue.get("https://x.test/retrying").id, "timeout")
    for _ in range(3):
        queue.fail(queue.get("https://x.test/parked").id, "no readable content")

    result = invoke(config_file, "status", "--json")

    assert result.exit_code == 0, result.output
    data = only_object(result)
    check_shape(data, SHAPES["status"])
    assert data["vault"] == str(vault.root)
    assert data["queue"] == {"queued": 2, "processing": 0, "done": 1, "failed": 1}
    assert data["failed"] == [
        {"target": "https://x.test/parked", "attempts": 3, "error": "no readable content"}
    ]
    assert data["retrying"] == [
        {"target": "https://x.test/retrying", "attempts": 1, "error": "timeout"}
    ]


def test_info_json_gives_the_paths_models_and_the_nightly_job(vault, config_file, monkeypatch):
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl(loaded=True))

    result = invoke(config_file, "info", "--json")

    assert result.exit_code == 0, result.output
    data = only_object(result)
    check_shape(data, SHAPES["info"])
    assert data["config"] == str(config_file) and data["vault"] == str(vault.root)
    assert data["viewer"] == "obsidian" and data["language"] == "es"
    assert data["models"] == {"summarize": "ollama/fake", "ask": "ollama/fake"}  # ask falls back
    assert data["nightly"] == {"installed": True, "time": "03:00"}


def test_info_json_names_the_configured_models_per_task(tmp_path, vault, config_file, monkeypatch):
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl(loaded=False))
    config_file.write_text(config_file.read_text() + '\n[llm.ask]\nmodel = "ollama/bigger"\n')

    data = only_object(invoke(config_file, "info", "--json"))

    assert data["models"]["ask"] == "ollama/bigger" and data["nightly"]["installed"] is False


def test_info_json_says_per_task_whether_the_model_sends_text_out(vault, config_file, monkeypatch):
    monkeypatch.setattr(launchd, "run_launchctl", FakeLaunchctl(loaded=False))
    config_file.write_text(
        config_file.read_text()
        + '\n[llm.ask]\nmodel = "claude-cli/default"\n'
        + '\n[llm.embed]\nmodel = "mystery/x"\n'
    )

    data = only_object(invoke(config_file, "info", "--json"))

    assert data["sends_text_out"]["summarize"] is False  # ollama
    assert data["sends_text_out"]["ask"] is True  # a subscription tool sends the text out
    assert data["sends_text_out"]["embed"] is True  # a model that cannot be built is assumed cloud
    assert set(data["sends_text_out"]) == set(data["models"])


def test_doctor_json_lists_every_check_and_keeps_the_exit_code(vault, config_file, monkeypatch):
    healthy(monkeypatch, vault)

    ok = invoke(config_file, "doctor", "--json")

    assert ok.exit_code == 0, ok.output
    data = only_object(ok)
    check_shape(data, SHAPES["doctor"])
    assert data["ok"] is True and {c["name"] for c in data["checks"]} >= {"config", "vault"}
    assert {c["level"] for c in data["checks"]} <= {"ok", "WARN", "FAIL"}

    healthy(monkeypatch, vault, models=("DOWN",))  # the model server is unreachable: FAIL
    broken = invoke(config_file, "doctor", "--json")

    assert broken.exit_code == 1
    assert only_object(broken)["ok"] is False


def test_add_json_counts_what_was_queued_and_what_was_already_known(vault, config_file):
    first = invoke(config_file, "add", "https://x.test/a", "https://x.test/b", "--json")
    again = invoke(config_file, "add", "https://x.test/a", "--json")

    check_shape(only_object(first), SHAPES["add"])
    assert only_object(first)["queued"] == 2 and only_object(first)["already_known"] == 0
    assert only_object(again)["queued"] == 0 and only_object(again)["already_known"] == 1


def test_add_json_reports_a_source_the_wiki_already_has_instead_of_queuing_it(vault, config_file):
    from conftest import add_source

    page = add_source(vault, "Ya está")
    page.meta["url"] = "https://x.test/known"
    vault.write_page(page)

    data = only_object(invoke(config_file, "add", "https://x.test/known", "--json"))

    check_shape(data, SHAPES["add"])
    assert data["queued"] == 0 and data["in_wiki"] == [
        {"target": "https://x.test/known", "title": "Ya está"}
    ]


def test_add_json_refuses_a_target_that_is_not_a_source_with_an_error_object(config_file):
    result = invoke(config_file, "add", "not a url", "--json")

    assert result.exit_code == 1
    data = only_object(result)
    check_shape(data, SHAPES["error"])
    assert data["code"] == "bad_target" and "not a url" in data["error"]


def test_ask_json_returns_the_answer_the_human_mode_prints_and_the_page_titles(
    vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    from test_cli import _answer_plan

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan(), _answer_plan()))
    question = "¿Qué es un arnés de agente?"

    human = invoke(config_file, "ask", question)
    result = invoke(config_file, "ask", question, "--json")

    assert result.exit_code == 0, result.output
    data = only_object(result)
    check_shape(data, SHAPES["ask"])
    assert data["refused"] is False and data["saved"] is None
    assert data["cited"] == ["Arnés de agente", "Code as Agent Harness"]
    assert "Sources: " + ", ".join(f"[[{c}]]" for c in data["cited"]) in human.stdout
    assert data["answer"] in human.stdout
    assert "Capa de código que rodea" not in result.stdout  # titles only, no page text


def test_ask_json_lists_the_sentences_the_pages_do_not_back_and_stays_contract_1(
    vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    from test_cli import _answer_plan

    answer = _answer_plan(
        answer="Un arnés de agente es la capa de código que orquesta al modelo. Lo inventó Google en 2019. [[Arnés de agente]]"
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(answer))

    data = only_object(invoke(config_file, "ask", "¿Qué es un arnés de agente?", "--json"))

    check_shape(data, SHAPES["ask"])
    assert data["contract"] == 1 and data["refused"] is False
    assert data["unsupported"] == [
        {"sentence": "Lo inventó Google en 2019.", "missing": ["inventó", "Google", "2019"]}
    ]
    assert "Lo inventó Google en 2019. ⚠" in data["answer"]


def test_ask_json_of_an_answer_the_pages_back_has_an_empty_unsupported_list(
    vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    from test_cli import _answer_plan

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan()))

    data = only_object(invoke(config_file, "ask", "¿Qué es un arnés de agente?", "--json"))

    assert data["unsupported"] == [] and "⚠" not in data["answer"]


def test_ask_json_with_save_gives_the_relative_path_of_the_saved_page(
    vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    from test_cli import _answer_plan

    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(_answer_plan(), _answer_plan()))

    data = only_object(
        invoke(config_file, "ask", "¿Qué es un arnés de agente?", "--save", "--json")
    )

    assert data["saved"] == "wiki/syntheses/Qué es un arnés de agente.md"
    assert (vault.root / data["saved"]).exists()


def test_a_refused_ask_is_a_normal_answer_with_refused_true_and_exit_0(
    vault, config_file, monkeypatch
):
    _harness_wiki(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())

    result = invoke(config_file, "ask", "¿Cómo se hace una tortilla?", "--json")

    assert result.exit_code == 0, result.output
    data = only_object(result)
    check_shape(data, SHAPES["ask"])
    assert data["refused"] is True and data["cited"] == [] and "No encuentro nada" in data["answer"]


def test_ask_json_turns_a_model_failure_into_an_error_object(vault, config_file, monkeypatch):
    _harness_wiki(vault)
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(LLMError("Ollama is down")))

    result = invoke(config_file, "ask", "¿Qué es un arnés de agente?", "--json")

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    data = only_object(result)
    check_shape(data, SHAPES["error"])
    assert data["code"] == "llm_error" and "Ollama is down" in data["error"]


@pytest.mark.parametrize("command", ["status", "info", "add", "ask", "run"])
def test_every_json_command_reports_a_bad_config_as_an_error_object(tmp_path, config_file, command):
    bad = tmp_path / "bad.toml"
    bad.write_text(config_file.read_text().replace("[run]", "[run]\nnonsense = 1"))
    extra = {"add": ["https://x.test/a"], "ask": ["q"]}.get(command, [])

    result = invoke(bad, command, *extra, "--json")

    assert result.exit_code == 1
    data = only_object(result)
    check_shape(data, SHAPES["error"])
    assert data["code"] == "bad_config" and "nonsense" in data["error"]
    assert "Traceback" not in result.output


def test_a_config_that_does_not_exist_is_an_error_object(tmp_path):
    result = invoke(tmp_path / "typo.toml", "status", "--json")

    assert result.exit_code == 1
    data = only_object(result)
    assert data["code"] == "config_not_found" and "typo.toml" in data["error"]


def test_without_json_the_error_stays_a_human_line_on_stderr(tmp_path):
    result = invoke(tmp_path / "typo.toml", "status")

    assert result.exit_code == 1 and result.stdout == ""
    assert "error: config file not found" in result.output


def test_a_command_without_the_option_stays_human_after_a_json_one_in_the_same_process(tmp_path):
    missing = tmp_path / "typo.toml"
    invoke(missing, "status", "--json")  # the menu and the tests run many commands in one process

    result = invoke(missing, "retry")  # `retry` has no --json

    assert result.exit_code == 1 and result.stdout == ""
    assert "error: config file not found" in result.output


# --- sb run --json: JSON Lines ---------------------------------------------------------------


def test_run_json_streams_one_event_per_line_in_the_contract_order(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)

    result = invoke(config_file, "run", "--json")

    assert result.exit_code == 0, result.output
    events = lines(result)
    names = [e["event"] for e in events]
    assert names[0] == "started" and names[1] == "source_started" and names[-1] == "finished"
    assert names.count("source_done") == 1 and names.count("finished") == 1
    assert names.index("source_done") > names.index("source_started")
    for event in events:
        check_shape(event, SHAPES[event["event"]])
        assert event["contract"] == 1
    started, begun, done, finished = events[0], events[1], events[-2], events[-1]
    assert done["event"] == "source_done" and started["queued"] == 1
    assert begun["title"] == "Arnés de agentes"
    assert (
        done["note"] == "wiki/sources/Arnés de agentes.md" and done["title"] == "Arnés de agentes"
    )
    assert (vault.root / done["note"]).exists()
    assert finished["ingested"] == 1 and finished["failed"] == 0 and finished["stopped_by"] is None
    assert finished["tokens"] > 0
    assert all(e["target"] == begun["target"] for e in events if e["event"] == "step")


def test_run_json_gives_a_source_the_wiki_already_has_as_done_with_its_existing_note(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)
    invoke(config_file, "run", "--json")
    (vault.root / "inbox" / "Again.md").write_text(
        "---\nsource: https://x.test/p\ntitle: Otro título\n---\n" + "Texto del post. " * 10
    )

    events = lines(invoke(config_file, "run", "--json"))

    done = [e for e in events if e["event"] == "source_done"]
    assert [e["event"] for e in events][-1] == "finished" and events[-1]["skipped"] == 1
    assert done and done[0]["title"] == "Arnés de agentes"
    assert done[0]["note"] == "wiki/sources/Arnés de agentes.md"


def test_run_json_turns_a_model_that_cannot_be_built_into_an_error_object(
    vault, config_file, monkeypatch
):
    def boom(_cfg):
        raise ValueError("unknown provider 'nope'")

    monkeypatch.setattr(cli, "make_llm", boom)

    result = invoke(config_file, "run", "--json")

    assert result.exit_code == 1
    data = only_object(result)
    check_shape(data, SHAPES["error"])
    assert data["code"] == "bad_config" and "nope" in data["error"]


def test_run_json_prints_nothing_but_events_on_stdout(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)

    result = invoke(config_file, "run", "--json")

    for line in result.stdout.splitlines():
        assert line.startswith("{") and "event" in json.loads(line)  # no "Wrote ...", "ingested:"


def test_run_json_steps_say_which_chunk_of_how_many(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    (vault.root / "inbox" / "Long.md").write_text(
        "---\nsource: https://x.test/long\ntitle: Largo\n---\n" + "Texto largo. " * 800
    )

    steps = [e for e in lines(invoke(config_file, "run", "--json")) if e["event"] == "step"]

    chunks = [s for s in steps if s["name"] == "chunk"]
    assert chunks and all(
        isinstance(s["index"], int) and isinstance(s["total"], int) for s in chunks
    )
    assert [s["index"] for s in chunks] == list(range(1, len(chunks) + 1))
    assert {s["name"] for s in steps} <= {
        "chunk",
        "merging section",
        "synthesis",
        "detailed summary",
        "connections",
    }  # what the pipeline's on_step says: nothing reports the OCR as a step


def test_run_json_when_the_model_is_down_ends_with_finished_and_exit_1(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(LLMError("Ollama is down")))
    _clip(vault)

    result = invoke(config_file, "run", "--json")

    assert result.exit_code == 1
    events = lines(result)
    assert [e["event"] for e in events][-1] == "finished"
    assert events[-1]["stopped_by"] == "llm_unavailable" and events[-1]["ingested"] == 0
    for event in events:
        check_shape(event, SHAPES[event["event"]])


def test_run_json_a_usd_cap_ends_with_finished_and_its_own_stopped_by(
    vault, config_file, monkeypatch
):
    cloud = FakeLLM(make_plan(), make_plan(title="Otro"))
    cloud.sends_text_out = True
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: cloud)
    _priced(config_file, "anthropic/fake")
    _two_clips(vault)

    result = invoke(config_file, "run", "--json")

    events = lines(result)
    assert result.exit_code == 0 and events[-1]["event"] == "finished"
    assert (events[-1]["stopped_by"], events[-1]["ingested"]) == ("usd_budget", 1)
    for event in events:
        check_shape(event, SHAPES[event["event"]])


def test_run_json_with_nothing_queued_still_says_started_and_finished(
    vault, config_file, monkeypatch
):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())

    events = lines(invoke(config_file, "run", "--json"))

    assert [e["event"] for e in events] == ["started", "finished"]
    assert events[0]["queued"] == 0


def test_run_json_while_another_run_holds_the_lock_is_an_error_object_and_exit_0(
    vault, config_file
):
    from esbi_cli.runlock import RunLock

    with RunLock(vault.root / ".esbi" / "run.lock"):
        result = invoke(config_file, "run", "--json")

    assert result.exit_code == 0  # as in human mode: skipping is not a failure
    data = only_object(result)
    check_shape(data, SHAPES["error"])
    assert data["code"] == "run_in_progress"


def test_run_json_a_run_that_is_not_due_finishes_at_once(vault, config_file, monkeypatch):
    from datetime import datetime

    from esbi_cli.runlog import RunLog, RunRecord

    now = datetime.now()
    RunLog(vault.root / ".esbi" / "runs.jsonl").record(
        RunRecord(now, now, 1, 0, 0, 10, None, "scheduled")
    )
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM())

    events = lines(invoke(config_file, "run", "--if-due", "--json"))

    assert [e["event"] for e in events] == ["finished"] and events[0]["stopped_by"] == "not_due"


def test_run_queue_emits_started_source_started_and_source_failed(queue, doc):
    queue.add("https://x.test/ok", "cli", label="Bueno")
    queue.add("https://x.test/bad", "cli")
    events = []

    def ingest_fn(target):
        if target.endswith("/bad"):
            raise RuntimeError("no readable content")
        return IngestResult("ingested", doc)

    run_queue(
        queue,
        ingest_fn,
        RunLimits(max_sources=5),
        on_event=lambda name, **f: events.append((name, f)),
    )

    assert events == [
        ("started", {"queued": 2}),
        ("source_started", {"target": "https://x.test/ok", "title": "Bueno"}),
        ("source_started", {"target": "https://x.test/bad", "title": "https://x.test/bad"}),
        (
            "source_failed",
            {
                "target": "https://x.test/bad",
                "attempt": 1,
                "max_attempts": 3,
                "parked": False,
                "reason": "RuntimeError: no readable content",
            },
        ),
    ]


def test_run_queue_works_without_a_listener(queue, doc):
    queue.add("https://x.test/ok", "cli")

    assert run_queue(queue, lambda t: IngestResult("ingested", doc), RunLimits(2)).ingested == 1


# --- the stream itself ------------------------------------------------------------------------


class RecordingStream:
    def __init__(self):
        self.ops: list[tuple[str, str]] = []

    def write(self, text):
        self.ops.append(("write", text))
        return len(text)

    def flush(self):
        self.ops.append(("flush", ""))

    def isatty(self):
        return False


def test_every_event_is_flushed_on_its_own_so_a_reader_sees_it_at_once(monkeypatch):
    stream = RecordingStream()
    monkeypatch.setattr(sys, "stdout", stream)

    jsonout.event("started", queued=2)
    jsonout.event("finished", ingested=1)

    chunks, current = [], ""
    for op, text in stream.ops:
        if op == "write":
            current += text
        else:
            chunks.append(current)
            current = ""
    assert current == ""  # nothing is left unflushed
    assert len(chunks) == 2
    for chunk, name in zip(chunks, ("started", "finished"), strict=True):
        assert chunk.endswith("\n") and chunk.count("\n") == 1
        assert json.loads(chunk)["event"] == name


def test_run_json_flushes_line_by_line_through_the_cli(vault, config_file, monkeypatch):
    monkeypatch.setattr(cli, "make_llm", lambda _cfg: FakeLLM(make_plan()))
    _clip(vault)
    stream = RecordingStream()
    monkeypatch.setattr(sys, "stdout", stream)

    with pytest.raises(SystemExit) as exit_:
        cli.app(["run", "--json", "--config", str(config_file)])

    assert exit_.value.code in (0, None)
    chunks, current = [], ""
    for op, text in stream.ops:
        if op == "write":
            current += text
        else:
            chunks.append(current)
            current = ""
    assert current == "", "text written to stdout after the last flush"
    parsed = [json.loads(c) for c in chunks if c]
    assert [p["event"] for p in parsed][0] == "started" and parsed[-1]["event"] == "finished"
    assert all(c.count("\n") == 1 and c.endswith("\n") for c in chunks if c)


def test_a_real_sb_status_json_prints_pure_json_on_stdout(tmp_path, vault, config_file):
    env = {
        **os.environ,
        "ESBI_NO_UPDATE_CHECK": "1",
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "ESBI_CONFIG": "",
    }
    sb = Path(sys.executable).parent / "sb"

    done = subprocess.run(
        [str(sb), "status", "--json", "--config", str(config_file)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.count("\n") == 1
    data = json.loads(done.stdout)
    check_shape(data, SHAPES["status"])
    assert data["contract"] == 1 and data["vault"] == str(vault.root)


MISSING_VAULT_COMMANDS = [
    ["status"],
    ["info"],
    ["scan"],
    ["index"],
    ["today"],
    ["lint"],
    ["retry"],
    ["add", "https://x.test/a"],
    ["ask", "q"],
    ["ingest", "https://x.test/a"],
    ["run"],
]


@pytest.mark.parametrize("command", MISSING_VAULT_COMMANDS, ids=lambda c: c[0])
def test_a_vault_that_does_not_exist_is_an_error_not_a_new_folder(tmp_path, command):
    missing = tmp_path / "gone"
    config = tmp_path / "config.toml"
    config.write_text(f'[paths]\nvault = "{missing}"\n[llm.summarize]\nmodel = "ollama/fake"\n')

    human = invoke(config, *command)

    assert human.exit_code == 1 and "error: vault not found" in human.output
    if command[0] in ("status", "info", "add", "ask"):
        machine = invoke(config, *command, "--json")
        assert machine.exit_code == 1
        data = only_object(machine)
        check_shape(data, SHAPES["error"])
        assert data["code"] == "vault_not_found" and str(missing) in data["error"]
    assert not missing.exists()
