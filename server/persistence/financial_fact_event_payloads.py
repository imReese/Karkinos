"""Pure event projections for persisted financial-fact rows."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.quote_ingestion import quote_timestamp_instant
from server.persistence.database_serialization import metadata_payload_value


def quote_observation_rank(row: dict[str, Any]) -> tuple[Any, int]:
    """Order quote observations by instant, never by ISO string spelling."""

    raw = str(row.get("timestamp") or row.get("quote_timestamp") or "").strip()
    return quote_timestamp_instant(raw), int(row.get("id") or 0)


def order_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "order_row_id": row["id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": row["quantity"],
        "price": row["price"],
        "asset_class": row["asset_class"],
        "intent_id": row["intent_id"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_mode": row["execution_mode"],
        "status": row["status"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "payload": metadata_payload_value(row["payload_json"]),
    }


def manual_order_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "order_row_id": row["id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": row["quantity"],
        "price": row["price"],
        "intent_id": row["intent_id"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_mode": row["execution_mode"],
        "status": row["status"],
        "note": row["note"],
        "payload": metadata_payload_value(row["payload_json"]),
    }


def fill_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "fill_row_id": row["id"],
        "fill_id": row["fill_id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "fill_price": row["fill_price"],
        "fill_quantity": row["fill_quantity"],
        "commission": row["commission"],
        "slippage": row["slippage"],
        "asset_class": row["asset_class"],
        "execution_mode": row["execution_mode"],
        "provider_name": row["provider_name"],
        "broker_order_id": row["broker_order_id"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "metadata": metadata_payload_value(row["metadata_json"]),
    }


def latest_quote_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "quote_id": row["id"],
        "symbol": row["symbol"],
        "asset_type": row["asset_type"],
        "price": row["price"],
        "previous_close": row["previous_close"],
        "change": row["change"],
        "change_percent": row["change_percent"],
        "volume": row["volume"],
        "turnover": row["turnover"],
        "quote_timestamp": row["quote_timestamp"],
        "quote_source": row["quote_source"],
        "provider_name": row["provider_name"],
        "provider_status": row["provider_status"],
        "quote_status": row["quote_status"],
        "stale_reason": row["stale_reason"],
        "captured_at": row["captured_at"],
        "captured_reason": row["captured_reason"],
        "nav_date": row["nav_date"],
        "fetch_run_id": row["fetch_run_id"],
        "metadata": metadata_payload_value(row["metadata_json"]),
    }


def action_task_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["id"],
        "source_signal_id": row["source_signal_id"],
        "symbol": row["symbol"],
        "title": row["title"],
        "detail": row["detail"],
        "direction": row["direction"],
        "urgency": row["urgency"],
        "target_weight": row["target_weight"],
        "price": row["price"],
        "strategy_id": row["strategy_id"],
        "timestamp": row["timestamp"],
        "asset_class": row["asset_class"],
        "status": row["status"],
    }


__all__ = [
    "action_task_event_payload",
    "fill_event_payload",
    "latest_quote_event_payload",
    "manual_order_event_payload",
    "order_event_payload",
    "quote_observation_rank",
]
