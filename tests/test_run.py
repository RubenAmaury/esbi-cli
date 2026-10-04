import os
import signal
import time

import pytest
from conftest import FakeLLM, make_plan

from esbi_cli.extract import ExtractError
from esbi_cli.ingest.pipeline import IngestResult, ingest
from esbi_cli.llm.adapter import LLMError, LLMTimeout
from esbi_cli.run import RunLimits, run_queue


def fill(queue, n):
    for i in range(n):
        queue.add(f"https://x.test/{i}", origin="inbox")


def test_run_processes_up_to_max_sources_and_leaves_the_rest_queued(queue, doc):
    fill(queue, 5)
    seen = []

    def ingest_fn(target):
        seen.append(target)
        return IngestResult("ingested", doc)

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=3))

    assert seen == ["https://x.test/0", "https://x.test/1", "https://x.test/2"]
    assert (summary.ingested, summary.stopped_by) == (3, "max_sources")
    assert queue.counts() == {"done": 3, "queued": 2}


def test_a_failing_source_is_recorded_for_retry_and_does_not_stop_the_run(queue, doc):
    fill(queue, 3)

    def ingest_fn(target):
        if target.endswith("/1"):
            raise ExtractError("no readable content")
        return IngestResult("ingested", doc)

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert (summary.ingested, summary.failed, summary.stopped_by) == (2, 1, None)
    assert queue.counts() == {"done": 2, "queued": 1}
    [retry] = queue.items("queued")
    assert retry.target == "https://x.test/1" and "no readable content" in retry.error


def test_a_queue_emptied_exactly_at_the_cap_is_reported_as_drained_and_skips_are_counted(
    queue, doc
):
    fill(queue, 2)
    statuses = iter(["ingested", "skipped"])

    summary = run_queue(
        queue, lambda target: IngestResult(next(statuses), doc), RunLimits(max_sources=2)
    )

    assert (summary.ingested, summary.skipped, summary.stopped_by) == (1, 1, None)
    assert queue.counts() == {"done": 2}


def test_run_stops_once_the_token_budget_is_spent(queue, doc):
    fill(queue, 5)
    spent = [50]  # the counter may already be non-zero when the run starts

    def ingest_fn(target):
        spent[0] += 400
        return IngestResult("ingested", doc)

    summary = run_queue(
        queue,
        ingest_fn,
        RunLimits(max_sources=10, max_tokens=1000),
        tokens_used=lambda: spent[0],
    )

    assert (summary.ingested, summary.stopped_by, summary.tokens_used) == (3, "token_budget", 1200)
    assert queue.counts() == {"done": 3, "queued": 2}


def test_an_unreachable_llm_aborts_the_run_without_burning_retry_attempts(queue):
    fill(queue, 3)
    calls = []

    def ingest_fn(target):
        calls.append(target)
        raise LLMError("http://localhost:11434 unreachable")

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert calls == ["https://x.test/0"]
    assert (summary.stopped_by, summary.failed) == ("llm_unavailable", 0)
    assert queue.counts() == {"queued": 3}
    assert queue.items("queued")[0].attempts == 0


def test_a_source_that_times_out_fails_alone_and_the_run_goes_on(queue):
    fill(queue, 3)

    def ingest_fn(target):
        if target.endswith("/0"):
            raise LLMTimeout("timed out after 300s")
        return IngestResult("ingested", None)

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert (summary.ingested, summary.failed, summary.stopped_by) == (2, 1, None)


def test_each_failed_source_is_reported_with_its_attempt_and_whether_it_is_now_parked(queue):
    fill(queue, 2)
    queue.fail(queue.claim(1)[0].id, "ExtractError: old")  # x/0 has already failed twice
    queue.fail(queue.claim(1)[0].id, "ExtractError: old")
    queue.add("https://x.test/9", origin="inbox", label="A clipped page")

    def ingest_fn(target):
        raise ExtractError(f"no readable content in {target}")

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert [(f.name, f.attempt, f.parked) for f in summary.failures] == [
        ("https://x.test/0", 3, True),
        ("https://x.test/1", 1, False),
        ("A clipped page", 1, False),
    ]
    assert summary.failures[0].error == "ExtractError: no readable content in https://x.test/0"
    assert summary.failed == 3


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_a_signal_puts_the_item_in_flight_back_without_counting_an_attempt(queue, doc, signum):
    fill(queue, 3)
    before = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    calls = []

    def ingest_fn(target):
        calls.append(target)
        os.kill(os.getpid(), signum)  # the user presses Ctrl-C, or a Cancel button sends SIGTERM
        time.sleep(5)  # never reached: the handler raises in this very thread
        return IngestResult("ingested", doc)

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert calls == ["https://x.test/0"]
    assert (summary.stopped_by, summary.signum, summary.released) == ("interrupted", signum, 1)
    assert (summary.failed, summary.ingested) == (0, 0)
    assert queue.counts() == {"queued": 3}
    assert [i.attempts for i in queue.items("queued")] == [0, 0, 0]
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == before


def test_work_finished_before_the_signal_stays_done(queue, doc):
    fill(queue, 3)

    def ingest_fn(target):
        if target.endswith("/1"):
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)
        return IngestResult("ingested", doc)

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert (summary.ingested, summary.stopped_by) == (1, "interrupted")
    assert queue.counts() == {"done": 1, "queued": 2}


def test_a_signal_during_an_ingest_applies_the_whole_note_then_stops(queue, doc, vault, cfg):
    """The write of a note is not interruptible: it lands complete, and the stop comes right after."""
    queue.add("https://x.test/a", origin="inbox")

    def ingest_fn(target):
        return ingest(
            target,
            vault=vault,
            llm=FakeLLM(make_plan()),
            cfg=cfg,
            extractor=lambda _: doc,
            before_write=lambda: os.kill(os.getpid(), signal.SIGINT),  # lands inside the write
        )

    summary = run_queue(queue, ingest_fn, RunLimits(max_sources=10))

    assert summary.stopped_by == "interrupted"
    [note] = vault.iter_pages(("sources",))
    assert note.title == "Arnés de agentes" and note.body.strip()
    assert "Arnés de agentes" in (vault.root / "log.md").read_text(encoding="utf-8")
    assert queue.counts() == {"queued": 1}  # the next run finds the note and skips the source
