"""Drain the ingest queue within limits, isolating failures per item."""

from collections.abc import Callable
from dataclasses import dataclass, field

from esbi_cli.ingest.pipeline import IngestResult
from esbi_cli.interrupts import Interrupted, handling, interruptible
from esbi_cli.llm.adapter import LLMError, LLMTimeout
from esbi_cli.queue import Queue


@dataclass
class RunLimits:
    max_sources: int
    max_tokens: int | None = None


@dataclass
class Failure:
    name: str  # the label (clip title, file name) or the target
    attempt: int  # which attempt this was
    error: str
    parked: bool  # out of attempts: it waits for `sb retry`


@dataclass
class RunSummary:
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[Failure] = field(default_factory=list)
    tokens_used: int = 0
    # "max_sources" | "token_budget" | "llm_unavailable" | "interrupted" | None (queue drained)
    stopped_by: str | None = None
    signum: int | None = None  # set when stopped_by == "interrupted"
    released: int = 0  # items put back in the queue by an interruption


def run_queue(
    queue: Queue,
    ingest_fn: Callable[[str], IngestResult],
    limits: RunLimits,
    tokens_used: Callable[[], int] = lambda: 0,
    on_event: Callable[..., None] | None = None,  # on_event("source_started", target=..., ...)
) -> RunSummary:
    summary = RunSummary()
    if on_event:
        on_event("started", queued=queue.counts().get("queued", 0))
    start_tokens = tokens_used()
    tried: set[int] = set()  # a failed item is requeued, but must wait for the next run
    item = None
    with handling():
        try:
            while True:
                with interruptible():  # a signal that came between two items stops the run here
                    pass
                claimed = queue.claim(1, exclude=tried)
                if not claimed:
                    break
                item = claimed[0]
                if len(tried) >= limits.max_sources:
                    queue.release(item.id)
                    summary.stopped_by = "max_sources"
                    break
                if (
                    limits.max_tokens is not None
                    and tokens_used() - start_tokens >= limits.max_tokens
                ):
                    queue.release(item.id)
                    summary.stopped_by = "token_budget"
                    break
                tried.add(item.id)
                if on_event:
                    on_event("source_started", target=item.target, title=item.label or item.target)
                try:
                    with interruptible():
                        result = ingest_fn(item.target)
                except Exception as exc:  # one bad source must not stop the nightly batch
                    if isinstance(exc, LLMError) and not isinstance(exc, LLMTimeout):
                        # the model is the problem, not this source: keep it fresh and stop
                        queue.release(item.id)
                        summary.stopped_by = "llm_unavailable"
                        break
                    error = f"{type(exc).__name__}: {exc}"
                    queue.fail(item.id, error)
                    attempt = item.attempts + 1
                    summary.failures.append(
                        Failure(
                            item.label or item.target, attempt, error, attempt >= queue.max_attempts
                        )
                    )
                    if on_event:
                        on_event(
                            "source_failed",
                            target=item.target,
                            attempt=attempt,
                            max_attempts=queue.max_attempts,
                            parked=attempt >= queue.max_attempts,
                            reason=" ".join(error.split()),
                        )
                    summary.failed += 1
                    continue
                queue.complete(item.id)
                if result.status == "skipped":
                    summary.skipped += 1
                else:
                    summary.ingested += 1
        except Interrupted as exc:
            # like an outage: the item goes back untouched. Release only affects a row still
            # `processing`, so a finished item is not undone.
            summary.stopped_by, summary.signum = "interrupted", exc.signum
            summary.released = int(item is not None and queue.release(item.id))
    summary.tokens_used = tokens_used() - start_tokens
    return summary
