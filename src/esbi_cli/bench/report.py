"""Turn raw trials into a per-model comparison and a routing suggestion. Never edits config."""

from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from statistics import mean, median

from esbi_cli import lang
from esbi_cli.bench.runner import Trial
from esbi_cli.vault import Vault

TASKS = ("ingest", "ask")
RELIABLE = 0.8  # a model must succeed on at least this share of cases to be recommended


@dataclass
class ModelSummary:
    model: str
    task: str
    trials: int
    ok_rate: float
    first_try_rate: float
    median_latency_s: float
    tokens_per_case: float
    cost_usd: float
    language_rate: float | None = None  # ingest only: answers in the wanted language
    avg_concepts: float | None = None  # ingest only
    cites_rate: float | None = None  # ask only


def _rate(flags: list[bool]) -> float:
    return sum(flags) / len(flags)


def summarize(trials: list[Trial], prices: dict[str, float]) -> list[ModelSummary]:
    """One row per (model, task). `prices` is USD per million tokens; unknown models cost 0."""
    summaries = []
    for key in dict.fromkeys((t.model, t.task) for t in trials):
        model, task = key
        rows = [t for t in trials if (t.model, t.task) == key]
        good = [t for t in rows if t.ok]
        summary = ModelSummary(
            model=model,
            task=task,
            trials=len(rows),
            ok_rate=_rate([t.ok for t in rows]),
            first_try_rate=_rate([t.first_try for t in rows]),
            median_latency_s=median(t.latency_s for t in rows),
            tokens_per_case=mean(t.tokens for t in rows),
            cost_usd=sum(t.tokens for t in rows) / 1_000_000 * prices.get(model, 0.0),
        )
        if task == "ingest":
            summary.language_rate = _rate([t.metrics["in_language"] for t in good]) if good else 0.0
            summary.avg_concepts = mean(t.metrics["concepts"] for t in good) if good else 0.0
        else:
            summary.cites_rate = _rate([t.metrics["cites_expected"] for t in good]) if good else 0.0
        summaries.append(summary)
    return summaries


def suggest_routing(summaries: list[ModelSummary]) -> dict[str, str | None]:
    """Per task: the best reliable model (fewest retries, best quality, then fastest, then cheapest)."""
    routing: dict[str, str | None] = {}
    for task in TASKS:
        reliable = [s for s in summaries if s.task == task and s.ok_rate >= RELIABLE]
        best = min(
            reliable,
            key=lambda s: (
                -s.first_try_rate,
                -(s.language_rate if s.language_rate is not None else s.cites_rate or 0.0),
                s.median_latency_s,
                s.cost_usd,
            ),
            default=None,
        )
        routing[task] = best.model if best else None
    return routing


def render_report(
    summaries: list[ModelSummary],
    routing: dict[str, str | None],
    when: datetime,
    language: str,
) -> str:
    L = partial(lang.t, language)
    lines = [f"# {L('bench_title', when=f'{when:%Y-%m-%d %H:%M}')}", ""]
    for task in TASKS:
        rows = [s for s in summaries if s.task == task]
        if not rows:
            continue
        extra = L("bench_extra_ingest" if task == "ingest" else "bench_extra_ask")
        lines += [f"## {task}", L("bench_header", extra=extra), "|---|---|---|---|---|---|---|"]
        for s in rows:
            detail = (
                f"{s.language_rate:.0%} / {s.avg_concepts:.1f}"
                if s.language_rate is not None
                else f"{s.cites_rate:.0%}"
            )
            lines.append(
                f"| {s.model} | {s.ok_rate:.0%} | {s.first_try_rate:.0%} | {s.median_latency_s:.1f} | "
                f"{s.tokens_per_case:.0f} | {s.cost_usd:.4f} | {detail} |"
            )
        lines.append("")
    lines += [f"## {L('bench_routing')}", ""]
    for task, model in routing.items():
        lines.append(f"- {task} → " + (f"`{model}`" if model else L("bench_none")))
    lines += ["", L("bench_footer")]
    return "\n".join(lines) + "\n"


def save_report(vault: Vault, text: str, when: datetime) -> Path:
    path = vault.root / ".esbi" / "bench" / f"{when:%Y-%m-%d-%H%M}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
