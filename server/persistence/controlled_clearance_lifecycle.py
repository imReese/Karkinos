"""Persisted lifecycle revalidation for controlled-submission clearances."""

from __future__ import annotations

import sqlite3
from typing import Any

from account_truth.broker_order_lifecycle import (
    broker_order_lifecycle_terminal_outcome,
    resolve_broker_order_lifecycle_from_connection,
)
from server.persistence.database_normalization import json_dict


def controlled_lifecycle_invalidated_clearance_rows(
    conn: sqlite3.Connection,
    *,
    exclude_order_id: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Find cleared intents contradicted by newer persisted lifecycle facts."""

    rows = conn.execute(
        """
        SELECT intent.*, oms.status AS oms_status,
               oms.symbol AS oms_symbol, oms.side AS oms_side,
               oms.quantity AS oms_quantity,
               clearance.terminal_status AS clearance_terminal_status,
               clearance.fill_quantity AS clearance_fill_quantity,
               clearance.cancelled_quantity AS clearance_cancelled_quantity,
               clearance.lifecycle_observation_id AS clearance_lifecycle_observation_id,
               clearance.lifecycle_evidence_fingerprint AS clearance_lifecycle_evidence_fingerprint
        FROM controlled_broker_submit_intents AS intent
        JOIN controlled_submission_reconciliation_clearances AS clearance
          ON clearance.submit_intent_id = intent.submit_intent_id
         AND clearance.status = 'cleared'
        JOIN oms_orders AS oms ON oms.order_id = intent.order_id
        WHERE intent.status = 'submitted'
          AND intent.order_id != ?
        ORDER BY intent.prepared_at_epoch_ms ASC, intent.id ASC
        LIMIT ?
        """,
        (str(exclude_order_id or ""), max(1, min(int(limit), 500))),
    ).fetchall()
    invalidated: list[dict[str, Any]] = []
    for row in rows:
        intent = dict(row)
        account_alias = str(
            json_dict(intent.get("payload_json")).get("account_alias") or ""
        )
        if not account_alias:
            continue
        evidence = resolve_broker_order_lifecycle_from_connection(
            conn,
            gateway_id=str(intent.get("gateway_id") or ""),
            account_alias=account_alias,
            broker_order_id=str(intent.get("broker_order_id") or ""),
            client_order_id=str(intent.get("client_order_id") or ""),
        )
        terminal = broker_order_lifecycle_terminal_outcome(
            {
                "symbol": str(intent.get("oms_symbol") or ""),
                "side": str(intent.get("oms_side") or ""),
                "quantity": intent.get("oms_quantity"),
            },
            evidence,
        )
        lifecycle_blockers = list(terminal.get("blockers") or [])
        persisted_observation_id = str(
            intent.get("clearance_lifecycle_observation_id") or ""
        )
        persisted_evidence_fingerprint = str(
            intent.get("clearance_lifecycle_evidence_fingerprint") or ""
        )
        if terminal.get("status") == "non_terminal":
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_lifecycle_not_terminal"
            )
        elif terminal.get("status") == "not_available" and persisted_observation_id:
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_lifecycle_missing"
            )
        elif terminal.get("status") == "terminal":
            comparisons = {
                "terminal_status": intent.get("clearance_terminal_status"),
                "filled_quantity": intent.get("clearance_fill_quantity"),
                "cancelled_quantity": intent.get("clearance_cancelled_quantity"),
            }
            for field, expected in comparisons.items():
                if str(terminal.get(field) or "") != str(expected or ""):
                    lifecycle_blockers.append(
                        f"controlled_submission_terminal_clearance_{field}_changed"
                    )
            if persisted_observation_id and persisted_observation_id != str(
                terminal.get("observation_id") or ""
            ):
                lifecycle_blockers.append(
                    "controlled_submission_terminal_clearance_observation_changed"
                )
            if (
                persisted_evidence_fingerprint
                and persisted_evidence_fingerprint
                != str(terminal.get("evidence_fingerprint") or "")
            ):
                lifecycle_blockers.append(
                    "controlled_submission_terminal_clearance_evidence_changed"
                )
        expected_oms_status = str(intent.get("clearance_terminal_status") or "")
        if str(intent.get("oms_status") or "") != expected_oms_status and evidence.get(
            "status"
        ) in {"found", "blocked", "identity_conflict"}:
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_oms_status_changed"
            )
        if lifecycle_blockers:
            observation = evidence.get("observation")
            observation = observation if isinstance(observation, dict) else {}
            intent["interlock_reason"] = "lifecycle_clearance_invalidated"
            intent["lifecycle_blocker"] = lifecycle_blockers[0]
            intent["lifecycle_observation_id"] = str(
                observation.get("observation_id") or ""
            )
            invalidated.append(intent)
    return invalidated


__all__ = ["controlled_lifecycle_invalidated_clearance_rows"]
