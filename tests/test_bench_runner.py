from conftest import FakeLLM, make_plan
from test_ask import plan as answer_plan
from test_ask import wiki_with_harness

from esbi_cli.bench.cases import AskCase, IngestCase
from esbi_cli.bench.runner import run_benchmark
from esbi_cli.extract import ExtractedDoc
from esbi_cli.llm.adapter import LLMError


class BrokenLLM(FakeLLM):
    def complete_json(self, **kwargs):
        raise LLMError("localhost:11434 unreachable")


def ingest_case(name, url):
    text = (
        "Los agentes de IA usan un arnés de código para planificar y ejecutar herramientas. " * 10
    )
    return IngestCase(name, ExtractedDoc(title=name, text=text, kind="article", url=url))


def ticking_clock(step=2.0):
    now = [0.0]

    def clock():
        value = now[0]
        now[0] += step
        return value

    return clock


def trials_by(trials):
    return {(t.model, t.task, t.case): t for t in trials}


def test_every_model_runs_every_ingest_case_and_broken_models_do_not_stop_the_others(vault):
    cases = [ingest_case("uno", "https://x.test/1"), ingest_case("dos", "https://x.test/2")]
    models = {
        "good": FakeLLM(make_plan(), make_plan()),
        "retrier": FakeLLM("no es json", make_plan(), make_plan()),
        "invalid": FakeLLM("x", "y", "x", "y"),
        "down": BrokenLLM(),
    }

    trials = run_benchmark(
        list(models), cases, [], vault, llm_factory=models.__getitem__, clock=ticking_clock()
    )

    by = trials_by(trials)
    assert len(trials) == 8  # 4 models x 2 cases
    good = by[("good", "ingest", "uno")]
    assert (good.ok, good.first_try, good.tokens, good.latency_s) == (True, True, 100, 2.0)
    assert good.metrics == {"concepts": 1, "entities": 1, "in_language": True, "bad_refs": 0}
    retry = by[("retrier", "ingest", "uno")]
    assert (retry.ok, retry.first_try, retry.tokens) == (True, False, 200)
    invalid = by[("invalid", "ingest", "uno")]
    assert not invalid.ok and "invalid plan" in invalid.error
    down = by[("down", "ingest", "dos")]
    assert not down.ok and "unreachable" in down.error


def test_ask_cases_are_scored_on_grounding_and_on_citing_the_expected_page(vault):
    wiki_with_harness(vault)
    case = AskCase("Arnés de agente", "¿Qué es Arnés de agente?", "Arnés de agente")
    models = {
        "cites": FakeLLM(answer_plan()),
        "refuses": FakeLLM(answer_plan(answer="Nada verificable aquí.", cited_pages=["Nada"])),
    }

    trials = run_benchmark(list(models), [], [case], vault, llm_factory=models.__getitem__)

    by = trials_by(trials)
    cites = by[("cites", "ask", "Arnés de agente")]
    assert (cites.ok, cites.metrics["cites_expected"]) == (True, True)
    refused = by[("refuses", "ask", "Arnés de agente")]
    assert (refused.ok, refused.metrics["grounded"]) == (False, False)


def test_progress_is_reported_after_every_trial_in_order(vault):
    cases = [ingest_case("uno", "https://x.test/1"), ingest_case("dos", "https://x.test/2")]
    models = {"m": FakeLLM(make_plan(), make_plan())}
    seen = []

    run_benchmark(
        list(models), cases, [], vault, llm_factory=models.__getitem__, on_trial=seen.append
    )

    assert [(t.model, t.case) for t in seen] == [("m", "uno"), ("m", "dos")]


def test_the_benchmark_asks_for_the_wikis_language_so_a_right_answer_needs_no_retry(vault):
    models = {"m": FakeLLM(make_plan())}
    run_benchmark(["m"], [ingest_case("uno", "https://x.test/1")], [], vault, models.__getitem__)
    assert "Write ALL text in Spanish" in models["m"].calls[0]["system"]
