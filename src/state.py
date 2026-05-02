from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .models import Job


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    url TEXT NOT NULL,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    closed_at TIMESTAMP,
    notified BOOLEAN DEFAULT 0,
    discord_message_id TEXT,
    applied BOOLEAN DEFAULT 0,
    applied_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_seen_company ON seen(company);
CREATE INDEX IF NOT EXISTS idx_seen_first_seen ON seen(first_seen);
CREATE INDEX IF NOT EXISTS idx_seen_message_id ON seen(discord_message_id);

CREATE TABLE IF NOT EXISTS run_log (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    jobs_fetched INTEGER,
    jobs_new INTEGER,
    jobs_notified INTEGER,
    errors TEXT
);
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class State:
    def __init__(self, db_path: str | Path):
        self.path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # detect_types so TIMESTAMP round-trips as datetime
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._txn() as conn:
            conn.executescript(SCHEMA)

    # ---- seen table ----

    def get_open_ids(self) -> set[str]:
        with self._txn() as conn:
            rows = conn.execute("SELECT id FROM seen WHERE closed_at IS NULL").fetchall()
        return {r["id"] for r in rows}

    def insert(self, job: Job, *, notified: bool = False) -> None:
        now = _utcnow()
        with self._txn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO seen
                  (id, company, title, location, url, first_seen, last_seen, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job.id, job.company, job.title, job.location, job.url, now, now, int(notified)),
            )

    def bulk_update_last_seen(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        now = _utcnow()
        with self._txn() as conn:
            conn.executemany(
                "UPDATE seen SET last_seen = ?, closed_at = NULL WHERE id = ?",
                [(now, i) for i in ids],
            )

    def bulk_close(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        now = _utcnow()
        with self._txn() as conn:
            conn.executemany(
                "UPDATE seen SET closed_at = ? WHERE id = ? AND closed_at IS NULL",
                [(now, i) for i in ids],
            )

    def mark_notified(self, job_id: str, message_id: str) -> None:
        with self._txn() as conn:
            conn.execute(
                "UPDATE seen SET notified = 1, discord_message_id = ? WHERE id = ?",
                (message_id, job_id),
            )

    def mark_notified_no_message(self, ids: Iterable[str]) -> None:
        """Bootstrap helper: mark notified=1 without a Discord message ID."""
        ids = list(ids)
        if not ids:
            return
        with self._txn() as conn:
            conn.executemany(
                "UPDATE seen SET notified = 1 WHERE id = ?",
                [(i,) for i in ids],
            )

    def get_known_source_keys(self) -> set[str]:
        """Returns set of "ats:slug" strings that already have at least one row
        in seen. Used to detect first-touch sources that should auto-bootstrap
        instead of pinging their entire backlog."""
        with self._txn() as conn:
            rows = conn.execute("SELECT DISTINCT id FROM seen").fetchall()
        keys: set[str] = set()
        for r in rows:
            parts = r["id"].split(":", 2)
            if len(parts) >= 2:
                keys.add(f"{parts[0]}:{parts[1]}")
        return keys

    def mark_applied(self, job_id: str) -> None:
        with self._txn() as conn:
            conn.execute(
                "UPDATE seen SET applied = 1, applied_at = ? WHERE id = ? AND applied = 0",
                (_utcnow(), job_id),
            )

    def unapplied_recent(self, days: int = 30) -> list[sqlite3.Row]:
        """Rows eligible for reaction sync: notified, not applied, recent, with a message id."""
        cutoff = _utcnow().timestamp() - days * 86400
        with self._txn() as conn:
            return conn.execute(
                """
                SELECT id, company, title, discord_message_id
                FROM seen
                WHERE applied = 0
                  AND notified = 1
                  AND discord_message_id IS NOT NULL
                  AND CAST(strftime('%s', first_seen) AS INTEGER) >= ?
                """,
                (int(cutoff),),
            ).fetchall()

    # ---- run log ----

    def start_run(self) -> int:
        with self._txn() as conn:
            cur = conn.execute(
                "INSERT INTO run_log (started_at) VALUES (?)",
                (_utcnow(),),
            )
            return cur.lastrowid or 0

    def finish_run(
        self,
        run_id: int,
        *,
        jobs_fetched: int,
        jobs_new: int,
        jobs_notified: int,
        errors: str = "",
    ) -> None:
        with self._txn() as conn:
            conn.execute(
                """
                UPDATE run_log
                SET finished_at = ?, jobs_fetched = ?, jobs_new = ?, jobs_notified = ?, errors = ?
                WHERE run_id = ?
                """,
                (_utcnow(), jobs_fetched, jobs_new, jobs_notified, errors, run_id),
            )
