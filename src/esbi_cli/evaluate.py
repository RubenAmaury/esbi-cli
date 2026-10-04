"""Score retrieval (and answers) on questions whose source is known: the number to beat before
changing how `sb ask` finds pages."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from esbi_cli.ask.answer import answer_question, rewrite_question
from esbi_cli.ingest.retrieve import find_candidates
from esbi_cli.llm.adapter import LLM
from esbi_cli.vault import Vault, fold


@dataclass
class Golden:
    question: str
    expect: list[str]  # titles, or the start of titles: long source titles are cut


@dataclass
class Case:
    question: str
    expect: list[str]
    retrieved: list[str]
    rank: int | None  # 1 = first page returned; None = not among them
    grounded: bool | None = None  # only when answers were asked for
    cited: bool | None = None


@dataclass
class EvalReport:
    k: int
    cases: list[Case] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return sum(c.rank is not None for c in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def mrr(self) -> float:
        return (
            sum(1 / c.rank for c in self.cases if c.rank) / len(self.cases) if self.cases else 0.0
        )

    def rate(self, attribute: str) -> float | None:
        values = [getattr(c, attribute) for c in self.cases if getattr(c, attribute) is not None]
        return sum(values) / len(values) if values else None


def load_golden(path: Path) -> list[Golden]:
    golden = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            golden.append(Golden(str(row["question"]), [str(e) for e in row["expect"]]))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                f'{path.name} line {number}: need {{"question": ..., "expect": [...]}}'
            ) from exc
    return golden


def _matches(title: str, expect: list[str]) -> bool:
    return any(fold(title).startswith(fold(e)) for e in expect)


def evaluate(
    vault: Vault,
    golden: list[Golden],
    k: int = 6,
    rewrite_llm: LLM | None = None,
    answer_llm: LLM | None = None,
) -> EvalReport:
    report = EvalReport(k)
    for item in golden:
        extra = rewrite_question(rewrite_llm, item.question, vault.language) if rewrite_llm else []
        titles = [c.title for c in find_candidates(vault, item.question, limit=k, extra=extra)]
        rank = next((i + 1 for i, t in enumerate(titles) if _matches(t, item.expect)), None)
        case = Case(item.question, item.expect, titles, rank)
        if answer_llm:
            answer = answer_question(
                vault, answer_llm, item.question, rewrite=rewrite_llm is not None
            )
            case.grounded = answer.grounded
            case.cited = any(_matches(c, item.expect) for c in answer.citations)
        report.cases.append(case)
    return report
