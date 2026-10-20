"""Pure identity, normalization, and response values for broker submission."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def intent_response(
    row: dict[str, Any],
    *,
    reused: bool,
    external_call_performed: bool,
) -> dict[str, Any]:
    payload = json_object(row.get("payload_json"))
    result = json_object(row.get("result_json"))
    status = str(row.get("status") or payload.get("status") or "not_found")
    return {
        **payload,
        "database_id": int(row.get("id") or 0),
        "submit_intent_id": str(
            row.get("submit_intent_id") or payload.get("submit_intent_id") or ""
        ),
        "submit_fingerprint": str(
            row.get("submit_fingerprint") or payload.get("submit_fingerprint") or ""
        ),
        "order_id": str(row.get("order_id") or payload.get("order_id") or ""),
        "gateway_id": str(row.get("gateway_id") or payload.get("gateway_id") or ""),
        "client_order_id": str(
            row.get("client_order_id") or payload.get("client_order_id") or ""
        ),
        "status": status,
        "broker_order_id": str(row.get("broker_order_id") or ""),
        "broker_status": str(row.get("broker_status") or ""),
        "gateway_result": result,
        "persisted": bool(row),
        "reused": reused,
        "external_call_performed": external_call_performed,
        "submitted_to_broker": status == "submitted",
        "submission_outcome_unknown": status == "submission_unknown",
        "default_broker_submission_enabled": False,
        "automatic_submission_enabled": False,
        "strategy_direct_submission_enabled": False,
        "recovery_resubmission_enabled": False,
        "production_ledger_mutated": False,
        "safety": safety_flags(),
    }


def client_order_id(
    *,
    order_id: str,
    order_fingerprint: str,
    confirmation_id: str,
    release_evidence_fingerprint: str,
) -> str:
    digest = fingerprint(
        {
            "domain": "karkinos.controlled_broker.client_order_id.v1",
            "order_id": order_id,
            "order_fingerprint": order_fingerprint,
            "confirmation_id": confirmation_id,
            "release_evidence_fingerprint": release_evidence_fingerprint,
        }
    )
    return f"KARK-{digest[:32]}"


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_timestamp(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def safety_flags() -> dict[str, bool]:
    return {
        "manual_final_signature_required": True,
        "one_shot_order_authority_only": True,
        "default_broker_submission_disabled": True,
        "automatic_submission_disabled": True,
        "strategy_direct_submission_disabled": True,
        "unknown_outcome_resubmission_disabled": True,
        "production_ledger_mutation_disabled": True,
        "automatic_capital_expansion_disabled": True,
        "unreconciled_submission_blocks_new_orders": True,
    }
