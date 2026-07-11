"""Read-only broker connector soak evidence and health summaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_observation.v1"
)
BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION = "karkinos.broker_connector_soak_status.v1"
BROKER_CONNECTOR_SOAK_EVENT_TYPE = "broker_connector.snapshot_observed"
BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE = "broker_connector_soak_observation"
BROKER_CONNECTOR_SOAK_EVENT_SOURCE = "broker_connector_soak"
BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS = 20

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CLEAR_EXECUTION_RECONCILIATION_STATUSES = frozenset({"clear"})
_REQUIRED_READ_CAPABILITIES = (
    "can_read_account",
    "can_read_cash",
    "can_read_positions",
    "can_read_orders",
    "can_read_fills",
    "can_read_health",
)


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

    def capture(
        self,
        *,
        max_snapshot_age_seconds: int = 900,
    ) -> dict[str, Any]:
        observed_at = _aware_utc(self._clock())
        max_age = max(60, min(int(max_snapshot_age_seconds), 86400))
        observations: list[dict[str, Any]] = []
        for connector in self._connectors:
            observations.append(
                self._capture_connector(
                    connector,
                    observed_at=observed_at,
                    max_snapshot_age_seconds=max_age,
                )
            )
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
        rows = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
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
                _connector_id(connector)
                for connector in self._connectors
                if _connector_id(connector)
            }
        )
        summaries = [
            _connector_summary(
                connector_id,
                observations=[
                    observation
                    for observation in observations
                    if observation.get("connector_id") == connector_id
                ],
            )
            for connector_id in sorted(set(connector_ids) | set(configured_ids))
        ]
        return {
            "schema_version": BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION,
            "target_trading_days": BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
            "configured_connector_count": len(self._connectors),
            "observed_connector_count": len(connector_ids),
            "observation_count": len(observations),
            "connectors": summaries,
            "operational_soak_complete": bool(summaries)
            and all(item["operational_soak_complete"] for item in summaries),
            "promotion_ready": False,
            "promotion_blockers": _promotion_blockers(summaries),
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
        connector_id = _connector_id(connector)
        try:
            capabilities = getattr(connector, "capabilities")
            snapshot = connector.read_account_snapshot()
            trading_day = _trading_day(snapshot.captured_at)
            payload = _observation_payload(
                connector_id=connector_id,
                capabilities=capabilities,
                snapshot=snapshot,
                observed_at=observed_at,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
                market_calendar=_market_calendar_evidence(
                    self._db,
                    trading_day=trading_day,
                ),
                execution_reconciliation=_latest_execution_reconciliation(
                    self._db,
                    trading_day=trading_day,
                ),
            )
        except Exception as exc:  # connector errors must degrade, never execute
            payload = _failed_observation_payload(
                connector_id=connector_id,
                observed_at=observed_at,
                reason_code=type(exc).__name__,
            )

        observation_id = str(payload["observation_id"])
        existing = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            response = self._event_response(existing[0], reused=True)
            self._record_soak_alert(response)
            return response

        self._db.append_event_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            timestamp=observed_at.isoformat(),
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            source_ref=connector_id or observation_id,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=observation_id,
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("broker connector soak observation was not recorded")
        response = self._event_response(saved[0], reused=False)
        self._record_soak_alert(response)
        return response

    def _event_response(
        self,
        row: dict[str, Any],
        *,
        reused: bool,
    ) -> dict[str, Any]:
        payload = _json_object(row.get("payload_json"))
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
        connector_id = str(observation.get("connector_id") or "unknown")
        trading_day = str(observation.get("trading_day") or "unknown")
        blockers = [str(item) for item in observation.get("blockers") or []]
        self._db.upsert_automation_alert_sync(
            alert_key=(
                f"broker_connector_soak:{connector_id}:{trading_day}:{soak_status}"
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
                "connector_id": connector_id,
                "account_alias": observation.get("account_alias"),
                "trading_day": trading_day,
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


def _observation_payload(
    *,
    connector_id: str,
    capabilities: Any,
    snapshot: Any,
    observed_at: datetime,
    max_snapshot_age_seconds: int,
    market_calendar: dict[str, Any],
    execution_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    effective_connector_id = connector_id or str(snapshot.connector_id or "")
    captured_at = str(snapshot.captured_at or "")
    captured = _parse_timestamp(captured_at)
    age_seconds: int | None = None
    blockers: list[str] = []
    if not effective_connector_id:
        blockers.append("missing_connector_id")
    if not str(snapshot.account_alias or ""):
        blockers.append("missing_account_alias")
    if captured is None:
        blockers.append("invalid_snapshot_captured_at")
    else:
        age = (observed_at - captured.astimezone(timezone.utc)).total_seconds()
        age_seconds = int(max(0, age))
        if age < -300:
            blockers.append("snapshot_time_in_future")
        elif age > max_snapshot_age_seconds:
            blockers.append("snapshot_stale")

    capability_payload = _capability_payload(capabilities)
    for capability in _REQUIRED_READ_CAPABILITIES:
        if not capability_payload[capability]:
            blockers.append(f"missing_read_capability:{capability}")
    if capability_payload["can_submit_orders"]:
        blockers.append("connector_exposes_submit_capability")

    source_health_status = str(snapshot.health.status or "incomplete")
    if source_health_status != "healthy":
        blockers.append(f"source_health:{source_health_status}")
    if snapshot.cash is None:
        blockers.append("cash_fact_missing")
    if market_calendar.get("status") != "available":
        blockers.append("market_calendar_missing")
    elif not market_calendar.get("is_trading_day"):
        blockers.append("not_market_trading_day")

    snapshot_evidence = _snapshot_evidence(
        snapshot=snapshot,
        capabilities=capability_payload,
    )
    snapshot_fingerprint = _fingerprint(snapshot_evidence)
    trading_day = _trading_day(captured_at)
    soak_status = _soak_status(blockers)
    observation_id = _fingerprint(
        {
            "connector_id": effective_connector_id,
            "snapshot_fingerprint": snapshot_fingerprint,
            "trading_day": trading_day,
            "soak_status": soak_status,
            "max_snapshot_age_seconds": max_snapshot_age_seconds,
        }
    )
    return {
        "schema_version": BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_id,
        "connector_id": effective_connector_id,
        "account_alias": str(snapshot.account_alias or ""),
        "account_ref_hash": _account_ref_hash(str(snapshot.account_id or "")),
        "source_name": str(snapshot.source_name or ""),
        "source_captured_at": captured_at,
        "trading_day": trading_day,
        "observed_at": observed_at.isoformat(),
        "max_snapshot_age_seconds": max_snapshot_age_seconds,
        "snapshot_age_seconds": age_seconds,
        "source_health_status": source_health_status,
        "soak_status": soak_status,
        "blockers": list(dict.fromkeys(blockers)),
        "snapshot_fingerprint": snapshot_fingerprint,
        "capabilities": capability_payload,
        "counts": {
            "cash": 1 if snapshot.cash is not None else 0,
            "positions": len(snapshot.positions),
            "orders": len(snapshot.orders),
            "fills": len(snapshot.fills),
        },
        "snapshot": snapshot_evidence,
        "market_calendar": market_calendar,
        "execution_reconciliation": execution_reconciliation,
        "account_truth_reconciliation": {
            "status": "not_linked",
            "evidence_ref": "",
        },
        "qualifies_for_healthy_soak_day": soak_status == "healthy",
        "qualifies_for_promotion_day": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "limitations": sorted(
            set(
                [
                    *[str(item) for item in snapshot.limitations],
                    "Snapshot evidence is local and read-only.",
                    "Account Truth reconciliation is not linked in this slice.",
                ]
            )
        ),
    }


def _failed_observation_payload(
    *,
    connector_id: str,
    observed_at: datetime,
    reason_code: str,
) -> dict[str, Any]:
    trading_day = observed_at.astimezone(_SHANGHAI).date().isoformat()
    observation_id = _fingerprint(
        {
            "connector_id": connector_id,
            "trading_day": trading_day,
            "reason_code": reason_code,
            "soak_status": "blocked",
        }
    )
    return {
        "schema_version": BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_id,
        "connector_id": connector_id,
        "account_alias": "",
        "account_ref_hash": "",
        "source_name": "",
        "source_captured_at": "",
        "trading_day": trading_day,
        "observed_at": observed_at.isoformat(),
        "max_snapshot_age_seconds": None,
        "snapshot_age_seconds": None,
        "source_health_status": "incomplete",
        "soak_status": "blocked",
        "blockers": [f"connector_read_failed:{reason_code}"],
        "snapshot_fingerprint": "",
        "capabilities": _capability_payload(None),
        "counts": {"cash": 0, "positions": 0, "orders": 0, "fills": 0},
        "snapshot": {},
        "market_calendar": {
            "status": "not_available",
            "is_trading_day": False,
            "evidence_ref": "",
        },
        "execution_reconciliation": {
            "status": "not_available",
            "evidence_ref": "",
        },
        "account_truth_reconciliation": {
            "status": "not_linked",
            "evidence_ref": "",
        },
        "qualifies_for_healthy_soak_day": False,
        "qualifies_for_promotion_day": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "limitations": [
            "Connector read failure was recorded without broker-write contact.",
            "Account Truth reconciliation is not linked in this slice.",
        ],
    }


def _snapshot_evidence(
    *, snapshot: Any, capabilities: dict[str, bool]
) -> dict[str, Any]:
    cash = _json_safe(snapshot.cash) if snapshot.cash is not None else None
    positions = sorted(
        (_json_safe(item) for item in snapshot.positions),
        key=lambda item: (
            str(item.get("symbol") or ""),
            str(item.get("asset_class") or ""),
        ),
    )
    orders = sorted(
        (_json_safe(item) for item in snapshot.orders),
        key=lambda item: str(item.get("order_id") or ""),
    )
    fills = sorted(
        (_json_safe(item) for item in snapshot.fills),
        key=lambda item: str(item.get("fill_id") or ""),
    )
    return {
        "connector_id": str(snapshot.connector_id or ""),
        "source_name": str(snapshot.source_name or ""),
        "account_alias": str(snapshot.account_alias or ""),
        "account_ref_hash": _account_ref_hash(str(snapshot.account_id or "")),
        "captured_at": str(snapshot.captured_at or ""),
        "health": _json_safe(snapshot.health),
        "capabilities": capabilities,
        "cash": cash,
        "positions": positions,
        "orders": orders,
        "fills": fills,
        "limitations": sorted({str(item) for item in snapshot.limitations}),
    }


def _connector_summary(
    connector_id: str,
    *,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    healthy_days = sorted(
        {
            str(item.get("trading_day") or "")
            for item in observations
            if item.get("qualifies_for_healthy_soak_day")
            and str(item.get("trading_day") or "")
        }
    )
    execution_reconciled_days = sorted(
        {
            str(item.get("trading_day") or "")
            for item in observations
            if str((item.get("execution_reconciliation") or {}).get("status"))
            in _CLEAR_EXECUTION_RECONCILIATION_STATUSES
            and str(item.get("trading_day") or "")
        }
    )
    latest = observations[0] if observations else None
    healthy_count = len(healthy_days)
    return {
        "connector_id": connector_id,
        "observation_count": len(observations),
        "healthy_trading_days": healthy_days,
        "healthy_trading_day_count": healthy_count,
        "execution_reconciled_trading_days": execution_reconciled_days,
        "execution_reconciled_trading_day_count": len(execution_reconciled_days),
        "remaining_trading_days": max(
            0, BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS - healthy_count
        ),
        "latest_observation": latest,
        "latest_soak_status": (
            str(latest.get("soak_status") or "not_observed")
            if latest
            else "not_observed"
        ),
        "operational_soak_complete": healthy_count
        >= BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
        "account_truth_reconciliation_linked": False,
        "promotion_ready": False,
    }


def _promotion_blockers(summaries: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not summaries:
        return [
            "no_readonly_connector_observations",
            "account_truth_reconciliation_not_linked",
            "owner_acceptance_missing",
        ]
    for summary in summaries:
        connector_id = str(summary["connector_id"])
        if not summary["operational_soak_complete"]:
            blockers.append(f"soak_days_incomplete:{connector_id}")
        if summary["latest_soak_status"] != "healthy":
            blockers.append(f"latest_snapshot_not_healthy:{connector_id}")
    blockers.extend(
        [
            "account_truth_reconciliation_not_linked",
            "owner_acceptance_missing",
        ]
    )
    return blockers


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
    days = _json_list(row.get("days_json"))
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


def _capability_payload(value: Any) -> dict[str, bool]:
    return {
        name: bool(getattr(value, name, False))
        for name in (*_REQUIRED_READ_CAPABILITIES, "can_submit_orders")
    }


def _soak_status(blockers: list[str]) -> str:
    critical_prefixes = (
        "missing_connector_id",
        "connector_exposes_submit_capability",
        "invalid_snapshot_captured_at",
        "snapshot_time_in_future",
    )
    if any(reason.startswith(critical_prefixes) for reason in blockers):
        return "blocked"
    return "degraded" if blockers else "healthy"


def _connector_id(connector: Any) -> str:
    value = getattr(connector, "connector_id", None)
    if value:
        return str(value)
    snapshot = getattr(connector, "_snapshot", None)
    return str(getattr(snapshot, "connector_id", "") or "")


def _trading_day(value: str) -> str:
    timestamp = _parse_timestamp(value)
    return timestamp.astimezone(_SHANGHAI).date().isoformat() if timestamp else ""


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _account_ref_hash(account_id: str) -> str:
    if not account_id:
        return ""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


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


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
