"""Append-only record of every `sb run`: feeds the daily index and the "is the nightly due?" check."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class RunRecord:
    started: datetime
    finished: datetime
    ingested: int
    skipped: int
    failed: int
    tokens_used: int
    stopped_by: str | None  # None = queue drained; see run.RunSummary
    trigger: str  # "scheduled" (sb run --if-due) or "manual"


class RunLog:
    def __init__(self, path: Path, keep: int = 500):
        self.path, self.keep = path, keep  # older runs are dropped: only recent ones are ever read

    def record(self, run: RunRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            **asdict(run),
            "started": run.started.isoformat(),
            "finished": run.finished.isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if len(lines) > self.keep:
            self.path.write_text("\n".join(lines[-self.keep :]) + "\n", encoding="utf-8")

    def runs(self) -> list[RunRecord]:
        if not self.path.exists():
            return []
        rows = [
            json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line
        ]
        return [
            RunRecord(
                **{
                    **row,
                    "started": datetime.fromisoformat(row["started"]),
                    "finished": datetime.fromisoformat(row["finished"]),
                }
            )
            for row in rows
        ]


def is_due(runs: list[RunRecord], now: datetime, at: tuple[int, int] = (3, 0)) -> bool:
    """Has the nightly run still to happen?

    True until a scheduled run that reached the LLM has started since the most recent `at` (hour, minute)
    boundary. Runs stopped by an LLM outage or an interruption don't count (retried on the next
    hourly check) and neither do manual runs (which may be partial).
    """
    boundary = now.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    if now < boundary:
        boundary -= timedelta(days=1)
    return not any(
        r.trigger == "scheduled"
        and r.stopped_by not in ("llm_unavailable", "interrupted")
        and r.started >= boundary
        for r in runs
    )


def trim_log(path: Path, limit_bytes: int = 1_000_000, keep_bytes: int = 200_000) -> None:
    """Cut a log that passed `limit_bytes` to its last `keep_bytes`, from a whole line. launchd
    appends to this file, so it is trimmed in place at the start of a run, never renamed."""
    if not path.is_file() or path.stat().st_size <= limit_bytes:
        return
    tail = path.read_bytes()[-keep_bytes:]
    path.write_bytes(tail[tail.find(b"\n") + 1 :])
