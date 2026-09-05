"""Transactional job queue with compare-and-set leases and fenced completion."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from server.contracts.jobs import JobLease, JobRun, job_time

JOB_SCHEMA = (
    """CREATE TABLE job_runs (
        job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
        payload_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
        attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        available_at TEXT NOT NULL, lease_owner TEXT, lease_expires_at TEXT,
        heartbeat_at TEXT, result_ref TEXT, error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(kind, input_fingerprint)
    )""",
    "CREATE INDEX job_claim_idx ON job_runs(kind, status, available_at, lease_expires_at)",
)


def require_job_lease(
    conn: sqlite3.Connection, lease: JobLease, *, now: datetime
) -> None:
    row = conn.execute(
        "SELECT 1 FROM job_runs WHERE job_id=? AND status='running' "
        "AND lease_owner=? AND attempt=? AND lease_expires_at>?",
        (lease.job_id, lease.lease_owner, lease.attempt, job_time(now)),
    ).fetchone()
    if row is None:
        raise ValueError("job_lease_lost")


class SQLiteJobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def _transaction(self):
        conn = sqlite3.connect(self.path, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def enqueue(self, kind, payload, *, now):
        if not kind.strip() or not isinstance(payload, dict):
            raise ValueError("job_input_invalid")
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        job_id = hashlib.sha256(f"{kind}:{fingerprint}".encode()).hexdigest()
        at = job_time(now)
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO job_runs(job_id,kind,input_fingerprint,payload_json,status,available_at,created_at,updated_at) "
                "VALUES (?,?,?,?,'queued',?,?,?) ON CONFLICT(job_id) DO NOTHING",
                (job_id, kind, fingerprint, encoded, at, at, at),
            )
            row = conn.execute(
                "SELECT * FROM job_runs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row["payload_json"] != encoded or row["kind"] != kind:
                raise ValueError("job_identity_conflict")
            return _job(row)

    def claim(self, kind, owner, *, now, lease_seconds=60):
        if not owner.strip() or lease_seconds <= 0:
            raise ValueError("job_lease_invalid")
        at = job_time(now)
        with self._transaction() as conn:
            conn.execute(
                "UPDATE job_runs SET status='failed', error='lease_expired_attempts_exhausted', "
                "lease_owner=NULL, lease_expires_at=NULL, updated_at=? "
                "WHERE kind=? AND status='running' AND lease_expires_at<=? AND attempt>=max_attempts",
                (at, kind, at),
            )
            row = conn.execute(
                "SELECT * FROM job_runs WHERE kind=? AND attempt<max_attempts AND "
                "((status='queued' AND available_at<=?) OR (status='running' AND lease_expires_at<=?)) "
                "ORDER BY created_at, job_id LIMIT 1",
                (kind, at, at),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE job_runs SET status='running', attempt=attempt+1, lease_owner=?, "
                "lease_expires_at=?, heartbeat_at=?, updated_at=? WHERE job_id=?",
                (
                    owner,
                    job_time(now + timedelta(seconds=lease_seconds)),
                    at,
                    at,
                    row["job_id"],
                ),
            )
            return _job(
                conn.execute(
                    "SELECT * FROM job_runs WHERE job_id=?", (row["job_id"],)
                ).fetchone()
            )

    def heartbeat(self, lease, *, now, lease_seconds=60):
        if lease_seconds <= 0:
            raise ValueError("job_lease_invalid")
        with self._transaction() as conn:
            require_job_lease(conn, lease, now=now)
            conn.execute(
                "UPDATE job_runs SET lease_expires_at=?, heartbeat_at=?, updated_at=? WHERE job_id=?",
                (
                    job_time(now + timedelta(seconds=lease_seconds)),
                    job_time(now),
                    job_time(now),
                    lease.job_id,
                ),
            )

    def finish(self, lease, *, now, result_ref):
        if not result_ref.strip():
            raise ValueError("job_result_ref_required")
        with self._transaction() as conn:
            require_job_lease(conn, lease, now=now)
            conn.execute(
                "UPDATE job_runs SET status='succeeded', result_ref=?, error=NULL, "
                "lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                (result_ref, job_time(now), lease.job_id),
            )

    def fail(self, lease, *, now, error, retry_seconds=60):
        if retry_seconds < 0 or not error:
            raise ValueError("job_retry_invalid")
        with self._transaction() as conn:
            require_job_lease(conn, lease, now=now)
            conn.execute(
                "UPDATE job_runs SET status=CASE WHEN attempt>=max_attempts THEN 'failed' ELSE 'queued' END, "
                "error=?, available_at=?, lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                (
                    error,
                    job_time(now + timedelta(seconds=retry_seconds)),
                    job_time(now),
                    lease.job_id,
                ),
            )


def _job(row):
    return JobRun(
        **{key: row[key] for key in JobRun.__dataclass_fields__ if key != "payload"},
        payload=json.loads(row["payload_json"]),
    )
