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
