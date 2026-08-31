"""Persisted broker lifecycle resolution and safety projections."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from account_truth.broker_order_lifecycle_contracts import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_BINDING_SCHEMA_VERSION,
    BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
    broker_order_lifecycle_safety_flags,
)
from account_truth.broker_order_lifecycle_values import broker_order_decimal as _decimal
from account_truth.broker_order_lifecycle_values import broker_order_dict as _dict
from account_truth.broker_order_lifecycle_values import (
    broker_order_json_list as _json_list,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_json_object as _json_object,
)
from account_truth.broker_order_lifecycle_values import (
    broker_order_lifecycle_fingerprint as _fingerprint,
)
from account_truth.broker_order_lifecycle_values import (
    format_broker_order_decimal as _format_decimal,
)


def resolve_broker_order_lifecycle_from_connection(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    account_alias: str,
    broker_order_id: str,
    client_order_id: str,
) -> dict[str, Any]:
    """Resolve persisted evidence using the caller's current SQLite transaction."""

    identity = {
        "gateway_id": str(gateway_id or ""),
        "account_alias": str(account_alias or ""),
        "broker_order_id": str(broker_order_id or ""),
        "client_order_id": str(client_order_id or ""),
    }
    if not all(identity.values()):
        return _resolution("identity_incomplete", identity=identity)
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not {
        "broker_order_lifecycle_observations",
        "broker_order_lifecycle_orders",
        "broker_order_lifecycle_fills",
    }.issubset(tables):
        return _resolution("not_configured", identity=identity)
    row = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_observations
        WHERE gateway_id = ?
          AND account_alias = ?
          AND (broker_order_id = ? OR client_order_id = ?)
        ORDER BY captured_at DESC, id DESC
        LIMIT 1
        """,
        (
            identity["gateway_id"],
            identity["account_alias"],
            identity["broker_order_id"],
            identity["client_order_id"],
        ),
    ).fetchone()
    if row is None:
        return _resolution("not_found", identity=identity)
    observation = _observation_from_row(row, reused=False)
    collector_evidence = _resolve_broker_order_lifecycle_collector_evidence(
        conn,
        observation,
    )
    if str(row["validation_status"]) != "pass":
        return {
            **_resolution(
                "blocked",
                identity=identity,
                observation=observation,
                blockers=[str(item) for item in observation.get("blockers") or []],
            ),
            "collector_evidence": collector_evidence,
        }
    if (
        str(row["broker_order_id"]) != identity["broker_order_id"]
        or str(row["client_order_id"]) != identity["client_order_id"]
    ):
        return {
            **_resolution(
                "identity_conflict",
                identity=identity,
                observation=observation,
                blockers=["broker_order_lifecycle_order_identity_conflict"],
            ),
            "collector_evidence": collector_evidence,
        }
    order_row = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_orders
        WHERE observation_id = ? LIMIT 1
        """,
        (str(row["observation_id"]),),
    ).fetchone()
    fill_rows = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_fills
        WHERE observation_id = ? ORDER BY filled_at ASC, id ASC
        """,
        (str(row["observation_id"]),),
    ).fetchall()
    if order_row is None:
        return {
            **_resolution(
                "blocked",
                identity=identity,
                observation=observation,
                blockers=["broker_order_lifecycle_order_fact_missing"],
            ),
            "collector_evidence": collector_evidence,
        }
    return {
        **_resolution(
            "found",
            identity=identity,
            observation=observation,
        ),
        "order": _order_from_row(order_row),
        "fills": [_fill_from_row(fill_row) for fill_row in fill_rows],
        "fill_count": len(fill_rows),
        "collector_evidence": collector_evidence,
    }


def broker_order_lifecycle_clearance_blockers(
    order: dict[str, Any],
    evidence: dict[str, Any],
) -> list[str]:
    """Return canonical blockers for treating a controlled order as fully filled."""

    resolution_status = str(evidence.get("status") or "")
    if resolution_status in {"blocked", "identity_conflict"}:
        return ["controlled_submission_clearance_lifecycle_evidence_blocked"]
    if resolution_status != "found":
        return []
    collector_evidence = _dict(evidence.get("collector_evidence"))
    if (
        bool(collector_evidence.get("required"))
        and str(collector_evidence.get("status") or "") != "healthy"
    ):
        return ["controlled_submission_clearance_lifecycle_collector_unhealthy"]
    lifecycle_order = _dict(evidence.get("order"))
    expected_quantity = abs(_decimal(order.get("quantity")))
    filled_quantity = abs(_decimal(lifecycle_order.get("cumulative_filled_quantity")))
    cancelled_quantity = abs(_decimal(lifecycle_order.get("cancelled_quantity")))
    if (
        str(lifecycle_order.get("status") or "") != "filled"
        or str(lifecycle_order.get("symbol") or "") != str(order.get("symbol") or "")
        or str(lifecycle_order.get("side") or "") != str(order.get("side") or "")
        or abs(_decimal(lifecycle_order.get("order_quantity"))) != expected_quantity
        or filled_quantity != expected_quantity
        or cancelled_quantity != 0
    ):
        return ["controlled_submission_clearance_lifecycle_evidence_mismatch"]
    return []


def broker_order_lifecycle_terminal_outcome(
    order: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Resolve an exact terminal fill/cancel fact without granting authority."""

    base = {
        "schema_version": "karkinos.broker_order_lifecycle_terminal_outcome.v1",
        "status": "not_available",
        "terminal_status": "",
        "order_quantity": "0",
        "filled_quantity": "0",
        "cancelled_quantity": "0",
        "observation_id": "",
        "evidence_fingerprint": "",
        "source_sequence": 0,
        "fill_count": 0,
        "fill_fingerprint": _fingerprint([]),
        "blockers": [],
        "provider_contacted": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_fills": True,
        "does_not_mutate_production_ledger": True,
        "does_not_release_submission_interlock": True,
        "authorizes_execution": False,
    }
    resolution_status = str(evidence.get("status") or "")
    if resolution_status in {"blocked", "identity_conflict"}:
        return {
            **base,
            "status": "blocked",
            "blockers": [
                "controlled_submission_terminal_clearance_lifecycle_evidence_blocked"
            ],
        }
    if resolution_status != "found":
        return base

    observation = _dict(evidence.get("observation"))
    lifecycle_order = _dict(evidence.get("order"))
    lifecycle_fills = [
        _dict(item) for item in evidence.get("fills") or [] if isinstance(item, dict)
    ]
    expected_quantity = abs(_decimal(order.get("quantity")))
    order_quantity = abs(_decimal(lifecycle_order.get("order_quantity")))
    filled_quantity = abs(_decimal(lifecycle_order.get("cumulative_filled_quantity")))
    cancelled_quantity = abs(_decimal(lifecycle_order.get("cancelled_quantity")))
    blockers: list[str] = []

    collector_evidence = _dict(evidence.get("collector_evidence"))
    if (
        bool(collector_evidence.get("required"))
        and str(collector_evidence.get("status") or "") != "healthy"
    ):
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_collector_unhealthy"
        )
    if str(lifecycle_order.get("symbol") or "") != str(order.get("symbol") or ""):
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_symbol_mismatch"
        )
    if str(lifecycle_order.get("side") or "") != str(order.get("side") or ""):
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_side_mismatch"
        )
    if expected_quantity <= 0 or order_quantity != expected_quantity:
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_quantity_mismatch"
        )

    lifecycle_status = str(lifecycle_order.get("status") or "")
    terminal_status = (
        lifecycle_status if lifecycle_status in {"filled", "cancelled"} else ""
    )
    if terminal_status == "filled" and (
        filled_quantity != expected_quantity or cancelled_quantity != 0
    ):
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_fill_mismatch"
        )
    elif terminal_status == "cancelled" and (
        cancelled_quantity <= 0
        or filled_quantity + cancelled_quantity != expected_quantity
    ):
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_cancel_mismatch"
        )

    fill_quantity = sum(
        (abs(_decimal(item.get("quantity"))) for item in lifecycle_fills),
        Decimal("0"),
    )
    if fill_quantity != filled_quantity:
        blockers.append(
            "controlled_submission_terminal_clearance_lifecycle_fill_sum_mismatch"
        )
    status = (
        "blocked" if blockers else ("terminal" if terminal_status else "non_terminal")
    )
    return {
        **base,
        "status": status,
        "terminal_status": terminal_status,
        "order_quantity": _format_decimal(order_quantity),
        "filled_quantity": _format_decimal(filled_quantity),
        "cancelled_quantity": _format_decimal(cancelled_quantity),
        "observation_id": str(observation.get("observation_id") or ""),
        "evidence_fingerprint": str(observation.get("evidence_fingerprint") or ""),
        "source_sequence": int(observation.get("source_sequence") or 0),
        "fill_count": len(lifecycle_fills),
        "fill_fingerprint": _fingerprint(lifecycle_fills),
        "blockers": list(dict.fromkeys(blockers)),
    }


def _resolve_broker_order_lifecycle_collector_evidence(
    conn: sqlite3.Connection,
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Resolve optional collector binding without contacting a provider."""

    base = {
        "schema_version": BROKER_ORDER_LIFECYCLE_COLLECTOR_BINDING_SCHEMA_VERSION,
        "status": "not_configured",
        "required": False,
        "blockers": [],
        "observation_bound": False,
        "matching_run_id": "",
        "latest_run_id": "",
        "latest_run_status": "",
        "latest_cursor": 0,
        "state_cursor": 0,
        "collector_id": "",
        "deployment_id": "",
        "collection_mode": "",
        "source_contact_status": "",
        "connection_status": "",
        "batch_status": "",
        "release_review_status": "",
        "provider_contacted_by_karkinos": False,
        "broker_submission_enabled": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_fills": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
    }
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not {
        "broker_order_lifecycle_collector_runs",
        "broker_order_lifecycle_collector_state",
    }.issubset(tables):
        return base

    scope = (
        str(observation.get("provider") or ""),
        str(observation.get("gateway_id") or ""),
        str(observation.get("account_alias") or ""),
    )
    latest = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_collector_runs
        WHERE provider = ? AND gateway_id = ? AND account_alias = ?
          AND run_status != 'duplicate'
        ORDER BY id DESC LIMIT 1
        """,
        scope,
    ).fetchone()
    if latest is None:
        return {**base, "status": "not_bound"}

    matching = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_collector_runs
        WHERE lifecycle_observation_id = ? AND run_status = 'recorded'
        ORDER BY id ASC LIMIT 1
        """,
        (str(observation.get("observation_id") or ""),),
    ).fetchone()
    blockers: list[str] = []
    if matching is None:
        blockers.append("broker_order_lifecycle_collector_observation_not_bound")
    else:
        for field in ("provider", "gateway_id", "account_alias"):
            if str(matching[field]) != str(observation.get(field) or ""):
                blockers.append(
                    f"broker_order_lifecycle_collector_{field}_binding_mismatch"
                )
        if int(matching["cursor_current"]) != int(
            observation.get("source_sequence") or 0
        ):
            blockers.append(
                "broker_order_lifecycle_collector_source_sequence_binding_mismatch"
            )

    latest_status = str(latest["run_status"] or "")
    if latest_status == "prepared":
        blockers.append("broker_order_lifecycle_collector_recovery_pending")
    elif latest_status == "blocked":
        blockers.append("broker_order_lifecycle_collector_latest_run_blocked")
    elif latest_status != "recorded":
        blockers.append("broker_order_lifecycle_collector_latest_run_invalid")

    state = conn.execute(
        """
        SELECT * FROM broker_order_lifecycle_collector_state
        WHERE scope_key = ? LIMIT 1
        """,
        (str(latest["scope_key"] or ""),),
    ).fetchone()
    state_cursor = int(state["last_cursor"]) if state is not None else 0
    if latest_status == "recorded":
        if state is None:
            blockers.append("broker_order_lifecycle_collector_state_missing")
        else:
            for field in (
                "collector_id",
                "deployment_id",
                "deployment_fingerprint",
                "release_evidence_ref",
                "adapter_authorization_ref",
                "provider",
                "gateway_id",
                "account_alias",
            ):
                if str(state[field]) != str(latest[field]):
                    blockers.append(
                        f"broker_order_lifecycle_collector_state_{field}_mismatch"
                    )
            if state_cursor != int(latest["cursor_current"]):
                blockers.append(
                    "broker_order_lifecycle_collector_state_cursor_mismatch"
                )

    status = "healthy"
    if blockers:
        if latest_status == "prepared":
            status = "recovery_pending"
        elif latest_status == "blocked":
            status = "blocked"
        elif matching is None:
            status = "unbound"
        else:
            status = "inconsistent"
    return {
        **base,
        "status": status,
        "required": True,
        "blockers": list(dict.fromkeys(blockers)),
        "observation_bound": matching is not None,
        "matching_run_id": str(matching["run_id"] or "") if matching else "",
        "latest_run_id": str(latest["run_id"] or ""),
        "latest_run_status": latest_status,
        "latest_cursor": int(latest["cursor_current"]),
        "state_cursor": state_cursor,
        "collector_id": str(latest["collector_id"] or ""),
        "deployment_id": str(latest["deployment_id"] or ""),
        "collection_mode": str(latest["collection_mode"] or ""),
        "source_contact_status": str(latest["source_contact_status"] or ""),
        "connection_status": str(latest["connection_status"] or ""),
        "batch_status": str(latest["batch_status"] or ""),
        "release_review_status": str(latest["release_review_status"] or ""),
    }


def _observation_from_row(
    row: sqlite3.Row,
    *,
    reused: bool,
) -> dict[str, Any]:
    payload = _json_object(row["payload_json"])
    return {
        "schema_version": str(row["schema_version"]),
        "observation_id": str(row["observation_id"]),
        "provider": str(row["provider"]),
        "snapshot_kind": str(row["snapshot_kind"]),
        "gateway_id": str(row["gateway_id"]),
        "account_alias": str(row["account_alias"]),
        "account_ref_hash": str(row["account_ref_hash"]),
        "source_name": str(row["source_name"]),
        "source_sequence": int(row["source_sequence"]),
        "captured_at": str(row["captured_at"]),
        "observed_at": str(row["observed_at"]),
        "max_snapshot_age_seconds": int(row["max_snapshot_age_seconds"]),
        "file_fingerprint": str(row["file_fingerprint"]),
        "evidence_fingerprint": str(row["evidence_fingerprint"]),
        "validation_status": str(row["validation_status"]),
        "blockers": _json_list(row["blockers_json"]),
        "broker_order_id": str(row["broker_order_id"]),
        "client_order_id": str(row["client_order_id"]),
        "recorded_at": str(row["created_at"]),
        "persisted": True,
        "reused": reused,
        "fill_count": int(payload.get("fill_count") or 0),
        **broker_order_lifecycle_safety_flags(),
    }


def _order_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "broker_order_id",
            "client_order_id",
            "symbol",
            "side",
            "status",
            "order_quantity",
            "cumulative_filled_quantity",
            "cancelled_quantity",
            "average_fill_price",
            "submitted_at",
            "updated_at",
            "order_fingerprint",
        )
    }


def _fill_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "broker_trade_id",
            "broker_order_id",
            "client_order_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "fee",
            "tax",
            "transfer_fee",
            "net_amount",
            "filled_at",
            "fill_fingerprint",
        )
    }


def _resolution(
    status: str,
    *,
    identity: dict[str, str],
    observation: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": BROKER_ORDER_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "identity": identity,
        "observation": observation or {},
        "blockers": list(blockers or []),
        **broker_order_lifecycle_safety_flags(),
    }


# Public implementation seams keep repository modules off private imports.
broker_order_lifecycle_observation_from_row = _observation_from_row
broker_order_lifecycle_resolution = _resolution
