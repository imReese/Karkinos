"""Pure evidence projections for read-only broker connector soak observations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from account_truth.broker_connector import LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION

BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_observation.v1"
)
BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION = "karkinos.broker_connector_soak_status.v1"
BROKER_CONNECTOR_SOAK_EVENT_TYPE = "broker_connector.snapshot_observed"
BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE = "broker_connector_soak_observation"
BROKER_CONNECTOR_SOAK_EVENT_SOURCE = "broker_connector_soak"
BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS = 20
BROKER_CONNECTOR_SOAK_SOURCE_SEQUENCE_SCHEMA_VERSION = (
    "karkinos.broker_connector_soak_source_sequence.v1"
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
CLEAR_EXECUTION_RECONCILIATION_STATUSES = frozenset({"clear"})
REQUIRED_READ_CAPABILITIES = (
    "can_read_account",
    "can_read_cash",
    "can_read_positions",
    "can_read_orders",
    "can_read_fills",
    "can_read_health",
)


def build_observation_payload(
    *,
    connector_id: str,
    capabilities: Any,
    snapshot: Any,
    source_contract_required: bool,
    observed_at: datetime,
    max_snapshot_age_seconds: int,
    market_calendar: dict[str, Any],
    execution_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    effective_connector_id = connector_id or str(snapshot.connector_id or "")
    captured_at = str(snapshot.captured_at or "")
    captured = parse_timestamp(captured_at)
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

    capabilities_payload = capability_payload(capabilities)
    for capability in REQUIRED_READ_CAPABILITIES:
        if not capabilities_payload[capability]:
            blockers.append(f"missing_read_capability:{capability}")
    if capabilities_payload["can_submit_orders"]:
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

    source_contract = json_safe(getattr(snapshot, "source_contract", None))
    if not isinstance(source_contract, dict):
        source_contract = {}
    blockers.extend(
        source_contract_blockers(
            source_contract,
            required=source_contract_required,
            connector_id=effective_connector_id,
            captured_at=captured_at,
            observed_at=observed_at,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
        )
    )

    evidence = snapshot_evidence(
        snapshot=snapshot,
        capabilities=capabilities_payload,
        source_contract=source_contract,
    )
    snapshot_fingerprint = fingerprint(evidence)
    trading_date = trading_day(captured_at)
    payload = {
        "schema_version": BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION,
        "observation_id": "",
        "connector_id": effective_connector_id,
        "account_alias": str(snapshot.account_alias or ""),
        "account_ref_hash": account_ref_hash(str(snapshot.account_id or "")),
        "source_name": str(snapshot.source_name or ""),
        "source_captured_at": captured_at,
        "trading_day": trading_date,
        "observed_at": observed_at.isoformat(),
        "max_snapshot_age_seconds": max_snapshot_age_seconds,
        "snapshot_age_seconds": age_seconds,
        "source_health_status": source_health_status,
        "source_contract_required": source_contract_required,
        "source_contract": source_contract,
        "soak_status": soak_status(blockers),
        "blockers": list(dict.fromkeys(blockers)),
        "snapshot_fingerprint": snapshot_fingerprint,
        "capabilities": capabilities_payload,
        "counts": {
            "cash": 1 if snapshot.cash is not None else 0,
            "positions": len(snapshot.positions),
            "orders": len(snapshot.orders),
            "fills": len(snapshot.fills),
        },
        "snapshot": evidence,
        "market_calendar": market_calendar,
        "execution_reconciliation": execution_reconciliation,
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
    payload["observation_id"] = observation_id(payload)
    return payload


def build_failed_observation_payload(
    *, connector_id: str, observed_at: datetime, reason_code: str
) -> dict[str, Any]:
    trading_date = observed_at.astimezone(SHANGHAI).date().isoformat()
    failed_observation_id = fingerprint(
        {
            "connector_id": connector_id,
            "trading_day": trading_date,
            "reason_code": reason_code,
            "soak_status": "blocked",
        }
    )
    return {
        "schema_version": BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION,
        "observation_id": failed_observation_id,
        "connector_id": connector_id,
        "account_alias": "",
        "account_ref_hash": "",
        "source_name": "",
        "source_captured_at": "",
        "trading_day": trading_date,
        "observed_at": observed_at.isoformat(),
        "max_snapshot_age_seconds": None,
        "snapshot_age_seconds": None,
        "source_health_status": "incomplete",
        "source_contract": {},
        "soak_status": "blocked",
        "blockers": [f"connector_read_failed:{reason_code}"],
        "snapshot_fingerprint": "",
        "capabilities": capability_payload(None),
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


def with_source_sequence(
    payload: dict[str, Any],
    *,
    evidence: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    finalized = dict(payload)
    finalized["source_sequence"] = evidence
    finalized["blockers"] = list(
        dict.fromkeys(
            [
                *[str(item) for item in payload.get("blockers") or []],
                *blockers,
            ]
        )
    )
    finalized["soak_status"] = soak_status(finalized["blockers"])
    finalized["qualifies_for_healthy_soak_day"] = (
        finalized["soak_status"] == "healthy" and evidence.get("accepted") is True
    )
    finalized["observation_id"] = observation_id(finalized)
    return finalized


def source_sequence_evidence(
    contract: dict[str, Any],
    *,
    status: str,
    expected_previous_cursor: int | None,
    accepted: bool,
    state_advanced: bool,
) -> dict[str, Any]:
    return {
        "schema_version": BROKER_CONNECTOR_SOAK_SOURCE_SEQUENCE_SCHEMA_VERSION,
        "status": status,
        "deployment_identity": str(contract.get("deployment_identity") or ""),
        "batch_id": str(contract.get("batch_id") or ""),
        "cursor_previous": strict_nonnegative_int(contract.get("cursor_previous")),
        "cursor_current": strict_nonnegative_int(contract.get("cursor_current")),
        "expected_previous_cursor": expected_previous_cursor,
        "accepted": accepted,
        "state_advanced": state_advanced,
    }


def source_sequence_has_invalid_source(payload: dict[str, Any]) -> bool:
    prefixes = (
        "missing_read_capability:",
        "connector_exposes_submit_capability",
        "invalid_snapshot_captured_at",
        "snapshot_time_in_future",
        "snapshot_stale",
        "source_health:",
        "cash_fact_missing",
        "source_contract_",
        "source_heartbeat_",
        "source_scope_incomplete:",
    )
    return any(
        str(blocker).startswith(prefixes) for blocker in payload.get("blockers") or []
    )


def source_contract_is_partial(contract: dict[str, Any]) -> bool:
    return any(
        contract.get(f"{scope}_complete") is not True
        for scope in ("cash", "positions", "orders", "fills")
    )


def captured_after_state(payload: dict[str, Any], state: Mapping[str, Any]) -> bool:
    current = parse_timestamp(str(payload.get("source_captured_at") or ""))
    previous = parse_timestamp(str(state["last_source_captured_at"] or ""))
    return bool(current is not None and previous is not None and current > previous)


def strict_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def snapshot_evidence(
    *, snapshot: Any, capabilities: dict[str, bool], source_contract: dict[str, Any]
) -> dict[str, Any]:
    cash = json_safe(snapshot.cash) if snapshot.cash is not None else None
    positions = sorted(
        (json_safe(item) for item in snapshot.positions),
        key=lambda item: (
            str(item.get("symbol") or ""),
            str(item.get("asset_class") or ""),
        ),
    )
    orders = sorted(
        (json_safe(item) for item in snapshot.orders),
        key=lambda item: str(item.get("order_id") or ""),
    )
    fills = sorted(
        (json_safe(item) for item in snapshot.fills),
        key=lambda item: str(item.get("fill_id") or ""),
    )
    return {
        "connector_id": str(snapshot.connector_id or ""),
        "source_name": str(snapshot.source_name or ""),
        "account_alias": str(snapshot.account_alias or ""),
        "account_ref_hash": account_ref_hash(str(snapshot.account_id or "")),
        "captured_at": str(snapshot.captured_at or ""),
        "health": json_safe(snapshot.health),
        "source_contract": source_contract,
        "capabilities": capabilities,
        "cash": cash,
        "positions": positions,
        "orders": orders,
        "fills": fills,
        "limitations": sorted({str(item) for item in snapshot.limitations}),
    }


def source_contract_blockers(
    contract: dict[str, Any],
    *,
    required: bool,
    connector_id: str,
    captured_at: str,
    observed_at: datetime,
    max_snapshot_age_seconds: int,
) -> list[str]:
    if not contract:
        return ["source_contract_missing"] if required else []

    blockers: list[str] = []
    if str(contract.get("schema_version") or "") != (
        LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION
    ):
        blockers.append("source_contract_schema_invalid")
    if str(contract.get("connector_id") or "") != connector_id:
        blockers.append("source_contract_connector_mismatch")
    for key in ("deployment_identity", "batch_id"):
        if not str(contract.get(key) or "").strip():
            blockers.append(f"source_contract_{key}_missing")
    cursor_previous = strict_nonnegative_int(contract.get("cursor_previous"))
    cursor_current = strict_nonnegative_int(contract.get("cursor_current"))
    if cursor_previous is None or cursor_current is None:
        blockers.append("source_contract_cursor_invalid")
    elif cursor_current <= 0 or cursor_current != cursor_previous + 1:
        blockers.append("source_contract_cursor_not_consecutive")

    expected_trading_day = trading_day(captured_at)
    contract_trading_day = str(contract.get("trading_day") or "")
    if not contract_trading_day:
        blockers.append("source_contract_trading_day_missing")
    elif contract_trading_day != expected_trading_day:
        blockers.append("source_contract_trading_day_mismatch")
    if str(contract.get("session_phase") or "") not in {
        "startup",
        "intraday",
        "end_of_day",
    }:
        blockers.append("source_contract_session_phase_invalid")

    heartbeat = parse_timestamp(str(contract.get("heartbeat_at") or ""))
    if heartbeat is None:
        blockers.append("source_heartbeat_invalid")
    else:
        heartbeat_age = (
            observed_at - heartbeat.astimezone(timezone.utc)
        ).total_seconds()
        if heartbeat_age < -300:
            blockers.append("source_heartbeat_time_in_future")
        elif heartbeat_age > max_snapshot_age_seconds:
            blockers.append("source_heartbeat_stale")

    for key in ("cash", "positions", "orders", "fills"):
        if contract.get(f"{key}_complete") is not True:
            blockers.append(f"source_scope_incomplete:{key}")
    return blockers


def connector_summary(
    connector_id: str, *, observations: list[dict[str, Any]]
) -> dict[str, Any]:
    observed_healthy_days = sorted(
        {
            str(item.get("trading_day") or "")
            for item in observations
            if str(item.get("soak_status") or "") == "healthy"
            and str(item.get("trading_day") or "")
        }
    )
    healthy_days = sorted(
        {
            str(item.get("trading_day") or "")
            for item in observations
            if reviewed_broker_soak_sequence_is_accepted(item)
            and str(item.get("trading_day") or "")
        }
    )
    execution_reconciled_days = sorted(
        {
            str(item.get("trading_day") or "")
            for item in observations
            if str((item.get("execution_reconciliation") or {}).get("status"))
            in CLEAR_EXECUTION_RECONCILIATION_STATUSES
            and str(item.get("trading_day") or "")
        }
    )
    latest = observations[0] if observations else None
    healthy_count = len(healthy_days)
    return {
        "connector_id": connector_id,
        "observation_count": len(observations),
        "observed_healthy_trading_days": observed_healthy_days,
        "observed_healthy_trading_day_count": len(observed_healthy_days),
        "healthy_trading_days": healthy_days,
        "healthy_trading_day_count": healthy_count,
        "sequence_accepted_trading_days": healthy_days,
        "sequence_accepted_trading_day_count": healthy_count,
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
        "latest_source_sequence_accepted": bool(
            latest and reviewed_broker_soak_sequence_is_accepted(latest)
        ),
        "operational_soak_complete": healthy_count
        >= BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS,
        "account_truth_reconciliation_linked": False,
        "promotion_ready": False,
    }


def promotion_blockers(summaries: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not summaries:
        return [
            "no_readonly_connector_observations",
            "account_truth_reconciliation_not_linked",
            "owner_acceptance_missing",
        ]
    for summary in summaries:
        connector = str(summary["connector_id"])
        if not summary["operational_soak_complete"]:
            blockers.append(f"soak_days_incomplete:{connector}")
        if summary["latest_soak_status"] != "healthy":
            blockers.append(f"latest_snapshot_not_healthy:{connector}")
        elif not summary["latest_source_sequence_accepted"]:
            blockers.append(f"latest_source_sequence_not_accepted:{connector}")
    blockers.extend(
        ["account_truth_reconciliation_not_linked", "owner_acceptance_missing"]
    )
    return blockers


def capability_payload(value: Any) -> dict[str, bool]:
    return {
        name: bool(getattr(value, name, False))
        for name in (*REQUIRED_READ_CAPABILITIES, "can_submit_orders")
    }


def soak_status(blockers: list[str]) -> str:
    critical_prefixes = (
        "missing_connector_id",
        "connector_exposes_submit_capability",
        "invalid_snapshot_captured_at",
        "snapshot_time_in_future",
        "source_contract_",
        "source_heartbeat_",
        "source_scope_incomplete:",
        "source_sequence_",
    )
    if any(reason.startswith(critical_prefixes) for reason in blockers):
        return "blocked"
    return "degraded" if blockers else "healthy"


def observation_id(payload: dict[str, Any]) -> str:
    return fingerprint(
        {
            "connector_id": str(payload.get("connector_id") or ""),
            "snapshot_fingerprint": str(payload.get("snapshot_fingerprint") or ""),
            "trading_day": str(payload.get("trading_day") or ""),
            "soak_status": str(payload.get("soak_status") or "blocked"),
            "max_snapshot_age_seconds": payload.get("max_snapshot_age_seconds"),
            "blockers": sorted({str(item) for item in payload.get("blockers") or []}),
        }
    )


def reviewed_broker_soak_sequence_is_accepted(
    observation: dict[str, Any],
) -> bool:
    contract = observation.get("source_contract")
    sequence = observation.get("source_sequence")
    if not isinstance(contract, dict) or not isinstance(sequence, dict):
        return False
    if str(contract.get("schema_version") or "") != (
        LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION
    ):
        return False
    if str(sequence.get("schema_version") or "") != (
        BROKER_CONNECTOR_SOAK_SOURCE_SEQUENCE_SCHEMA_VERSION
    ):
        return False
    if observation.get("source_contract_required") is not True:
        return False
    if observation.get("qualifies_for_healthy_soak_day") is not True:
        return False
    if str(observation.get("soak_status") or "") != "healthy":
        return False
    if observation.get("blockers"):
        return False
    if sequence.get("accepted") is not True or sequence.get("status") not in {
        "initial",
        "advanced",
        "replayed",
    }:
        return False
    if source_contract_is_partial(contract):
        return False
    connector = str(observation.get("connector_id") or "")
    deployment_identity = str(contract.get("deployment_identity") or "")
    batch_id = str(contract.get("batch_id") or "")
    if (
        not connector
        or str(contract.get("connector_id") or "") != connector
        or not deployment_identity
        or str(sequence.get("deployment_identity") or "") != deployment_identity
        or not batch_id
        or str(sequence.get("batch_id") or "") != batch_id
    ):
        return False
    contract_cursor = tuple(
        strict_nonnegative_int(contract.get(field))
        for field in ("cursor_previous", "cursor_current")
    )
    sequence_cursor = tuple(
        strict_nonnegative_int(sequence.get(field))
        for field in ("cursor_previous", "cursor_current")
    )
    if any(value is None for value in (*contract_cursor, *sequence_cursor)):
        return False
    return contract_cursor == sequence_cursor


def connector_id(connector: Any) -> str:
    value = getattr(connector, "connector_id", None)
    if value:
        return str(value)
    snapshot = getattr(connector, "_snapshot", None)
    return str(getattr(snapshot, "connector_id", "") or "")


def trading_day(value: str) -> str:
    timestamp = parse_timestamp(value)
    return timestamp.astimezone(SHANGHAI).date().isoformat() if timestamp else ""


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def account_ref_hash(account_id: str) -> str:
    if not account_id:
        return ""
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def fingerprint(value: Any) -> str:
    payload = json.dumps(
        json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


__all__ = [
    "BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE",
    "BROKER_CONNECTOR_SOAK_EVENT_SOURCE",
    "BROKER_CONNECTOR_SOAK_EVENT_TYPE",
    "BROKER_CONNECTOR_SOAK_OBSERVATION_SCHEMA_VERSION",
    "BROKER_CONNECTOR_SOAK_SOURCE_SEQUENCE_SCHEMA_VERSION",
    "BROKER_CONNECTOR_SOAK_STATUS_SCHEMA_VERSION",
    "BROKER_CONNECTOR_SOAK_TARGET_TRADING_DAYS",
    "aware_utc",
    "build_failed_observation_payload",
    "build_observation_payload",
    "captured_after_state",
    "connector_id",
    "connector_summary",
    "json_list",
    "json_object",
    "promotion_blockers",
    "reviewed_broker_soak_sequence_is_accepted",
    "source_contract_is_partial",
    "source_sequence_evidence",
    "source_sequence_has_invalid_source",
    "strict_nonnegative_int",
    "trading_day",
    "with_source_sequence",
]
