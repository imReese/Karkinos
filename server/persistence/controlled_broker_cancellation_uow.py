"""Atomic write-side unit of work for controlled broker cancellation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_order_lifecycle import (
    resolve_broker_order_lifecycle_from_connection,
)
from server.contracts.controlled_broker_cancellation import (
    CANCELLABLE_LIFECYCLE_STATUSES,
    CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS,
    cancellation_decimal,
    cancellation_fingerprint,
    cancellation_json_dump,
    cancellation_json_object,
    cancellation_mapping,
)
from server.persistence.controlled_broker_cancellation_records import (
    controlled_broker_cancellation_command_row,
    controlled_broker_cancellation_store_rejection,
)
from server.persistence.controlled_broker_cancellation_schema import (
    ensure_controlled_broker_cancellation_schema,
)


class ControlledBrokerCancellationUnitOfWork:
    """Own all cancellation claim/finalization transactions."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        order_fingerprint_builder: Callable[[dict[str, Any]], str],
    ) -> None:
        self._path = Path(database_path)
        self._order_fingerprint_builder = order_fingerprint_builder

    def prepare(
        self,
        *,
        preview: dict[str, Any],
        operator_approval_id: str,
        prepared_at_epoch_ms: int,
        prepared_at: str,
    ) -> dict[str, Any]:
        ensure_controlled_broker_cancellation_schema(self._path)
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ? OR submit_intent_id = ?
                   OR order_id = ?
                ORDER BY id ASC LIMIT 1
                """,
                (
                    preview["cancel_command_id"],
                    preview["submit_intent_id"],
                    preview["order_id"],
                ),
            ).fetchone()
            if existing is not None:
                row = controlled_broker_cancellation_command_row(existing)
                if (
                    row["cancel_command_id"] == preview["cancel_command_id"]
                    and row["cancel_fingerprint"] == preview["cancel_fingerprint"]
                    and row["submit_intent_id"] == preview["submit_intent_id"]
                ):
                    connection.commit()
                    return {
                        "status": row["status"],
                        "reused": True,
                        "external_call_permitted": False,
                        "command": row,
                        "blockers": [],
                    }
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_command_conflict"]
                )

            blockers = controlled_broker_cancellation_transaction_blockers(
                connection,
                preview,
                order_fingerprint_builder=self._order_fingerprint_builder,
            )
            if blockers:
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(blockers)

            payload = {
                key: preview[key]
                for key in (
                    "schema_version",
                    "cancel_command_id",
                    "cancel_fingerprint",
                    "submit_intent_id",
                    "submit_fingerprint",
                    "ticket_fingerprint",
                    "order_id",
                    "order_fingerprint",
                    "provider",
                    "identity",
                    "order",
                    "lifecycle_evidence",
                    "release_evidence_id",
                    "release_evidence_fingerprint",
                    "gateway_health_source_fingerprint",
                    "operator_id",
                )
            }
            payload.update(
                {
                    "operator_approval_id": operator_approval_id,
                    "status": "prepared",
                    "cancellation_proven": False,
                    "oms_mutated": False,
                    "production_ledger_mutated": False,
                    "capital_authority_changed": False,
                }
            )
            identity = cancellation_mapping(preview.get("identity"))
            lifecycle = cancellation_mapping(preview.get("lifecycle_evidence"))
            connection.execute(
                """
                INSERT INTO controlled_broker_cancellation_commands (
                    cancel_command_id, cancel_fingerprint, submit_intent_id,
                    submit_fingerprint, ticket_fingerprint, order_id,
                    order_fingerprint, provider, gateway_id, account_alias,
                    broker_order_id, client_order_id, release_evidence_id,
                    release_evidence_fingerprint, lifecycle_observation_id,
                    lifecycle_evidence_fingerprint, lifecycle_source_sequence,
                    operator_id, operator_approval_id, status,
                    prepared_at_epoch_ms, prepared_at, payload_json,
                    result_json, last_query_result_json, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'prepared', ?, ?, ?, '{}', '{}', ?, ?
                )
                """,
                (
                    preview["cancel_command_id"],
                    preview["cancel_fingerprint"],
                    preview["submit_intent_id"],
                    preview["submit_fingerprint"],
                    preview["ticket_fingerprint"],
                    preview["order_id"],
                    preview["order_fingerprint"],
                    preview["provider"],
                    identity["gateway_id"],
                    identity["account_alias"],
                    identity["broker_order_id"],
                    identity["client_order_id"],
                    preview["release_evidence_id"],
                    preview["release_evidence_fingerprint"],
                    lifecycle["observation_id"],
                    lifecycle["evidence_fingerprint"],
                    int(lifecycle["source_sequence"]),
                    preview["operator_id"],
                    operator_approval_id,
                    int(prepared_at_epoch_ms),
                    prepared_at,
                    cancellation_json_dump(payload),
                    prepared_at,
                    prepared_at,
                ),
            )
            saved = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (preview["cancel_command_id"],),
            ).fetchone()
            connection.commit()
        if saved is None:
            raise RuntimeError("controlled broker cancellation was not persisted")
        return {
            "status": "prepared",
            "reused": False,
            "external_call_permitted": True,
            "command": controlled_broker_cancellation_command_row(saved),
            "blockers": [],
        }

    def finalize(
        self,
        *,
        cancel_command_id: str,
        status: str,
        result: dict[str, Any],
        finalized_at_epoch_ms: int,
        finalized_at: str,
    ) -> dict[str, Any]:
        if status not in {
            "cancel_requested",
            "cancel_rejected",
            "cancellation_unknown",
        }:
            raise ValueError("invalid controlled broker cancellation status")
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ? LIMIT 1
                """,
                (cancel_command_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_command_not_found"]
                )
            existing = controlled_broker_cancellation_command_row(row)
            if existing["status"] != "prepared":
                if existing["status"] == status and existing["result"] == result:
                    connection.commit()
                    return {
                        "status": status,
                        "reused": True,
                        "command": existing,
                        "blockers": [],
                    }
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_finalize_conflict"]
                )
            connection.execute(
                """
                UPDATE controlled_broker_cancellation_commands
                SET status = ?, result_json = ?, finalized_at_epoch_ms = ?,
                    finalized_at = ?, updated_at = ?
                WHERE cancel_command_id = ? AND status = 'prepared'
                """,
                (
                    status,
                    cancellation_json_dump(result),
                    int(finalized_at_epoch_ms),
                    finalized_at,
                    finalized_at,
                    cancel_command_id,
                ),
            )
            saved = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (cancel_command_id,),
            ).fetchone()
            connection.commit()
        return {
            "status": status,
            "reused": False,
            "command": controlled_broker_cancellation_command_row(saved),
            "blockers": [],
        }

    def claim_recovery(
        self,
        *,
        preview: dict[str, Any],
        operator_approval_id: str,
        claimed_at_epoch_ms: int,
        claimed_at: str,
    ) -> dict[str, Any]:
        ensure_controlled_broker_cancellation_schema(self._path)
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            command_row = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ? LIMIT 1
                """,
                (preview["cancel_command_id"],),
            ).fetchone()
            if command_row is None:
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_recovery_command_not_found"]
                )
            command = controlled_broker_cancellation_command_row(command_row)
            expected_sequence = int(command["query_count"]) + 1
            recovery_claim_id = cancellation_fingerprint(
                {
                    "domain": (
                        "karkinos.controlled_broker_cancellation_recovery_claim_id.v1"
                    ),
                    "cancel_command_id": preview["cancel_command_id"],
                    "recovery_fingerprint": preview["recovery_fingerprint"],
                    "operator_approval_id": operator_approval_id,
                }
            )
            existing = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_recovery_claims
                WHERE recovery_claim_id = ? LIMIT 1
                """,
                (recovery_claim_id,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                return {
                    "status": str(existing["status"]),
                    "reused": True,
                    "external_call_permitted": False,
                    "recovery_claim_id": recovery_claim_id,
                    "command": command,
                    "blockers": [],
                }
            if int(preview["query_sequence"]) != expected_sequence:
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_recovery_sequence_changed"]
                )

            previous_epoch_ms = max(
                int(command["prepared_at_epoch_ms"]),
                int(command["last_query_at_epoch_ms"]),
            )
            elapsed_seconds = max(
                0,
                int(claimed_at_epoch_ms) // 1000 - previous_epoch_ms // 1000,
            )
            if (
                elapsed_seconds
                < CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS
            ):
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_recovery_query_wait_required"]
                )
            blockers = controlled_broker_cancellation_transaction_blockers(
                connection,
                cancellation_mapping(preview.get("source_preview")),
                order_fingerprint_builder=self._order_fingerprint_builder,
                require_command=command,
            )
            if blockers:
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(blockers)

            connection.execute(
                """
                INSERT INTO controlled_broker_cancellation_recovery_claims (
                    recovery_claim_id, recovery_fingerprint, cancel_command_id,
                    query_sequence, operator_id, operator_approval_id, status,
                    claimed_at_epoch_ms, claimed_at, result_json, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'claimed', ?, ?, '{}', ?, ?)
                """,
                (
                    recovery_claim_id,
                    preview["recovery_fingerprint"],
                    preview["cancel_command_id"],
                    expected_sequence,
                    preview["operator_id"],
                    operator_approval_id,
                    int(claimed_at_epoch_ms),
                    claimed_at,
                    claimed_at,
                    claimed_at,
                ),
            )
            connection.execute(
                """
                UPDATE controlled_broker_cancellation_commands
                SET last_query_at_epoch_ms = ?, last_query_at = ?,
                    query_count = ?, updated_at = ?
                WHERE cancel_command_id = ? AND query_count = ?
                """,
                (
                    int(claimed_at_epoch_ms),
                    claimed_at,
                    expected_sequence,
                    claimed_at,
                    preview["cancel_command_id"],
                    expected_sequence - 1,
                ),
            )
            saved = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (preview["cancel_command_id"],),
            ).fetchone()
            connection.commit()
        return {
            "status": "claimed",
            "reused": False,
            "external_call_permitted": True,
            "recovery_claim_id": recovery_claim_id,
            "command": controlled_broker_cancellation_command_row(saved),
            "blockers": [],
        }

    def finalize_recovery(
        self,
        *,
        recovery_claim_id: str,
        result: dict[str, Any],
        completed_at_epoch_ms: int,
        completed_at: str,
    ) -> dict[str, Any]:
        with sqlite3.connect(self._path, timeout=2) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=2000")
            connection.execute("BEGIN IMMEDIATE")
            claim = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_recovery_claims
                WHERE recovery_claim_id = ? LIMIT 1
                """,
                (recovery_claim_id,),
            ).fetchone()
            if claim is None:
                connection.rollback()
                return controlled_broker_cancellation_store_rejection(
                    ["controlled_broker_cancel_recovery_claim_not_found"]
                )
            if str(claim["status"]) == "completed":
                existing_result = cancellation_json_object(claim["result_json"])
                if existing_result != result:
                    connection.rollback()
                    return controlled_broker_cancellation_store_rejection(
                        ["controlled_broker_cancel_recovery_finalize_conflict"]
                    )
                command = connection.execute(
                    """
                    SELECT * FROM controlled_broker_cancellation_commands
                    WHERE cancel_command_id = ?
                    """,
                    (str(claim["cancel_command_id"]),),
                ).fetchone()
                connection.commit()
                return {
                    "status": "completed",
                    "reused": True,
                    "command": controlled_broker_cancellation_command_row(command),
                    "result": existing_result,
                    "blockers": [],
                }
            connection.execute(
                """
                UPDATE controlled_broker_cancellation_recovery_claims
                SET status = 'completed', result_json = ?,
                    completed_at_epoch_ms = ?, completed_at = ?, updated_at = ?
                WHERE recovery_claim_id = ? AND status = 'claimed'
                """,
                (
                    cancellation_json_dump(result),
                    int(completed_at_epoch_ms),
                    completed_at,
                    completed_at,
                    recovery_claim_id,
                ),
            )
            connection.execute(
                """
                UPDATE controlled_broker_cancellation_commands
                SET last_query_result_json = ?, updated_at = ?
                WHERE cancel_command_id = ?
                """,
                (
                    cancellation_json_dump(result),
                    completed_at,
                    str(claim["cancel_command_id"]),
                ),
            )
            command = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (str(claim["cancel_command_id"]),),
            ).fetchone()
            connection.commit()
        return {
            "status": "completed",
            "reused": False,
            "command": controlled_broker_cancellation_command_row(command),
            "result": result,
            "blockers": [],
        }


def controlled_broker_cancellation_transaction_blockers(
    connection: sqlite3.Connection,
    preview: dict[str, Any],
    *,
    order_fingerprint_builder: Callable[[dict[str, Any]], str],
    require_command: dict[str, Any] | None = None,
) -> list[str]:
    """Re-resolve every authority-bound fact under the write transaction."""

    blockers: list[str] = []
    if not preview:
        return ["controlled_broker_cancel_transaction_preview_missing"]
    intent = connection.execute(
        """
        SELECT * FROM controlled_broker_submit_intents
        WHERE submit_intent_id = ? LIMIT 1
        """,
        (str(preview.get("submit_intent_id") or ""),),
    ).fetchone()
    if intent is None:
        return ["controlled_broker_cancel_transaction_intent_not_found"]
    if str(intent["status"]) != "submitted":
        blockers.append("controlled_broker_cancel_transaction_intent_not_submitted")
    comparisons = {
        "submit_fingerprint": preview.get("submit_fingerprint"),
        "order_id": preview.get("order_id"),
        "order_fingerprint": preview.get("order_fingerprint"),
        "gateway_id": cancellation_mapping(preview.get("identity")).get("gateway_id"),
        "broker_order_id": cancellation_mapping(preview.get("identity")).get(
            "broker_order_id"
        ),
        "client_order_id": cancellation_mapping(preview.get("identity")).get(
            "client_order_id"
        ),
    }
    for field, expected in comparisons.items():
        if str(intent[field] or "") != str(expected or ""):
            blockers.append(f"controlled_broker_cancel_transaction_{field}_changed")
    payload = cancellation_json_object(intent["payload_json"])
    account_alias = str(
        cancellation_mapping(preview.get("identity")).get("account_alias") or ""
    )
    if str(payload.get("account_alias") or "") != account_alias:
        blockers.append("controlled_broker_cancel_transaction_account_alias_changed")

    order = connection.execute(
        "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
        (str(preview.get("order_id") or ""),),
    ).fetchone()
    if order is None:
        blockers.append("controlled_broker_cancel_transaction_order_not_found")
    else:
        order_dict = dict(order)
        if str(order["status"]) != "submitted":
            blockers.append("controlled_broker_cancel_transaction_order_not_submitted")
        if order_fingerprint_builder(order_dict) != str(
            preview.get("order_fingerprint") or ""
        ):
            blockers.append("controlled_broker_cancel_transaction_order_changed")

    identity = cancellation_mapping(preview.get("identity"))
    resolution = resolve_broker_order_lifecycle_from_connection(
        connection,
        gateway_id=str(identity.get("gateway_id") or ""),
        account_alias=account_alias,
        broker_order_id=str(identity.get("broker_order_id") or ""),
        client_order_id=str(identity.get("client_order_id") or ""),
    )
    if str(resolution.get("status") or "") != "found":
        blockers.append("controlled_broker_cancel_transaction_lifecycle_unavailable")
        blockers.extend(str(item) for item in resolution.get("blockers") or [])
    collector = cancellation_mapping(resolution.get("collector_evidence"))
    if bool(collector.get("required")) and str(collector.get("status") or "") != (
        "healthy"
    ):
        blockers.append("controlled_broker_cancel_transaction_collector_unhealthy")
    observation = cancellation_mapping(resolution.get("observation"))
    expected_lifecycle = cancellation_mapping(preview.get("lifecycle_evidence"))
    for field, expected in (
        ("observation_id", expected_lifecycle.get("observation_id")),
        ("evidence_fingerprint", expected_lifecycle.get("evidence_fingerprint")),
        ("source_sequence", expected_lifecycle.get("source_sequence")),
    ):
        if str(observation.get(field) or "") != str(expected or ""):
            blockers.append(
                f"controlled_broker_cancel_transaction_lifecycle_{field}_changed"
            )
    lifecycle_order = cancellation_mapping(resolution.get("order"))
    if str(lifecycle_order.get("status") or "") not in CANCELLABLE_LIFECYCLE_STATUSES:
        blockers.append(
            "controlled_broker_cancel_transaction_lifecycle_not_cancellable"
        )
    expected_order = cancellation_mapping(preview.get("order"))
    for field in (
        "symbol",
        "side",
        "order_quantity",
        "filled_quantity",
        "cancelled_quantity",
        "remaining_quantity",
    ):
        actual_value = (
            controlled_broker_cancellation_remaining_quantity(lifecycle_order)
            if field == "remaining_quantity"
            else lifecycle_order.get(
                {
                    "filled_quantity": "cumulative_filled_quantity",
                    "order_quantity": "order_quantity",
                    "cancelled_quantity": "cancelled_quantity",
                }.get(field, field)
            )
        )
        if field in {
            "order_quantity",
            "filled_quantity",
            "cancelled_quantity",
            "remaining_quantity",
        }:
            if cancellation_decimal(actual_value) != cancellation_decimal(
                expected_order.get(field)
            ):
                blockers.append(
                    f"controlled_broker_cancel_transaction_lifecycle_{field}_changed"
                )
        elif str(actual_value or "") != str(expected_order.get(field) or ""):
            blockers.append(
                f"controlled_broker_cancel_transaction_lifecycle_{field}_changed"
            )
    if (
        cancellation_decimal(
            controlled_broker_cancellation_remaining_quantity(lifecycle_order)
        )
        <= 0
    ):
        blockers.append("controlled_broker_cancel_transaction_no_remaining_quantity")
    if require_command is not None:
        for field in (
            "cancel_command_id",
            "cancel_fingerprint",
            "submit_intent_id",
            "order_id",
            "gateway_id",
            "account_alias",
            "broker_order_id",
            "client_order_id",
        ):
            source_value = (
                cancellation_mapping(preview.get("identity")).get(field)
                if field
                in {
                    "gateway_id",
                    "account_alias",
                    "broker_order_id",
                    "client_order_id",
                }
                else preview.get(field)
            )
            if str(require_command.get(field) or "") != str(source_value or ""):
                blockers.append(
                    f"controlled_broker_cancel_recovery_command_{field}_changed"
                )
    return list(dict.fromkeys(blockers))


def controlled_broker_cancellation_remaining_quantity(
    order: dict[str, Any],
) -> Any:
    """Calculate remaining quantity only for transaction drift comparison."""

    return (
        abs(cancellation_decimal(order.get("order_quantity")))
        - abs(cancellation_decimal(order.get("cumulative_filled_quantity")))
        - abs(cancellation_decimal(order.get("cancelled_quantity")))
    )
