"""Persistent work queue of sources waiting to be ingested (SQLite)."""

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "trk", "trkemail"})


def normalize_target(target: str) -> str:
    """Canonical form used to detect duplicates: URLs lose tracking params and fragments."""
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        return str(Path(target).expanduser().resolve())
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (parsed.scheme, parsed.netloc.lower(), path, "", urlencode(sorted(query)), "")
    )


_COLUMNS = "id, target, origin, attempts, error, captured, label"


def _item(row: tuple) -> "Item":
    id_, target, origin, attempts, error, captured, label = row
    return Item(
        id_,
        target,
        origin,
        attempts,
        error,
        date.fromisoformat(captured) if captured else None,
        label,
    )


@dataclass
class Item:
    id: int
    target: str
    origin: str
    attempts: int = 0
    error: str | None = None
    captured: date | None = None  # when the source was saved, if known (legacy import)
    label: str | None = None  # human-readable name (clip title, file name)


class Queue:
    def __init__(self, path: Path, max_attempts: int = 3):
        self.max_attempts = max_attempts
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                target TEXT NOT NULL UNIQUE,
                origin TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                captured TEXT,
                label TEXT
            )"""
        )
        # databases created before these columns existed keep working
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(items)")}
        for column in ("captured", "label"):
            if column not in existing:
                self._db.execute(f"ALTER TABLE items ADD COLUMN {column} TEXT")
        self._db.commit()

    def add(
        self,
        target: str,
        origin: str,
        captured: date | None = None,
        label: str | None = None,
    ) -> bool:
        """Queue a source. Returns False if an equivalent one is already known."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO items (target, origin, captured, label) VALUES (?, ?, ?, ?)",
            (normalize_target(target), origin, captured.isoformat() if captured else None, label),
        )
        self._db.commit()
        return cur.rowcount == 1

    def counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT status, COUNT(*) FROM items GROUP BY status").fetchall()
        return dict(rows)

    def claim(self, n: int, exclude: Collection[int] = ()) -> list[Item]:
        """Take up to n of the oldest queued items (skipping `exclude`), marking them processing."""
        skip = ",".join("?" for _ in exclude)
        rows = self._db.execute(
            f"SELECT {_COLUMNS} FROM items WHERE status = 'queued'"
            + (f" AND id NOT IN ({skip})" if skip else "")
            + " ORDER BY id LIMIT ?",
            (*exclude, n),
        ).fetchall()
        self._db.executemany(
            "UPDATE items SET status = 'processing' WHERE id = ?", [(r[0],) for r in rows]
        )
        self._db.commit()
        return [_item(r) for r in rows]

    def complete(self, item_id: int) -> None:
        self._db.execute("UPDATE items SET status = 'done' WHERE id = ?", (item_id,))
        self._db.commit()

    def fail(self, item_id: int, error: str) -> None:
        """Record a failed attempt: retry next run, or park as 'failed' after max_attempts."""
        self._db.execute(
            """UPDATE items SET attempts = attempts + 1, error = ?,
               status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'queued' END
               WHERE id = ?""",
            (error, self.max_attempts, item_id),
        )
        self._db.commit()

    def items(self, status: str) -> list[Item]:
        rows = self._db.execute(
            f"SELECT {_COLUMNS} FROM items WHERE status = ? ORDER BY id", (status,)
        ).fetchall()
        return [_item(r) for r in rows]

    def get(self, target: str) -> Item | None:
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM items WHERE target = ?", (normalize_target(target),)
        ).fetchone()
        return _item(row) if row else None

    def requeue_failed(self, target: str | None = None) -> int:
        """Put parked failures back in the queue with a fresh attempt count. Returns how many."""
        sql = (
            "UPDATE items SET status = 'queued', attempts = 0, error = NULL WHERE status = 'failed'"
        )
        args: tuple = ()
        if target is not None:
            sql, args = sql + " AND target = ?", (normalize_target(target),)
        cur = self._db.execute(sql, args)
        self._db.commit()
        return cur.rowcount

    def remove(self, target: str) -> bool:
        """Delete an item whatever its state. The original file, if any, is not touched."""
        cur = self._db.execute("DELETE FROM items WHERE target = ?", (normalize_target(target),))
        self._db.commit()
        return cur.rowcount == 1

    def recover(self) -> int:
        """Requeue items a previous run claimed but never finished. Returns how many. The lost run
        counts as an attempt: an item that kills the process (a PDF that exhausts memory) is parked
        after max_attempts instead of killing every run."""
        cur = self._db.execute(
            """UPDATE items SET attempts = attempts + 1,
               status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'queued' END,
               error = CASE WHEN attempts + 1 >= ? THEN 'the run died while reading this' ELSE error END
               WHERE status = 'processing'""",
            (self.max_attempts, self.max_attempts),
        )
        self._db.commit()
        return cur.rowcount

    def release(self, item_id: int) -> bool:
        """Give back a claimed item untouched (no attempt counted). False if it was not claimed."""
        cur = self._db.execute(
            "UPDATE items SET status = 'queued' WHERE id = ? AND status = 'processing'", (item_id,)
        )
        self._db.commit()
        return cur.rowcount == 1
