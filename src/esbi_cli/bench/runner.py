"""Run every candidate model over the same cases and record what it cost and how usable it was."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from esbi_cli.ask.answer import answer_question
from esbi_cli.bench.cases import AskCase, IngestCase
from esbi_cli.bench.metrics import answer_metrics, plan_metrics
from esbi_cli.ingest.plan import build_prompt, make_plan
from esbi_cli.ingest.retrieve import find_candidates
from esbi_cli.llm.adapter import LLM
from esbi_cli.privacy import private_titles, sends_text_out
from esbi_cli.vault import Vault


@dataclass
class Trial:
    model: str
    task: str  # "ingest" | "ask"
    case: str
    ok: bool  # ingest: a valid plan came back; ask: a grounded answer came back
    first_try: bool  # no retry was needed
    latency_s: float
    tokens: int
    metrics: dict = field(default_factory=dict)
    error: str | None = None


class _CountingLLM:
    """Wraps an LLM to count calls: more than one call means the worker had to retry."""

    def __init__(self, inner: LLM):
        self.inner, self.calls = inner, 0

    @property
    def tokens_used(self) -> int:
        return self.inner.tokens_used

    @property
    def sends_text_out(self) -> bool:  # the wrapper must not hide that the model is a cloud one
        return bool(getattr(self.inner, "sends_text_out", False))

    def complete_json(self, **kwargs) -> str:
        self.calls += 1
        return self.inner.complete_json(**kwargs)


def run_benchmark(
    models: list[str],
    ingest_cases: list[IngestCase],
    ask_cases: list[AskCase],
    vault: Vault,
    llm_factory: Callable[[str], LLM],
    clock: Callable[[], float] = time.monotonic,
    max_source_chars: int = 12000,
    on_trial: Callable[[Trial], None] | None = None,
) -> list[Trial]:
    """The wiki is only read, never written: plans are scored, not applied."""
    trials: list[Trial] = []
    schema = vault.schema_text()

    def measure(model: str, task: str, case: str, work: Callable[[LLM], tuple[bool, dict]]) -> None:
        started = clock()
        llm: _CountingLLM | None = None
        tokens_before = 0
        try:
            llm = _CountingLLM(
                llm_factory(model)
            )  # building the model can fail too (bad name, no key)
            tokens_before = llm.tokens_used
            ok, metrics = work(llm)
            error = None
        except Exception as exc:  # a broken model is a result, not a crash
            ok, metrics, error = False, {}, f"{type(exc).__name__}: {exc}"
        trial = Trial(
            model=model,
            task=task,
            case=case,
            ok=ok,
            first_try=ok and llm is not None and llm.calls == 1,
            latency_s=clock() - started,
            tokens=(llm.tokens_used - tokens_before) if llm else 0,
            metrics=metrics,
            error=error,
        )
        trials.append(trial)
        if on_trial:
            on_trial(trial)

    for model in models:
        for case in ingest_cases:

            def ingest(llm, case=case):
                candidates = find_candidates(
                    vault,
                    f"{case.doc.title}\n{case.doc.text[:max_source_chars]}",
                    exclude=private_titles(vault) if sends_text_out(llm) else frozenset(),
                )
                system, user = build_prompt(
                    schema, case.doc, candidates, max_source_chars, language=vault.language
                )
                plan, _warnings = make_plan(llm, system, user, vault.language)
                return True, plan_metrics(plan, vault)

            measure(model, "ingest", case.name, ingest)
        for ask_case in ask_cases:

            def ask(llm, ask_case=ask_case):
                answer = answer_question(vault, llm, ask_case.question)
                return answer.grounded, answer_metrics(answer, ask_case.expected)

            measure(model, "ask", ask_case.name, ask)
    return trials
