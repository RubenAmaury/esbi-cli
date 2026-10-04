"""Automatic quality signals for one model output. No LLM judge: cheap, deterministic, comparable."""

from esbi_cli import lang
from esbi_cli.ask.answer import Answer
from esbi_cli.ingest.plan import plan_prose
from esbi_cli.llm.schemas import EditPlan
from esbi_cli.vault import Vault


def plan_metrics(plan: EditPlan, vault: Vault) -> dict:
    """How usable is this ingest plan? Counts what the worker would have to throw away."""
    referenced = [*plan.related_pages, *(c.page for c in plan.contradictions)]
    return {
        "concepts": len(plan.concepts),
        "entities": len(plan.entities),
        "in_language": not lang.wrong_language(plan_prose(plan), vault.language),
        "bad_refs": sum(vault.resolve_page(name) is None for name in referenced),
    }


def answer_metrics(answer: Answer, expected: str) -> dict:
    """An `ask` answer is good if it is grounded and cites the page the question was made from."""
    return {"grounded": answer.grounded, "cites_expected": expected in answer.citations}
