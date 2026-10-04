from datetime import datetime

from esbi_cli.bench.report import render_report, save_report, suggest_routing, summarize
from esbi_cli.bench.runner import Trial


def trial(
    model, ok=True, first=True, latency_seconds=10.0, tokens=1000, task="ingest", metrics=None, n=0
):
    return Trial(
        model,
        task,
        f"c{n}",
        ok,
        first,
        latency_seconds,
        tokens,
        metrics or {"in_language": True, "concepts": 3},
    )


def by_model(summaries, task="ingest"):
    return {s.model: s for s in summaries if s.task == task}


def test_summaries_give_success_rates_median_latency_tokens_and_estimated_cost():
    trials = [
        trial("cloud", latency_seconds=4.0, tokens=2000, n=0),
        trial("cloud", latency_seconds=6.0, tokens=1000, n=1),
        trial("cloud", latency_seconds=100.0, tokens=3000, n=2),
        trial("local", ok=False, first=False, latency_seconds=30.0, tokens=500, n=0, metrics={}),
        trial(
            "local",
            latency_seconds=50.0,
            tokens=500,
            n=1,
            metrics={"in_language": False, "concepts": 1},
        ),
    ]

    summaries = by_model(summarize(trials, prices={"cloud": 3.0}))

    cloud = summaries["cloud"]
    assert (cloud.trials, cloud.ok_rate, cloud.first_try_rate) == (3, 1.0, 1.0)
    assert cloud.median_latency_seconds == 6.0 and cloud.tokens_per_case == 2000
    assert round(cloud.cost_usd, 4) == 0.018  # 6000 tokens at $3 per million
    local = summaries["local"]
    assert (local.ok_rate, local.first_try_rate, local.cost_usd) == (0.5, 0.5, 0.0)
    assert local.language_rate == 0.0 and local.avg_concepts == 1.0  # only successful trials count


def test_routing_never_recommends_an_unreliable_model_however_fast_it_is():
    trials = [
        *[trial("fast-flaky", ok=i < 2, latency_seconds=1.0, n=i) for i in range(5)],  # 40% ok
        *[trial("slow-solid", latency_seconds=60.0, n=i) for i in range(5)],
        *[trial("quick-solid", latency_seconds=20.0, n=i) for i in range(5)],
        *[trial("only-flaky", ok=False, task="ask", n=i, metrics={}) for i in range(3)],
    ]

    routing = suggest_routing(summarize(trials, prices={}))

    assert routing == {"ingest": "quick-solid", "ask": None}


def test_the_report_lists_each_model_and_the_routing_and_is_saved_in_the_vault(vault):
    trials = [trial("qwen3:4b", n=0), trial("qwen3:4b", n=1, first=False)]
    summaries = summarize(trials, prices={})
    routing = suggest_routing(summaries)

    text = render_report(summaries, routing, datetime(2026, 9, 29, 20, 15), "es")
    path = save_report(vault, text, datetime(2026, 9, 29, 20, 15))

    assert "| qwen3:4b |" in text and "ingest" in text
    assert "ingest → `qwen3:4b`" in text and "ask → sin recomendación" in text
    assert path == vault.root / ".esbi" / "bench" / "2026-09-29-2015.md"
    assert path.read_text(encoding="utf-8") == text
