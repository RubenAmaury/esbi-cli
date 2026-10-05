from dataclasses import replace
from datetime import datetime

from esbi_cli.runlog import RunLog, RunRecord, is_due

RUN = RunRecord(
    started=datetime(2026, 9, 29, 3, 5),
    finished=datetime(2026, 9, 29, 3, 9, 30),
    ingested=6,
    skipped=1,
    failed=0,
    tokens_used=39711,
    stopped_by="max_sources",
    trigger="scheduled",
)


def test_run_log_keeps_every_run_in_order_across_instances(tmp_path):
    path = tmp_path / ".esbi" / "runs.jsonl"
    later = replace(RUN, started=datetime(2026, 9, 30, 3, 5), stopped_by=None, trigger="manual")

    RunLog(path).record(RUN)
    RunLog(path).record(later)

    assert RunLog(path).runs() == [RUN, later]
    assert RunLog(tmp_path / "never-written.jsonl").runs() == []


def test_nightly_is_due_until_a_scheduled_run_completes_after_the_daily_boundary():
    morning = datetime(2026, 9, 29, 10, 0)
    assert is_due([], now=morning) is True
    assert is_due([RUN], now=morning) is False  # completed at 03:05 today


def test_before_the_boundary_yesterdays_run_still_counts_and_after_it_the_nightly_is_due_again():
    yesterday_night = replace(RUN, started=datetime(2026, 9, 28, 3, 5))
    assert is_due([yesterday_night], now=datetime(2026, 9, 29, 2, 0)) is False
    assert is_due([yesterday_night], now=datetime(2026, 9, 29, 3, 1)) is True


def test_an_llm_outage_or_a_manual_run_does_not_satisfy_the_nightly():
    morning = datetime(2026, 9, 29, 10, 0)
    outage = replace(RUN, stopped_by="llm_unavailable")
    manual = replace(RUN, trigger="manual")
    assert is_due([outage], now=morning) is True  # retried on the next hourly check
    assert is_due([manual], now=morning) is True
    assert is_due([outage, RUN], now=morning) is False


def test_an_interrupted_run_does_not_satisfy_the_nightly():
    stopped = replace(RUN, stopped_by="interrupted")
    assert is_due([stopped], now=datetime(2026, 9, 29, 10, 0)) is True


def test_the_run_log_keeps_only_the_most_recent_runs_so_it_cannot_grow_forever(tmp_path):
    log = RunLog(tmp_path / "runs.jsonl", keep=3)

    for day in range(1, 7):
        log.record(replace(RUN, started=datetime(2026, 9, day, 3, 5)))

    assert [r.started.day for r in log.runs()] == [4, 5, 6]


def test_the_daily_boundary_can_be_any_time_of_day_not_only_a_full_hour():
    ran_at_five_past_five = replace(RUN, started=datetime(2026, 9, 29, 5, 5))
    at = (4, 30)
    assert is_due([], now=datetime(2026, 9, 29, 4, 10), at=at) is True  # yesterday's boundary
    assert is_due([ran_at_five_past_five], now=datetime(2026, 9, 29, 6, 0), at=at) is False
    # a run before today's 04:30 is yesterday's: today's is still to come after 04:30
    early = replace(RUN, started=datetime(2026, 9, 29, 4, 10))
    assert is_due([early], now=datetime(2026, 9, 29, 4, 40), at=at) is True


def test_a_scheduled_run_that_stopped_at_the_source_limit_drains_the_backlog_on_the_next_tick():
    morning = datetime(2026, 9, 29, 10, 0)
    assert is_due([RUN], now=morning, queued=3) is True  # stopped_by="max_sources", items left
    assert is_due([RUN], now=morning, queued=0) is False  # nothing left: the day is done


def test_the_backlog_is_drained_only_after_a_run_that_stopped_for_the_source_limit():
    morning = datetime(2026, 9, 29, 10, 0)
    for reason in (None, "token_budget", "usd_budget"):
        assert is_due([replace(RUN, stopped_by=reason)], now=morning, queued=5) is False, reason


def test_the_drain_follows_the_latest_scheduled_run_and_ignores_manual_runs():
    morning = datetime(2026, 9, 29, 10, 0)
    drained = replace(RUN, started=datetime(2026, 9, 29, 4, 5), stopped_by=None)
    outage = replace(RUN, started=datetime(2026, 9, 29, 5, 5), stopped_by="llm_unavailable")
    manual = replace(RUN, started=datetime(2026, 9, 29, 6, 5), trigger="manual")
    assert is_due([RUN, drained], now=morning, queued=2) is False  # the last batch finished
    assert is_due([RUN, outage], now=morning, queued=2) is False  # model down: wait for tomorrow
    assert is_due([RUN, manual], now=morning, queued=2) is True  # a manual run is not a batch
    assert is_due([drained, replace(RUN, started=datetime(2026, 9, 29, 7, 5))], morning, queued=2)


def test_yesterdays_limit_run_is_not_a_reason_to_drain_but_the_nightly_is_due_anyway():
    yesterday = replace(RUN, started=datetime(2026, 9, 28, 3, 5))
    assert is_due([yesterday], now=datetime(2026, 9, 29, 3, 30), queued=4) is True  # new day


def _batches(n: int, day=29) -> list[RunRecord]:
    return [replace(RUN, started=datetime(2026, 9, day, 3 + i, 5)) for i in range(n)]


def test_the_hourly_drain_stops_after_max_batches_scheduled_batches_since_the_boundary():
    morning = datetime(2026, 9, 29, 14, 0)
    assert is_due(_batches(5), now=morning, queued=9, max_batches=6) is True
    assert is_due(_batches(6), now=morning, queued=9, max_batches=6) is False
    assert is_due(_batches(2), now=morning, queued=9, max_batches=2) is False
    assert is_due(_batches(6), now=morning, queued=9, max_batches=7) is True


def test_six_batches_a_day_is_the_default_cap():
    morning = datetime(2026, 9, 29, 14, 0)
    assert is_due(_batches(5), now=morning, queued=9) is True
    assert is_due(_batches(6), now=morning, queued=9) is False


def test_only_scheduled_runs_that_reached_the_model_since_the_boundary_count_as_batches():
    morning = datetime(2026, 9, 29, 14, 0)
    yesterday = _batches(5, day=28)  # before the 03:00 boundary
    manual = [replace(r, trigger="manual") for r in _batches(5)]
    outages = [replace(r, stopped_by="llm_unavailable") for r in _batches(5)]
    interrupted = [replace(r, stopped_by="interrupted") for r in _batches(5)]
    batch_one = [replace(RUN, started=datetime(2026, 9, 29, 12, 5))]  # the latest, and the only one
    for noise in (yesterday, manual, outages, interrupted):
        assert is_due([*noise, *batch_one], now=morning, queued=9, max_batches=2) is True, noise
