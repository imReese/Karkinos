"""Write-lock revalidation for controlled reconciliation clearance."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from account_truth.broker_order_lifecycle import (
    broker_order_lifecycle_terminal_outcome,
    resolve_broker_order_lifecycle_from_connection,
)
from server.persistence.controlled_clearance_repository import (
    get_broker_evidence_event,
    get_latest_reconciliation_item,
    get_latest_usable_broker_import,
    get_oms_order,
    get_submit_intent,
)
from server.persistence.controlled_clearance_values import (
    ControlledClearanceWritePlan,
)
from server.persistence.database_normalization import json_dict


def build_controlled_clearance_write_plan(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
) -> ControlledClearanceWritePlan:
    """Re-read every mutable source while the UoW owns the write lock."""

    intent = get_submit_intent(conn, requested["submit_intent_id"])
    order = get_oms_order(conn, requested["order_id"])
    latest_item = get_latest_reconciliation_item(conn, requested["order_id"])
    blockers: list[str] = []
    _validate_intent(intent, requested, blockers)
    _validate_order_and_terminal_lifecycle(
        conn,
        intent=intent,
        order=order,
        requested=requested,
        blockers=blockers,
    )
    _validate_reconciliation_item(latest_item, requested, blockers)
    _validate_latest_import(conn, requested, blockers)

    fill_rows = list(requested.get("fills") or [])
    terminal_status = str(requested.get("terminal_status") or "")
    fill_quantity = sum(
        (Decimal(str(item.get("fill_quantity") or "0")) for item in fill_rows),
        Decimal("0"),
    )
    order_quantity = (
        Decimal(str(order["quantity"])) if order is not None else Decimal("0")
    )
    cancelled_quantity = Decimal(str(requested.get("cancelled_quantity") or "0"))
    _validate_fill_quantities(
        requested=requested,
        fill_rows=fill_rows,
        terminal_status=terminal_status,
        fill_quantity=fill_quantity,
        order_quantity=order_quantity,
        cancelled_quantity=cancelled_quantity,
        blockers=blockers,
    )
    _validate_broker_events(conn, requested, fill_rows, blockers)
    return ControlledClearanceWritePlan(
        fill_rows=tuple(fill_rows),
        terminal_status=terminal_status,
        fill_quantity=fill_quantity,
        cancelled_quantity=cancelled_quantity,
        blockers=tuple(blockers),
    )


def _validate_intent(
    intent: sqlite3.Row | None,
    requested: dict[str, Any],
    blockers: list[str],
) -> None:
    if intent is None:
        blockers.append("controlled_submission_intent_not_found")
        return
    if str(intent["status"]) != "submitted":
        blockers.append("controlled_submission_intent_not_submitted")
    if str(intent["order_id"]) != requested["order_id"]:
        blockers.append("controlled_submission_intent_order_mismatch")
    if str(intent["submit_fingerprint"]) != requested["submit_fingerprint"]:
        blockers.append("controlled_submission_submit_fingerprint_changed")
    if str(intent["broker_order_id"]) != requested["broker_order_id"]:
        blockers.append("controlled_submission_broker_order_changed")
    if str(intent["client_order_id"]) != requested["client_order_id"]:
        blockers.append("controlled_submission_client_order_changed")


def _validate_order_and_terminal_lifecycle(
    conn: sqlite3.Connection,
    *,
    intent: sqlite3.Row | None,
    order: sqlite3.Row | None,
    requested: dict[str, Any],
    blockers: list[str],
) -> None:
    if order is None or str(order["status"]) != "submitted":
        blockers.append("controlled_submission_oms_not_submitted")
    if intent is None or order is None:
        return
    account_alias = str(json_dict(intent["payload_json"]).get("account_alias") or "")
    if not account_alias:
        return
    lifecycle_evidence = resolve_broker_order_lifecycle_from_connection(
        conn,
        gateway_id=str(intent["gateway_id"] or ""),
        account_alias=account_alias,
        broker_order_id=str(intent["broker_order_id"] or ""),
        client_order_id=str(intent["client_order_id"] or ""),
    )
    terminal_lifecycle = broker_order_lifecycle_terminal_outcome(
        dict(order),
        lifecycle_evidence,
    )
    if terminal_lifecycle["status"] in {"blocked", "non_terminal"}:
        blockers.extend(terminal_lifecycle["blockers"])
        blockers.append("controlled_submission_terminal_outcome_changed")
    elif terminal_lifecycle["status"] == "terminal":
        expected_terminal_fields = {
            "terminal_status": requested["terminal_status"],
            "filled_quantity": requested["fill_quantity"],
            "cancelled_quantity": requested["cancelled_quantity"],
            "observation_id": requested["lifecycle_observation_id"],
            "evidence_fingerprint": requested["lifecycle_evidence_fingerprint"],
            "source_sequence": requested["lifecycle_source_sequence"],
        }
        for field, expected in expected_terminal_fields.items():
            if str(terminal_lifecycle.get(field) or "") != str(expected or ""):
                blockers.append(
                    "controlled_submission_terminal_" f"lifecycle_{field}_changed"
                )
    elif requested["terminal_status"] == "cancelled":
        blockers.append("controlled_submission_terminal_lifecycle_missing")


def _validate_reconciliation_item(
    latest_item: sqlite3.Row | None,
    requested: dict[str, Any],
    blockers: list[str],
) -> None:
    if latest_item is None:
        blockers.append("controlled_submission_reconciliation_item_missing")
        return
    if int(latest_item["id"]) != int(requested["review_reconciliation_item_id"]):
        blockers.append("controlled_submission_reconciliation_item_superseded")
    if str(latest_item["run_id"]) != requested["review_reconciliation_run_id"]:
        blockers.append("controlled_submission_reconciliation_run_changed")
    clearable_item_statuses = {
        "filled": {"controlled_submission_broker_evidence_available"},
        "cancelled": {
            "controlled_submission_partial_fill_cancel_evidence_available",
            "controlled_submission_cancel_evidence_available",
        },
    }
    if str(latest_item["item_status"]) not in clearable_item_statuses.get(
        str(requested.get("terminal_status") or ""),
        set(),
    ):
        blockers.append("controlled_submission_reconciliation_item_not_clearable")
    item_payload = json_dict(latest_item["payload_json"])
    item_summary = item_payload.get("controlled_submission_evidence_summary")
    item_summary = item_summary if isinstance(item_summary, dict) else {}
    if str(item_summary.get("submit_intent_id") or "") != requested["submit_intent_id"]:
        blockers.append("controlled_submission_reconciliation_intent_changed")
    if (
        str(item_summary.get("broker_evidence_fingerprint") or "")
        != requested["broker_evidence_fingerprint"]
    ):
        blockers.append("controlled_submission_broker_evidence_changed")


def _validate_latest_import(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    blockers: list[str],
) -> None:
    latest_import = get_latest_usable_broker_import(conn)
    if latest_import is None:
        blockers.append("controlled_submission_account_truth_import_missing")
        return
    if str(latest_import["import_run_id"]) != requested["account_truth_import_run_id"]:
        blockers.append("controlled_submission_account_truth_import_superseded")
    if (
        str(latest_import["file_fingerprint"])
        != requested["account_truth_file_fingerprint"]
    ):
        blockers.append("controlled_submission_account_truth_file_changed")


def _validate_fill_quantities(
    *,
    requested: dict[str, Any],
    fill_rows: list[dict[str, Any]],
    terminal_status: str,
    fill_quantity: Decimal,
    order_quantity: Decimal,
    cancelled_quantity: Decimal,
    blockers: list[str],
) -> None:
    if not fill_rows and terminal_status != "cancelled":
        blockers.append("controlled_submission_fill_evidence_missing")
    if str(requested.get("fill_quantity") or "0") != str(fill_quantity):
        blockers.append("controlled_submission_fill_quantity_changed")
    if terminal_status == "filled" and (
        fill_quantity <= 0
        or fill_quantity != abs(order_quantity)
        or cancelled_quantity != 0
    ):
        blockers.append("controlled_submission_full_fill_incomplete")
    elif terminal_status == "cancelled" and (
        cancelled_quantity <= 0
        or fill_quantity + cancelled_quantity != abs(order_quantity)
    ):
        blockers.append("controlled_submission_cancel_quantity_incomplete")
    elif terminal_status not in {"filled", "cancelled"}:
        blockers.append("controlled_submission_terminal_status_invalid")


def _validate_broker_events(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
    fill_rows: list[dict[str, Any]],
    blockers: list[str],
) -> None:
    for fill in fill_rows:
        broker_event = get_broker_evidence_event(
            conn,
            import_run_id=fill.get("account_truth_import_run_id"),
            event_id=fill.get("broker_event_id"),
            row_fingerprint=fill.get("broker_row_fingerprint"),
        )
        if broker_event is None:
            blockers.append("controlled_submission_broker_event_source_changed")
            continue
        expected_values = {
            "symbol": fill.get("symbol"),
            "price": fill.get("fill_price"),
            "fee": fill.get("fee"),
            "tax": fill.get("tax"),
            "transfer_fee": fill.get("transfer_fee"),
            "broker_order_id": requested["broker_order_id"],
            "client_order_id": requested["client_order_id"],
        }
        for field, expected in expected_values.items():
            if str(broker_event[field] or "") != str(expected or ""):
                blockers.append(f"controlled_submission_broker_event_{field}_changed")
        if abs(Decimal(str(broker_event["quantity"]))) != Decimal(
            str(fill.get("fill_quantity") or "0")
        ):
            blockers.append("controlled_submission_broker_event_quantity_changed")
