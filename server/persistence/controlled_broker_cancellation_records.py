"""Persistence record mapping for controlled broker cancellation."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.controlled_broker_cancellation import cancellation_json_object


def controlled_broker_cancellation_command_row(
    row: sqlite3.Row | None,
) -> dict[str, Any]:
    """Map one SQLite row to the stable persistence record shape."""

    if row is None:
        return {}
    result = dict(row)
    result["payload"] = cancellation_json_object(result.get("payload_json"))
    result["result"] = cancellation_json_object(result.get("result_json"))
    result["last_query_result"] = cancellation_json_object(
        result.get("last_query_result_json")
    )
    return result


def controlled_broker_cancellation_store_rejection(
    blockers: list[str],
) -> dict[str, Any]:
    """Return one fail-closed persistence decision."""

    return {
        "status": "rejected",
        "reused": False,
        "external_call_permitted": False,
        "command": {},
        "blockers": list(dict.fromkeys(str(item) for item in blockers)),
    }
