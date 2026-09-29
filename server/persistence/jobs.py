"""Transactional job queue with compare-and-set leases and fenced completion."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from server.contracts.jobs import JobLease, JobRun, job_time
from server.persistence.connection import connect_sqlite


class JobIdentityConflictError(ValueError):
    """Persisted job identity or payload no longer matches its durable key."""


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
        conn = connect_sqlite(self.path, timeout=2)
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

    def list_recent(self, kind: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("job_kind_invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("job_limit_invalid")
        try:
            with closing(connect_sqlite(self.path, readonly=True)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT job_id, kind, payload_json, status, attempt, result_ref, "
                    "error, failure_evidence_ref, created_at, updated_at "
                    "FROM job_runs WHERE kind=? "
                    "ORDER BY updated_at DESC, job_id DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise OSError("job_store_read_unavailable") from exc
        return [dict(row) for row in rows]

    def get(self, job_id: str) -> JobRun | None:
        """Read one exact durable job without changing its lease or status."""
        if (
            not isinstance(job_id, str)
            or len(job_id) != 64
            or any(character not in "0123456789abcdef" for character in job_id)
        ):
            raise ValueError("job_id_invalid")
        try:
            with closing(connect_sqlite(self.path, readonly=True)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM job_runs WHERE job_id=?", (job_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise OSError("job_store_read_unavailable") from exc
        if row is None:
            return None
        encoded = row["payload_json"]
        if not isinstance(encoded, str):
            raise JobIdentityConflictError("job_identity_conflict")
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        expected_id = hashlib.sha256(
            f"{row['kind']}:{fingerprint}".encode()
        ).hexdigest()
        if row["input_fingerprint"] != fingerprint or row["job_id"] != expected_id:
            raise JobIdentityConflictError("job_identity_conflict")
        try:
            return _job(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise JobIdentityConflictError("job_identity_conflict") from exc

    def enqueue(self, kind, payload, *, now):
        return self.enqueue_many(kind, (payload,), now=now)[0]

    def enqueue_many(
        self,
        kind: str,
        payloads: Iterable[dict[str, Any]],
        *,
        now: datetime,
    ) -> tuple[JobRun, ...]:
        """Enqueue an entire explicit batch in one transaction or none of it."""
        prepared = tuple(_job_identity(kind, payload) for payload in payloads)
        if not prepared:
            return ()
        at = job_time(now)
        with self._transaction() as conn:
            jobs: list[JobRun] = []
            for job_id, fingerprint, encoded in prepared:
                conn.execute(
                    "INSERT INTO job_runs(job_id,kind,input_fingerprint,payload_json,status,available_at,created_at,updated_at) "
                    "VALUES (?,?,?,?,'queued',?,?,?) ON CONFLICT(job_id) DO NOTHING",
                    (job_id, kind, fingerprint, encoded, at, at, at),
                )
                row = conn.execute(
                    "SELECT * FROM job_runs WHERE job_id=?", (job_id,)
                ).fetchone()
                if (
                    row is None
                    or row["payload_json"] != encoded
                    or row["kind"] != kind
                    or row["input_fingerprint"] != fingerprint
                ):
                    raise JobIdentityConflictError("job_identity_conflict")
                jobs.append(_job(row))
            return tuple(jobs)

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
                "failure_evidence_ref=NULL, "
                "lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                (result_ref, job_time(now), lease.job_id),
            )

    def fail(
        self,
        lease,
        *,
        now,
        error,
        retry_seconds=60,
        failure_evidence_ref=None,
    ):
        if retry_seconds < 0 or not error:
            raise ValueError("job_retry_invalid")
        if failure_evidence_ref is not None and (
            not isinstance(failure_evidence_ref, str)
            or not failure_evidence_ref.strip()
        ):
            raise ValueError("job_failure_evidence_ref_invalid")
        with self._transaction() as conn:
            require_job_lease(conn, lease, now=now)
            conn.execute(
                "UPDATE job_runs SET status=CASE WHEN attempt>=max_attempts THEN 'failed' ELSE 'queued' END, "
                "error=?, failure_evidence_ref=COALESCE(?, failure_evidence_ref), "
                "available_at=?, lease_owner=NULL, lease_expires_at=NULL, updated_at=? WHERE job_id=?",
                (
                    error,
                    failure_evidence_ref,
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


def _job_identity(kind: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(kind, str) or not kind.strip() or not isinstance(payload, dict):
        raise ValueError("job_input_invalid")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    job_id = hashlib.sha256(f"{kind}:{fingerprint}".encode()).hexdigest()
    return job_id, fingerprint, encoded


def job_id_for(kind: str, payload: dict[str, Any]) -> str:
    """Derive an existing job's identity without inserting it."""
    return _job_identity(kind, payload)[0]
