"""Durable, lease-backed jobs for the isolated shadow-research worker.

The queue deliberately reuses ``automation_runs``.  Worker lifecycle state is
operational metadata, not a new financial fact, so it does not require a new
schema or migration.  All claim/renew/finish transitions are short SQLite
transactions and only the current opaque lease owner may publish a result.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from server.ai_runtime.contracts import content_fingerprint
from server.persistence.ai_shadow_research_uow import ShadowResearchUnitOfWork
from server.persistence.research_worker_job_values import (
    AiShadowResearchWorkerJobRejected,
)
from server.persistence.research_worker_job_values import aware_utc as _aware_utc
from server.persistence.research_worker_job_values import canonical_job_json as _json
from server.persistence.research_worker_job_values import (
    lease_matches as _lease_matches,
)
from server.persistence.research_worker_job_values import parse_utc as _parse_utc
from server.persistence.research_worker_job_values import (
    required_text as _required_text,
)
from server.persistence.research_worker_job_values import safe_result as _safe_result

AI_SHADOW_RESEARCH_WORKER_JOB_SCHEMA = "karkinos.ai.shadow_research_worker_job.v1"
AI_SHADOW_RESEARCH_WORKER_JOB_RUN_TYPE = "ai_shadow_research_provider_job"
AI_SHADOW_RESEARCH_WORKER_EXECUTION_MODE = "research_only"

_TERMINAL_STATUSES = frozenset({"completed", "failed", "expired"})


def build_ai_shadow_research_worker_job_id(
    *,
    policy_fingerprint: str,
    provider_config_fingerprint: str,
    provider_window_policy_fingerprint: str,
    deadline_at: datetime,
) -> str:
    """Return one stable job identity for one authorized off-peak segment."""

    deadline = _aware_utc(deadline_at, field="deadline_at")
    fingerprint = content_fingerprint(
        {
            "schema_version": AI_SHADOW_RESEARCH_WORKER_JOB_SCHEMA,
            "policy_fingerprint": _required_text(
                policy_fingerprint, "policy_fingerprint"
            ),
            "provider_config_fingerprint": _required_text(
                provider_config_fingerprint, "provider_config_fingerprint"
            ),
            "provider_window_policy_fingerprint": _required_text(
                provider_window_policy_fingerprint,
                "provider_window_policy_fingerprint",
            ),
            "deadline_at": deadline.isoformat(),
        }
    )
    return f"automation:ai-shadow-research-provider-job:{fingerprint}"


class AiShadowResearchWorkerJobStore:
    """Own atomic enqueue, lease, heartbeat, and terminal queue transitions."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._uow = ShadowResearchUnitOfWork(self._path)

    def enqueue(
        self,
        *,
        policy_fingerprint: str,
        provider_config_fingerprint: str,
        provider_window_policy_fingerprint: str,
        available_at: datetime,
        deadline_at: datetime,
        enqueued_at: datetime,
    ) -> dict[str, Any]:
        available = _aware_utc(available_at, field="available_at")
        deadline = _aware_utc(deadline_at, field="deadline_at")
        enqueued = _aware_utc(enqueued_at, field="enqueued_at")
        if available >= deadline:
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_job_window_invalid"
            )
        job_id = build_ai_shadow_research_worker_job_id(
            policy_fingerprint=policy_fingerprint,
            provider_config_fingerprint=provider_config_fingerprint,
            provider_window_policy_fingerprint=(provider_window_policy_fingerprint),
            deadline_at=deadline,
        )
        payload = {
            "schema_version": AI_SHADOW_RESEARCH_WORKER_JOB_SCHEMA,
            "job_id": job_id,
            "policy_fingerprint": _required_text(
                policy_fingerprint, "policy_fingerprint"
            ),
            "provider_config_fingerprint": _required_text(
                provider_config_fingerprint, "provider_config_fingerprint"
            ),
            "provider_window_policy_fingerprint": _required_text(
                provider_window_policy_fingerprint,
                "provider_window_policy_fingerprint",
            ),
            "available_at": available.isoformat(),
            "deadline_at": deadline.isoformat(),
            "enqueued_at": enqueued.isoformat(),
            "attempt_count": 0,
            "lease_generation": 0,
            "takeover_count": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "provider_in_flight": None,
            "last_result": None,
            "provider_research_only": True,
            "automatic_strategy_replacement_enabled": False,
            "broker_submission_enabled": False,
            "production_strategy_mutation_enabled": False,
            "execution_authority_granted": False,
            "capital_authority_granted": False,
        }
        _validate_job_payload(payload, expected_job_id=job_id)
        payload_json = _json(payload)
        now_text = enqueued.isoformat()
        run_date = deadline.date().isoformat()
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO automation_runs (
                    run_id, run_type, run_date, status, execution_mode,
                    started_at, finished_at, source_ref, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    AI_SHADOW_RESEARCH_WORKER_JOB_RUN_TYPE,
                    run_date,
                    AI_SHADOW_RESEARCH_WORKER_EXECUTION_MODE,
                    now_text,
                    "automation-policy:ai_shadow_research",
                    payload_json,
                    now_text,
                    now_text,
                ),
            )
            row = self._load_row(conn, job_id)
            self._validate_row_identity(
                row,
                expected_job_id=job_id,
                expected_run_date=run_date,
                expected_payload=payload,
            )
        return {**row, "enqueued": cursor.rowcount == 1}

    def claim_next(
        self,
        *,
        lease_owner: str,
        claimed_at: datetime,
        lease_seconds: int = 90,
    ) -> dict[str, Any] | None:
        owner = _required_text(lease_owner, "lease_owner")
        claimed = _aware_utc(claimed_at, field="claimed_at")
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_lease_seconds_invalid"
            )
        with self._connect(immediate=True) as conn:
            rows = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE run_type=? AND status IN ('pending', 'leased')
                ORDER BY created_at ASC, run_id ASC
                """,
                (AI_SHADOW_RESEARCH_WORKER_JOB_RUN_TYPE,),
            ).fetchall()
            for raw_row in rows:
                row = _project_row(dict(raw_row))
                payload = row["payload"]
                _validate_job_payload(payload, expected_job_id=str(row["run_id"]))
                deadline = _parse_utc(payload["deadline_at"], "deadline_at")
                if claimed >= deadline:
                    self._expire_row(
                        conn,
                        row=row,
                        expired_at=claimed,
                        failure_code="research_worker_job_deadline_elapsed",
                    )
                    continue
                status = str(row["status"])
                stale_takeover = False
                if status == "pending":
                    available = _parse_utc(payload["available_at"], "available_at")
                    if claimed < available:
                        continue
                elif status == "leased":
                    expires_at = _parse_utc(
                        payload.get("lease_expires_at"), "lease_expires_at"
                    )
                    if claimed < expires_at:
                        continue
                    provider_in_flight = payload.get("provider_in_flight")
                    if isinstance(provider_in_flight, Mapping):
                        in_flight_until = _parse_utc(
                            provider_in_flight.get("fenced_until"),
                            "provider_in_flight.fenced_until",
                        )
                        if claimed < in_flight_until:
                            continue
                    stale_takeover = True
                else:  # pragma: no cover - query constrains this branch
                    continue

                lease_expires = min(
                    claimed + timedelta(seconds=lease_seconds), deadline
                )
                if lease_expires <= claimed:
                    continue
                updated_payload = {
                    **payload,
                    "attempt_count": int(payload.get("attempt_count") or 0) + 1,
                    "lease_generation": int(payload.get("lease_generation") or 0) + 1,
                    "takeover_count": int(payload.get("takeover_count") or 0)
                    + (1 if stale_takeover else 0),
                    "lease_owner": owner,
                    "lease_expires_at": lease_expires.isoformat(),
                    "provider_in_flight": None,
                    "last_claimed_at": claimed.isoformat(),
                }
                cursor = conn.execute(
                    """
                    UPDATE automation_runs
                    SET status='leased', payload_json=?, updated_at=?
                    WHERE run_id=? AND status=? AND updated_at=?
                    """,
                    (
                        _json(updated_payload),
                        claimed.isoformat(),
                        row["run_id"],
                        status,
                        row["updated_at"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise AiShadowResearchWorkerJobRejected(
                        "research_worker_job_claim_conflict"
                    )
                return self._load_row(conn, str(row["run_id"]))
        return None

    def renew_lease(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        renewed_at: datetime,
        lease_seconds: int = 90,
    ) -> bool:
        owner = _required_text(lease_owner, "lease_owner")
        renewed = _aware_utc(renewed_at, field="renewed_at")
        if isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_lease_seconds_invalid"
            )
        with self._connect(immediate=True) as conn:
            row = self._load_optional_row(conn, job_id)
            if row is None or row["status"] != "leased":
                return False
            payload = row["payload"]
            _validate_job_payload(payload, expected_job_id=job_id)
            if not _lease_matches(
                payload, lease_owner=owner, lease_generation=lease_generation
            ):
                return False
            current_expiry = _parse_utc(
                payload.get("lease_expires_at"), "lease_expires_at"
            )
            deadline = _parse_utc(payload["deadline_at"], "deadline_at")
            if renewed >= current_expiry or renewed >= deadline:
                return False
            lease_expires = min(renewed + timedelta(seconds=lease_seconds), deadline)
            updated_payload = {
                **payload,
                "lease_expires_at": lease_expires.isoformat(),
                "last_heartbeat_at": renewed.isoformat(),
            }
            cursor = conn.execute(
                """
                UPDATE automation_runs SET payload_json=?, updated_at=?
                WHERE run_id=? AND status='leased' AND updated_at=?
                """,
                (
                    _json(updated_payload),
                    renewed.isoformat(),
                    job_id,
                    row["updated_at"],
                ),
            )
            return cursor.rowcount == 1

    def complete(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        completed_at: datetime,
        result: Mapping[str, Any],
    ) -> bool:
        return self._finish(
            job_id=job_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            finished_at=completed_at,
            status="completed",
            result=result,
        )

    def fail(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        failed_at: datetime,
        result: Mapping[str, Any],
    ) -> bool:
        return self._finish(
            job_id=job_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            finished_at=failed_at,
            status="failed",
            result=result,
        )

    def reschedule(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        rescheduled_at: datetime,
        available_at: datetime,
        result: Mapping[str, Any],
    ) -> bool:
        owner = _required_text(lease_owner, "lease_owner")
        rescheduled = _aware_utc(rescheduled_at, field="rescheduled_at")
        available = _aware_utc(available_at, field="available_at")
        with self._connect(immediate=True) as conn:
            row = self._load_optional_row(conn, job_id)
            if row is None or row["status"] != "leased":
                return False
            payload = row["payload"]
            _validate_job_payload(payload, expected_job_id=job_id)
            if not _lease_matches(
                payload, lease_owner=owner, lease_generation=lease_generation
            ):
                return False
            if payload.get("provider_in_flight") is not None:
                return False
            deadline = _parse_utc(payload["deadline_at"], "deadline_at")
            lease_expires = _parse_utc(
                payload.get("lease_expires_at"), "lease_expires_at"
            )
            if rescheduled >= lease_expires or rescheduled >= deadline:
                return False
            status = "pending" if available < deadline else "expired"
            updated_payload = {
                **payload,
                "available_at": min(available, deadline).isoformat(),
                "lease_owner": None,
                "lease_expires_at": None,
                "provider_in_flight": None,
                "last_result": _safe_result(result),
            }
            cursor = conn.execute(
                """
                UPDATE automation_runs
                SET status=?, finished_at=?, payload_json=?, updated_at=?
                WHERE run_id=? AND status='leased' AND updated_at=?
                """,
                (
                    status,
                    rescheduled.isoformat() if status == "expired" else None,
                    _json(updated_payload),
                    rescheduled.isoformat(),
                    job_id,
                    row["updated_at"],
                ),
            )
            return cursor.rowcount == 1

    def lease_is_current(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        checked_at: datetime,
    ) -> bool:
        """Return whether one exact lease generation may still act."""

        owner = _required_text(lease_owner, "lease_owner")
        checked = _aware_utc(checked_at, field="checked_at")
        with self._connect() as conn:
            row = self._load_optional_row(conn, job_id)
        if row is None or row["status"] != "leased":
            return False
        payload = row["payload"]
        _validate_job_payload(payload, expected_job_id=job_id)
        if not _lease_matches(
            payload, lease_owner=owner, lease_generation=lease_generation
        ):
            return False
        return checked < min(
            _parse_utc(payload.get("lease_expires_at"), "lease_expires_at"),
            _parse_utc(payload["deadline_at"], "deadline_at"),
        )

    def begin_provider_send(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        started_at: datetime,
        timeout_seconds: float,
    ) -> str | None:
        """Fence one blocking provider send and expose it to takeover logic."""

        owner = _required_text(lease_owner, "lease_owner")
        started = _aware_utc(started_at, field="started_at")
        if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_provider_timeout_invalid"
            )
        with self._connect(immediate=True) as conn:
            row = self._load_optional_row(conn, job_id)
            if row is None or row["status"] != "leased":
                return None
            payload = row["payload"]
            _validate_job_payload(payload, expected_job_id=job_id)
            if not _lease_matches(
                payload, lease_owner=owner, lease_generation=lease_generation
            ):
                return None
            lease_expires = _parse_utc(
                payload.get("lease_expires_at"), "lease_expires_at"
            )
            deadline = _parse_utc(payload["deadline_at"], "deadline_at")
            if started >= lease_expires or started >= deadline:
                return None
            if payload.get("provider_in_flight") is not None:
                return None
            sequence = int(payload.get("provider_send_sequence") or 0) + 1
            token = f"{lease_generation}:{sequence}"
            fenced_until = min(
                started + timedelta(seconds=float(timeout_seconds)), deadline
            )
            updated_payload = {
                **payload,
                "provider_send_sequence": sequence,
                "provider_in_flight": {
                    "token": token,
                    "lease_owner": owner,
                    "lease_generation": lease_generation,
                    "started_at": started.isoformat(),
                    "fenced_until": fenced_until.isoformat(),
                },
            }
            cursor = conn.execute(
                """
                UPDATE automation_runs SET payload_json=?, updated_at=?
                WHERE run_id=? AND status='leased' AND updated_at=?
                """,
                (
                    _json(updated_payload),
                    started.isoformat(),
                    job_id,
                    row["updated_at"],
                ),
            )
            return token if cursor.rowcount == 1 else None

    def finish_provider_send(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        token: str,
        finished_at: datetime,
    ) -> bool:
        """Clear in-flight state only for the still-current exact generation."""

        owner = _required_text(lease_owner, "lease_owner")
        finished = _aware_utc(finished_at, field="finished_at")
        with self._connect(immediate=True) as conn:
            row = self._load_optional_row(conn, job_id)
            if row is None or row["status"] != "leased":
                return False
            payload = row["payload"]
            _validate_job_payload(payload, expected_job_id=job_id)
            if not _lease_matches(
                payload, lease_owner=owner, lease_generation=lease_generation
            ):
                return False
            provider_in_flight = payload.get("provider_in_flight")
            if (
                not isinstance(provider_in_flight, Mapping)
                or provider_in_flight.get("token") != token
            ):
                return False
            lease_expires = _parse_utc(
                payload.get("lease_expires_at"), "lease_expires_at"
            )
            deadline = _parse_utc(payload["deadline_at"], "deadline_at")
            if finished >= lease_expires or finished >= deadline:
                return False
            updated_payload = {**payload, "provider_in_flight": None}
            cursor = conn.execute(
                """
                UPDATE automation_runs SET payload_json=?, updated_at=?
                WHERE run_id=? AND status='leased' AND updated_at=?
                """,
                (
                    _json(updated_payload),
                    finished.isoformat(),
                    job_id,
                    row["updated_at"],
                ),
            )
            return cursor.rowcount == 1

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._load_optional_row(conn, job_id)

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM automation_runs WHERE run_type=?
                ORDER BY updated_at DESC, created_at DESC LIMIT ?
                """,
                (AI_SHADOW_RESEARCH_WORKER_JOB_RUN_TYPE, bounded_limit),
            ).fetchall()
            return [_project_row(dict(row)) for row in rows]

    def _finish(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_generation: int,
        finished_at: datetime,
        status: str,
        result: Mapping[str, Any],
    ) -> bool:
        if status not in _TERMINAL_STATUSES:
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_job_terminal_status_invalid"
            )
        owner = _required_text(lease_owner, "lease_owner")
        finished = _aware_utc(finished_at, field="finished_at")
        with self._connect(immediate=True) as conn:
            row = self._load_optional_row(conn, job_id)
            if row is None or row["status"] != "leased":
                return False
            payload = row["payload"]
            _validate_job_payload(payload, expected_job_id=job_id)
            if not _lease_matches(
                payload, lease_owner=owner, lease_generation=lease_generation
            ):
                return False
            if payload.get("provider_in_flight") is not None:
                return False
            lease_expires = _parse_utc(
                payload.get("lease_expires_at"), "lease_expires_at"
            )
            deadline = _parse_utc(payload["deadline_at"], "deadline_at")
            if finished >= lease_expires or finished >= deadline:
                return False
            updated_payload = {
                **payload,
                "lease_owner": None,
                "lease_expires_at": None,
                "provider_in_flight": None,
                "last_result": _safe_result(result),
            }
            cursor = conn.execute(
                """
                UPDATE automation_runs
                SET status=?, finished_at=?, payload_json=?, updated_at=?
                WHERE run_id=? AND status='leased' AND updated_at=?
                """,
                (
                    status,
                    finished.isoformat(),
                    _json(updated_payload),
                    finished.isoformat(),
                    job_id,
                    row["updated_at"],
                ),
            )
            return cursor.rowcount == 1

    def _expire_row(
        self,
        conn: Any,
        *,
        row: Mapping[str, Any],
        expired_at: datetime,
        failure_code: str,
    ) -> None:
        payload = dict(row["payload"])
        payload.update(
            {
                "lease_owner": None,
                "lease_expires_at": None,
                "provider_in_flight": None,
                "last_result": _safe_result(
                    {
                        "run_status": "expired",
                        "failure_code": failure_code,
                    }
                ),
            }
        )
        conn.execute(
            """
            UPDATE automation_runs
            SET status='expired', finished_at=?, payload_json=?, updated_at=?
            WHERE run_id=? AND status=? AND updated_at=?
            """,
            (
                expired_at.isoformat(),
                _json(payload),
                expired_at.isoformat(),
                row["run_id"],
                row["status"],
                row["updated_at"],
            ),
        )

    def _validate_row_identity(
        self,
        row: Mapping[str, Any],
        *,
        expected_job_id: str,
        expected_run_date: str,
        expected_payload: Mapping[str, Any],
    ) -> None:
        if (
            row.get("run_type") != AI_SHADOW_RESEARCH_WORKER_JOB_RUN_TYPE
            or row.get("execution_mode") != AI_SHADOW_RESEARCH_WORKER_EXECUTION_MODE
            or row.get("run_date") != expected_run_date
        ):
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_job_identity_conflict"
            )
        payload = row["payload"]
        _validate_job_payload(payload, expected_job_id=expected_job_id)
        for field in (
            "policy_fingerprint",
            "provider_config_fingerprint",
            "provider_window_policy_fingerprint",
            "deadline_at",
        ):
            if payload.get(field) != expected_payload.get(field):
                raise AiShadowResearchWorkerJobRejected(
                    "research_worker_job_identity_conflict"
                )

    def _load_row(self, conn: Any, job_id: str) -> dict[str, Any]:
        row = self._load_optional_row(conn, job_id)
        if row is None:
            raise RuntimeError("research worker job was not persisted")
        return row

    @staticmethod
    def _load_optional_row(conn: Any, job_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM automation_runs WHERE run_id=? LIMIT 1", (job_id,)
        ).fetchone()
        return _project_row(dict(row)) if row is not None else None

    def _connect(self, *, immediate: bool = False):
        return self._uow.write() if immediate else self._uow.connect()


def _project_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError as exc:
        raise AiShadowResearchWorkerJobRejected(
            "research_worker_job_payload_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise AiShadowResearchWorkerJobRejected("research_worker_job_payload_invalid")
    return {**row, "payload": payload}


def _validate_job_payload(payload: Mapping[str, Any], *, expected_job_id: str) -> None:
    if (
        payload.get("schema_version") != AI_SHADOW_RESEARCH_WORKER_JOB_SCHEMA
        or payload.get("job_id") != expected_job_id
        or payload.get("provider_research_only") is not True
        or payload.get("automatic_strategy_replacement_enabled") is not False
        or payload.get("broker_submission_enabled") is not False
        or payload.get("production_strategy_mutation_enabled") is not False
        or payload.get("execution_authority_granted") is not False
        or payload.get("capital_authority_granted") is not False
    ):
        raise AiShadowResearchWorkerJobRejected(
            "research_worker_job_safety_contract_invalid"
        )
    for field in (
        "policy_fingerprint",
        "provider_config_fingerprint",
        "provider_window_policy_fingerprint",
    ):
        _required_text(payload.get(field), field)
    available = _parse_utc(payload.get("available_at"), "available_at")
    deadline = _parse_utc(payload.get("deadline_at"), "deadline_at")
    if available > deadline:
        raise AiShadowResearchWorkerJobRejected("research_worker_job_window_invalid")
    generation = payload.get("lease_generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        raise AiShadowResearchWorkerJobRejected(
            "research_worker_job_lease_generation_invalid"
        )
    provider_in_flight = payload.get("provider_in_flight")
    if provider_in_flight is not None:
        if not isinstance(provider_in_flight, Mapping):
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_job_provider_in_flight_invalid"
            )
        _required_text(provider_in_flight.get("token"), "provider_in_flight_token")
        _required_text(
            provider_in_flight.get("lease_owner"),
            "provider_in_flight_lease_owner",
        )
        if provider_in_flight.get("lease_generation") != generation:
            raise AiShadowResearchWorkerJobRejected(
                "research_worker_job_provider_in_flight_generation_invalid"
            )
        _parse_utc(
            provider_in_flight.get("started_at"), "provider_in_flight.started_at"
        )
        _parse_utc(
            provider_in_flight.get("fenced_until"),
            "provider_in_flight.fenced_until",
        )
