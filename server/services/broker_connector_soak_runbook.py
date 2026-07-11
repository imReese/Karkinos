"""Operational run and recovery-drill evidence for read-only broker soak."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from server.services.broker_connector_soak import BrokerConnectorSoakService

BROKER_CONNECTOR_SOAK_RUN_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_operational_run.v1"
)
BROKER_CONNECTOR_SOAK_DRILL_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_recovery_drill.v1"
)
BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE = "broker_connector.soak_run_recorded"
BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE = "broker_connector_soak_operational_run"
BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE = "broker_connector.soak_drill_recorded"
BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE = "broker_connector_soak_recovery_drill"
BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE = "broker_connector_soak_runbook"

BROKER_CONNECTOR_SOAK_PHASES = frozenset({"startup", "intraday", "end_of_day"})
BROKER_CONNECTOR_SOAK_DRILL_TYPES = frozenset(
    {
        "disconnect",
        "schema_drift",
        "stale_data",
        "duplicate_evidence",
        "restart_recovery",
    }
)


class BrokerConnectorSoakRunbookService:
    """Persist fail-closed, broker-read-only operating and drill evidence."""

    def __init__(
        self,
        *,
        db: Any,
        connectors: list[Any] | tuple[Any, ...],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._connectors = list(connectors or [])
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_phase(
        self,
        *,
        phase: str,
        max_snapshot_age_seconds: int = 900,
    ) -> dict[str, Any]:
        effective_phase = _choice(phase, BROKER_CONNECTOR_SOAK_PHASES, "phase")
        observed_at = _aware_utc(self._clock())
        capture = self._soak_service().capture(
            max_snapshot_age_seconds=max_snapshot_age_seconds
        )
        observations = list(capture.get("observations") or [])
        blockers = _phase_blockers(effective_phase, observations)
        evidence = [_observation_reference(item) for item in observations]
        input_fingerprint = _fingerprint(
            {
                "phase": effective_phase,
                "max_snapshot_age_seconds": int(max_snapshot_age_seconds),
                "observations": [_observation_identity(item) for item in evidence],
            }
        )
        run_id = _fingerprint(
            {
                "schema_version": BROKER_CONNECTOR_SOAK_RUN_SCHEMA_VERSION,
                "input_fingerprint": input_fingerprint,
                "run_status": "passed" if not blockers else "blocked",
            }
        )
        payload = {
            "schema_version": BROKER_CONNECTOR_SOAK_RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "input_fingerprint": input_fingerprint,
            "phase": effective_phase,
            "observed_at": observed_at.isoformat(),
            "run_status": "passed" if not blockers else "blocked",
            "blockers": blockers,
            "observation_count": len(observations),
            "observations": evidence,
            "requires_clear_execution_reconciliation": (
                effective_phase == "end_of_day"
            ),
            **_safety_flags(),
        }
        result = self._persist_evidence(
            event_type=BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
            entity_id=run_id,
            timestamp=observed_at.isoformat(),
            source_ref=effective_phase,
            payload=payload,
        )
        self._record_alert(
            evidence_kind="run",
            evidence_name=effective_phase,
            result=result,
        )
        return result

    def run_drill(
        self,
        *,
        drill_type: str,
        max_snapshot_age_seconds: int = 900,
    ) -> dict[str, Any]:
        effective_drill = _choice(
            drill_type,
            BROKER_CONNECTOR_SOAK_DRILL_TYPES,
            "drill_type",
        )
        observed_at = _aware_utc(self._clock())
        first = self._soak_service().capture(
            max_snapshot_age_seconds=max_snapshot_age_seconds
        )
        second: dict[str, Any] | None = None
        if effective_drill == "duplicate_evidence":
            second = self._soak_service().capture(
                max_snapshot_age_seconds=max_snapshot_age_seconds
            )
        elif effective_drill == "restart_recovery":
            # A new service instance intentionally has no in-memory state. Reusing
            # persisted evidence proves restart-safe sequential replay behavior.
            second = BrokerConnectorSoakService(
                db=self._db,
                connectors=self._connectors,
                clock=self._clock,
            ).capture(max_snapshot_age_seconds=max_snapshot_age_seconds)

        first_observations = list(first.get("observations") or [])
        second_observations = list((second or {}).get("observations") or [])
        blockers = _drill_blockers(
            effective_drill,
            first_observations=first_observations,
            second_observations=second_observations,
        )
        first_evidence = [_observation_reference(item) for item in first_observations]
        second_evidence = [_observation_reference(item) for item in second_observations]
        input_fingerprint = _fingerprint(
            {
                "drill_type": effective_drill,
                "max_snapshot_age_seconds": int(max_snapshot_age_seconds),
                "first_observations": [
                    _observation_identity(item) for item in first_evidence
                ],
                "second_observations": [
                    _observation_identity(item) for item in second_evidence
                ],
            }
        )
        drill_id = _fingerprint(
            {
                "schema_version": BROKER_CONNECTOR_SOAK_DRILL_SCHEMA_VERSION,
                "input_fingerprint": input_fingerprint,
                "drill_status": "passed" if not blockers else "failed",
            }
        )
        payload = {
            "schema_version": BROKER_CONNECTOR_SOAK_DRILL_SCHEMA_VERSION,
            "drill_id": drill_id,
            "input_fingerprint": input_fingerprint,
            "drill_type": effective_drill,
            "observed_at": observed_at.isoformat(),
            "drill_status": "passed" if not blockers else "failed",
            "blockers": blockers,
            "expected_safe_state": _expected_safe_state(effective_drill),
            "first_observations": first_evidence,
            "second_observations": second_evidence,
            "requires_manual_review": True,
            **_safety_flags(),
        }
        result = self._persist_evidence(
            event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
            entity_id=drill_id,
            timestamp=observed_at.isoformat(),
            source_ref=effective_drill,
            payload=payload,
        )
        self._record_alert(
            evidence_kind="drill",
            evidence_name=effective_drill,
            result=result,
        )
        return result

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_evidence(
            event_type=BROKER_CONNECTOR_SOAK_RUN_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_RUN_ENTITY_TYPE,
            limit=limit,
        )

    def list_drills(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._list_evidence(
            event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_DRILL_ENTITY_TYPE,
            limit=limit,
        )

    def _soak_service(self) -> BrokerConnectorSoakService:
        return BrokerConnectorSoakService(
            db=self._db,
            connectors=self._connectors,
            clock=self._clock,
        )

    def _persist_evidence(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        timestamp: str,
        source_ref: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self._db.list_events_sync(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        self._db.append_event_sync(
            event_type=event_type,
            timestamp=timestamp,
            entity_type=entity_type,
            entity_id=entity_id,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            source_ref=source_ref,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError(
                "broker connector soak runbook evidence was not recorded"
            )
        return _event_response(saved[0], reused=False)

    def _list_evidence(
        self,
        *,
        event_type: str,
        entity_type: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=event_type,
            entity_type=entity_type,
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def _record_alert(
        self,
        *,
        evidence_kind: str,
        evidence_name: str,
        result: dict[str, Any],
    ) -> None:
        status = str(result.get(f"{evidence_kind}_status") or "failed")
        passed = status == "passed"
        if passed or not hasattr(self._db, "upsert_automation_alert_sync"):
            return
        blockers = [str(item) for item in result.get("blockers") or []]
        evidence_id = str(
            result.get(f"{evidence_kind}_id") or result.get("input_fingerprint") or ""
        )
        self._db.upsert_automation_alert_sync(
            alert_key=(
                f"broker_connector_soak_runbook:{evidence_kind}:"
                f"{evidence_name}:{evidence_id}"
            ),
            severity="critical" if status == "blocked" else "warning",
            category="broker_connector_soak_runbook",
            title=f"Read-only broker soak {evidence_kind} is {status}",
            detail=(
                ", ".join(blockers)
                or "Read-only broker soak runbook evidence requires review."
            ),
            source=BROKER_CONNECTOR_SOAK_RUNBOOK_EVENT_SOURCE,
            source_ref=evidence_id,
            payload={
                "schema_version": result.get("schema_version"),
                "evidence_kind": evidence_kind,
                "evidence_name": evidence_name,
                "status": status,
                "blockers": blockers,
                "requires_manual_review": True,
                **_safety_flags(),
            },
        )


def _phase_blockers(
    phase: str,
    observations: list[dict[str, Any]],
) -> list[str]:
    if not observations:
        return ["no_configured_readonly_connector"]
    blockers: list[str] = []
    for observation in observations:
        connector_id = str(observation.get("connector_id") or "unknown")
        if str(observation.get("soak_status") or "blocked") != "healthy":
            blockers.append(f"snapshot_not_healthy:{connector_id}")
        if phase != "end_of_day":
            continue
        reconciliation = observation.get("execution_reconciliation") or {}
        if (
            str(reconciliation.get("status") or "not_available") != "clear"
            or int(reconciliation.get("open_item_count") or 0) != 0
        ):
            blockers.append(f"execution_reconciliation_not_clear:{connector_id}")
    return list(dict.fromkeys(blockers))


def _drill_blockers(
    drill_type: str,
    *,
    first_observations: list[dict[str, Any]],
    second_observations: list[dict[str, Any]],
) -> list[str]:
    if not first_observations:
        return ["no_configured_readonly_connector"]
    blockers: list[str] = []
    if drill_type in {"disconnect", "schema_drift", "stale_data"}:
        expected = {
            "disconnect": "connector_read_failed:",
            "schema_drift": (
                "connector_read_failed:UnsupportedLocalJsonSnapshotSchema"
            ),
            "stale_data": "snapshot_stale",
        }[drill_type]
        for observation in first_observations:
            connector_id = str(observation.get("connector_id") or "unknown")
            reasons = [str(item) for item in observation.get("blockers") or []]
            matched = (
                any(reason.startswith(expected) for reason in reasons)
                if expected.endswith(":")
                else expected in reasons
            )
            if not matched:
                blockers.append(
                    f"expected_safe_degradation_not_observed:{connector_id}"
                )
        return blockers

    first_by_connector = {
        str(item.get("connector_id") or "unknown"): item for item in first_observations
    }
    second_by_connector = {
        str(item.get("connector_id") or "unknown"): item for item in second_observations
    }
    if first_by_connector.keys() != second_by_connector.keys():
        blockers.append("connector_set_changed_during_replay")
    for connector_id, first in first_by_connector.items():
        second = second_by_connector.get(connector_id)
        if second is None:
            blockers.append(f"replay_observation_missing:{connector_id}")
            continue
        if first.get("event_id") != second.get("event_id"):
            blockers.append(f"replay_created_duplicate_evidence:{connector_id}")
        if not bool(second.get("reused")):
            blockers.append(f"replay_was_not_reused:{connector_id}")
    return list(dict.fromkeys(blockers))


def _expected_safe_state(drill_type: str) -> str:
    return {
        "disconnect": "blocked_connector_read_failure_without_broker_write",
        "schema_drift": "blocked_unsupported_snapshot_schema_without_broker_write",
        "stale_data": "degraded_snapshot_stale_without_broker_write",
        "duplicate_evidence": "same_observation_event_reused",
        "restart_recovery": "persisted_observation_reused_by_new_service_instance",
    }[drill_type]


def _observation_reference(observation: dict[str, Any]) -> dict[str, Any]:
    reconciliation = observation.get("execution_reconciliation") or {}
    return {
        "connector_id": str(observation.get("connector_id") or ""),
        "event_id": observation.get("event_id"),
        "observation_id": str(observation.get("observation_id") or ""),
        "snapshot_fingerprint": str(observation.get("snapshot_fingerprint") or ""),
        "trading_day": str(observation.get("trading_day") or ""),
        "soak_status": str(observation.get("soak_status") or "blocked"),
        "blockers": [str(item) for item in observation.get("blockers") or []],
        "reused": bool(observation.get("reused")),
        "execution_reconciliation_status": str(
            reconciliation.get("status") or "not_available"
        ),
        "execution_reconciliation_open_item_count": int(
            reconciliation.get("open_item_count") or 0
        ),
    }


def _observation_identity(reference: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in reference.items() if key != "reused"}


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    payload = _json_object(row.get("payload_json"))
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **payload,
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "broker_submission_enabled": False,
        "does_not_contact_write_capabilities": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_grant_capital_authority": True,
    }


def _choice(value: str, allowed: frozenset[str], name: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"unsupported {name}: {value}")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
