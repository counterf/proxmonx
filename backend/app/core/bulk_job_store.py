"""Bulk job store -- persists server-side bulk update orchestration jobs."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bulk_jobs (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    guest_ids TEXT NOT NULL,
    results TEXT NOT NULL,
    total INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
)
"""

_PRUNE = """
DELETE FROM bulk_jobs WHERE id NOT IN (
    SELECT id FROM bulk_jobs ORDER BY created_at DESC LIMIT 100
)
"""


class BulkJobResult(BaseModel):
    status: str  # pending|running|success|failed|skipped
    task_id: str | None = None
    error: str | None = None


class BulkJob(BaseModel):
    id: str
    action: str
    status: str  # pending|running|completed|failed
    guest_ids: list[str]
    results: dict[str, BulkJobResult]
    total: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class BulkJobStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row_to_job(self, row: sqlite3.Row) -> BulkJob:
        d = dict(row)
        d["guest_ids"] = json.loads(d["guest_ids"])
        d["results"] = {
            k: BulkJobResult(**v) for k, v in json.loads(d["results"]).items()
        }
        return BulkJob(**d)

    def create(self, job: BulkJob) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO bulk_jobs
                   (id, action, status, guest_ids, results, total, completed, failed, skipped,
                    created_at, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.id, job.action, job.status,
                    json.dumps(job.guest_ids),
                    json.dumps({k: v.model_dump() for k, v in job.results.items()}),
                    job.total, job.completed, job.failed, job.skipped,
                    job.created_at, job.started_at, job.finished_at,
                ),
            )
            conn.execute(_PRUNE)

    def update(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "completed", "failed", "skipped", "results", "started_at", "finished_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        # serialize results dict if present
        if "results" in updates and isinstance(updates["results"], dict):
            updates["results"] = json.dumps(
                {k: (v.model_dump() if isinstance(v, BulkJobResult) else v) for k, v in updates["results"].items()}
            )
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE bulk_jobs SET {set_clause} WHERE id = ?", values)

    def update_result(self, job_id: str, guest_id: str, status: str, task_id: str | None = None, error: str | None = None) -> None:
        """Update a single guest result within the job, incrementing counters atomically."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bulk_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return
            job = self._row_to_job(row)
            prev = job.results.get(guest_id)
            prev_status = prev.status if prev else None
            job.results[guest_id] = BulkJobResult(status=status, task_id=task_id, error=error)
            if status != prev_status:
                if status == "success":
                    job.completed += 1
                elif status == "failed":
                    job.failed += 1
                elif status == "skipped":
                    job.skipped += 1
            results_json = json.dumps({k: v.model_dump() for k, v in job.results.items()})
            conn.execute(
                "UPDATE bulk_jobs SET results = ?, completed = ?, failed = ?, skipped = ? WHERE id = ?",
                (results_json, job.completed, job.failed, job.skipped, job_id),
            )

    def get(self, job_id: str) -> BulkJob | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bulk_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_recent(self, limit: int = 50) -> list[BulkJob]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bulk_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_job(r) for r in rows]
