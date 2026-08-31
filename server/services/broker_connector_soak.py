"""Read-only broker connector soak application service.

Evidence policy and persistence are owned by dedicated modules. This facade
retains the established import surface and never grants broker-write authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from server.persistence.broker_connector_soak import (
    BrokerConnectorSoakObservationRepository,
    advance_source_sequence_state,
)
from server.projections.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION,
    BROKER_CONNECTOR_SOAK_SOURCE_SEQUENCE_SCHEMA_VERSION,
    BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION,
    BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
    aware_utc,
    build_failed_observation_payload,
    build_observation_payload,
    connector_id,
    connector_summary,
    json_list,
    json_object,
    promotion_blockers,
    reviewed_broker_soak_sequence_is_accepted,
    trading_day,
)

# Compatibility injection seam used to prove event/checkpoint rollback.
_advance_source_sequence_state = advance_source_sequence_state


class BrokerConnectorSoakService:
    """Capture sanitized read-only snapshots without broker-write authority."""

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
        self._observations = BrokerConnectorSoakObservationRepository(db)

    def capture(
        self,
        *,
        max_snapshot_age_seconds: int = 900,
    ) -> dict[str, Any]:
        observed_at = aware_utc(self._clock())
        max_age = max(60, min(int(max_snapshot_age_seconds), 86400))
        observations = [
            self._capture_connector(
                connector,
                observed_at=observed_at,
                max_snapshot_age_seconds=max_age,
            )
            for connector in self._connectors
        ]
        return {
            "schema_version": "karkinos.broker_connector_soak_capture.v1",
            "observed_at": observed_at.isoformat(),
            "connector_count": len(self._connectors),
            "observation_count": len(observations),
            "observations": observations,
            "status": self.get_status(),
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "does_not_cancel_broker_order": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
        }

    def list_observations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._observations.list(limit=max(1, min(int(limit), 500)))
        return [self._event_response(row, reused=False) for row in rows]

    def get_status(self) -> dict[str, Any]:
        observations = self.list_observations(limit=500)
        connector_ids = sorted(
            {
                str(observation.get("connector_id") or "")
                for observation in observations
                if str(observation.get("connector_id") or "")
            }
        )
        configured_ids = sorted(
            {
                connector_id(connector)
                for connector in self._connectors
                if connector_id(connector)
            }
        )
        summaries = [
            connector_summary(
                configured_connector_id,
                observations=[
                    observation
                    for observation in observations
                    if observation.get("connector_id") == configured_connector_id
                ],
            )
            for configured_connector_id in sorted(
                set(connector_ids) | set(configured_ids)
            )
        ]
        return {
            "schema_version": BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION,
            "target_trading_days": BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
            "healthy_day_evidence_requirement": "accepted_v2_source_sequence",
            "configured_connector_count": len(self._connectors),
            "observed_connector_count": len(connector_ids),
            "observation_count": len(observations),
            "connectors": summaries,
            "operational_soak_complete": bool(summaries)
            and all(item["operational_soak_complete"] for item in summaries),
            "promotion_ready": False,
            "promotion_blockers": promotion_blockers(summaries),
            "broker_submission_enabled": False,
            "does_not_contact_write_capabilities": True,
            "does_not_submit_broker_order": True,
            "does_not_cancel_broker_order": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "owner_acceptance_recorded": False,
            "account_truth_reconciliation_linked": False,
        }

    def _capture_connector(
        self,
        connector: Any,
        *,
        observed_at: datetime,
        max_snapshot_age_seconds: int,
    ) -> dict[str, Any]:
        configured_connector_id = connector_id(connector)
        source_contract_required = bool(
            getattr(connector, "requires_source_contract", False)
        )
        try:
            capabilities = getattr(connector, "capabilities")
            snapshot = connector.read_account_snapshot()
            snapshot_trading_day = trading_day(snapshot.captured_at)
            payload = build_observation_payload(
                connector_id=configured_connector_id,
                capabilities=capabilities,
                snapshot=snapshot,
                source_contract_required=source_contract_required,
                observed_at=observed_at,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                market_calendar=_market_calendar_evidence(
                    self._db,
                    trading_day=snapshot_trading_day,
                ),
                execution_reconciliation=_latest_execution_reconciliation(
                    self._db,
                    trading_day=snapshot_trading_day,
                ),
            )
        except Exception as exc:  # connector errors must degrade, never execute
            payload = build_failed_observation_payload(
                connector_id=configured_connector_id,
                observed_at=observed_at,
                reason_code=type(exc).__name__,
            )

        row, reused = self._observations.record(
            payload=payload,
            observed_at=observed_at,
            source_contract_required=source_contract_required,
            advance_state=_advance_source_sequence_state,
        )
        response = self._event_response(row, reused=reused)
        self._record_soak_alert(response)
        return response

    @staticmethod
    def _event_response(
        row: dict[str, Any],
        *,
        reused: bool,
    ) -> dict[str, Any]:
        payload = json_object(row.get("payload_json"))
        return {
            "event_id": int(row["id"]),
            "recorded_at": row["timestamp"],
            "created_at": row["created_at"],
            "persisted": True,
            "reused": reused,
            **payload,
        }

    def _record_soak_alert(self, observation: dict[str, Any]) -> None:
        soak_status = str(observation.get("soak_status") or "blocked")
        if soak_status == "healthy" or not hasattr(
            self._db, "upsert_automation_alert_sync"
        ):
            return
        configured_connector_id = str(observation.get("connector_id") or "unknown")
        observation_trading_day = str(observation.get("trading_day") or "unknown")
        blockers = [str(item) for item in observation.get("blockers") or []]
        self._db.upsert_automation_alert_sync(
            alert_key=(
                "broker_connector_soak:"
                f"{configured_connector_id}:{observation_trading_day}:{soak_status}"
            ),
            severity="critical" if soak_status == "blocked" else "warning",
            category="broker_connector_soak",
            title=f"Read-only broker soak snapshot is {soak_status}",
            detail=(
                ", ".join(blockers)
                or "Read-only broker snapshot requires operator review."
            ),
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            source_ref=str(observation.get("observation_id") or ""),
            payload={
                "schema_version": BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION,
                "connector_id": configured_connector_id,
                "account_alias": observation.get("account_alias"),
                "trading_day": observation_trading_day,
                "soak_status": soak_status,
                "blockers": blockers,
                "snapshot_fingerprint": observation.get("snapshot_fingerprint"),
                "requires_manual_review": True,
                "broker_submission_enabled": False,
                "does_not_submit_broker_order": True,
                "does_not_cancel_broker_order": True,
                "does_not_mutate_oms": True,
                "does_not_mutate_production_ledger": True,
            },
        )


def _latest_execution_reconciliation(
    db: Any,
    *,
    trading_day: str,
) -> dict[str, Any]:
    if not trading_day or not hasattr(db, "list_execution_reconciliation_runs_sync"):
        return {"status": "not_available", "evidence_ref": ""}
    rows = db.list_execution_reconciliation_runs_sync(limit=50)
    for row in rows:
        if str(row.get("run_date") or "") != trading_day:
            continue
        status = str(row.get("status") or "not_available")
        open_count = int(row.get("open_item_count") or 0)
        return {
            "status": "clear" if status == "clear" and open_count == 0 else status,
            "evidence_ref": f"execution_reconciliation:{row.get('run_id')}",
            "open_item_count": open_count,
        }
    return {"status": "not_available", "evidence_ref": ""}


def _market_calendar_evidence(
    db: Any,
    *,
    trading_day: str,
) -> dict[str, Any]:
    if not trading_day or not hasattr(db, "get_market_calendar_snapshot_sync"):
        return {
            "status": "not_available",
            "is_trading_day": False,
            "evidence_ref": "",
        }
    year = int(trading_day[:4])
    row = db.get_market_calendar_snapshot_sync(exchange="SSE", year=year)
    if row is None:
        return {
            "status": "not_available",
            "is_trading_day": False,
            "evidence_ref": "",
        }
    days = json_list(row.get("days_json"))
    day = next(
        (
            item
            for item in days
            if isinstance(item, dict) and str(item.get("date") or "") == trading_day
        ),
        None,
    )
    if day is None:
        return {
            "status": "day_missing",
            "is_trading_day": False,
            "evidence_ref": (
                f"market_calendar:SSE:{year}:{row.get('source_fingerprint') or ''}"
            ),
        }
    return {
        "status": "available",
        "exchange": "SSE",
        "provider": str(row.get("provider") or ""),
        "source_fingerprint": str(row.get("source_fingerprint") or ""),
        "official_verification_status": str(
            row.get("official_verification_status") or "unverified"
        ),
        "date": trading_day,
        "day_type": str(day.get("day_type") or ""),
        "reason_code": str(day.get("reason_code") or ""),
        "is_trading_day": bool(day.get("is_trading_day")),
        "evidence_ref": (
            f"market_calendar:SSE:{year}:{row.get('source_fingerprint') or ''}"
        ),
    }


__all__ = [
    "BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE",
    "BROKER_CONNECTOR_SOAK_EVENT_SOURCE",
    "BROKER_CONNECTOR_SOAK_EVENT_TYPE",
    "BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION",
    "BROKER_CONNECTOR_SOAK_SOURCE_SEQUENCE_SCHEMA_VERSION",
    "BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION",
    "BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS",
    "BrokerConnectorSoakService",
    "reviewed_broker_soak_sequence_is_accepted",
]
