"""Shared content-identity validation for persisted valuation snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from server.contracts.quote_ingestion import quote_timestamp_instant
from server.projections.quote_status import quote_valuation_status

_VALUATION_SCOPE_POLICY = "current_nonzero_positions.v1"
_VALUATION_FRESHNESS_POLICY = "expected_session_and_live_ttl.v1"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MIN_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _quote_timestamp(row: dict[str, Any]) -> str:
    return str(row.get("quote_timestamp") or row.get("timestamp") or "")


def _snapshot_status(quotes: list[dict[str, Any]]) -> str:
    if not quotes:
        return "complete"
    statuses = {quote_valuation_status(row) for row in quotes}
    if "missing" in statuses:
        return "missing"
    if "degraded" in statuses:
        return "degraded"
    return "complete"


def _snapshot_trade_date(quotes: list[dict[str, Any]], as_of: str) -> str:
    quote_timestamps = [
        parsed
        for row in quotes
        if _quote_timestamp(row)
        and (parsed := quote_timestamp_instant(_quote_timestamp(row))) != _MIN_TIMESTAMP
    ]
    effective = max(quote_timestamps, default=quote_timestamp_instant(as_of))
    return effective.astimezone(_SHANGHAI_TZ).date().isoformat()


def validate_valuation_snapshot(payload: dict[str, Any]) -> None:
    """Recompute a persisted valuation identity and reject content drift."""

    quotes = payload.get("quotes")
    metadata = payload.get("metadata")
    if not isinstance(quotes, list) or any(
        not isinstance(quote, dict) for quote in quotes
    ):
        raise ValueError("valuation snapshot quotes are invalid")
    if not isinstance(metadata, dict):
        raise ValueError("valuation snapshot metadata is invalid")
    quote_set_fingerprint = _fingerprint(quotes)
    if payload.get("quote_set_fingerprint") != quote_set_fingerprint:
        raise ValueError("valuation snapshot quote fingerprint drifted")
    ledger_cutoff_id = payload.get("ledger_cutoff_id")
    if isinstance(ledger_cutoff_id, bool) or not isinstance(ledger_cutoff_id, int):
        raise ValueError("valuation snapshot ledger cutoff is invalid")
    ledger_fingerprint = str(payload.get("ledger_fingerprint") or "")
    if len(ledger_fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in ledger_fingerprint
    ):
        raise ValueError("valuation snapshot ledger fingerprint is invalid")

    is_v5 = metadata.get("valuation_freshness_policy") is not None
    if is_v5:
        if metadata.get("valuation_scope_policy") != _VALUATION_SCOPE_POLICY:
            raise ValueError("valuation snapshot scope policy drifted")
        if metadata.get("valuation_freshness_policy") != _VALUATION_FRESHNESS_POLICY:
            raise ValueError("valuation snapshot freshness policy drifted")
        if metadata.get("quote_count") != len(quotes):
            raise ValueError("valuation snapshot quote count drifted")
        if payload.get("status") != _snapshot_status(quotes):
            raise ValueError("valuation snapshot status drifted")
        if payload.get("trade_date") != _snapshot_trade_date(
            quotes,
            str(payload.get("as_of") or ""),
        ):
            raise ValueError("valuation snapshot trade date drifted")
        identity_payload = {
            "valuation_policy": payload["valuation_policy"],
            "as_of": payload["as_of"],
            "trade_date": payload["trade_date"],
            "status": payload["status"],
            "ledger_cutoff_id": int(payload.get("ledger_cutoff_id") or 0),
            "ledger_fingerprint": payload["ledger_fingerprint"],
            "quote_set_fingerprint": payload["quote_set_fingerprint"],
            "metadata": payload["metadata"],
        }
    else:
        identity_payload = {
            "valuation_policy": payload["valuation_policy"],
            "quote_set_fingerprint": quote_set_fingerprint,
            "ledger_fingerprint": ledger_fingerprint,
            "ledger_cutoff_id": ledger_cutoff_id,
        }
    expected_snapshot_id = f"valuation-{_fingerprint(identity_payload)}"
    if payload.get("snapshot_id") != expected_snapshot_id:
        raise ValueError("valuation snapshot content identity drifted")


__all__ = ["validate_valuation_snapshot"]
