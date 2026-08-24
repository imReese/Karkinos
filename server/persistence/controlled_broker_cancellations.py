"""Read repository and write-UoW facade for broker cancellation evidence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from server.contracts.controlled_broker_cancellation import cancellation_json_object
from server.persistence.controlled_broker_cancellation_records import (
    controlled_broker_cancellation_command_row,
)
from server.persistence.controlled_broker_cancellation_schema import (
    controlled_broker_cancellation_table_exists,
)
from server.persistence.controlled_broker_cancellation_uow import (
    ControlledBrokerCancellationUnitOfWork,
)


class ControlledBrokerCancellationStore:
    """Append-oriented, restart-safe store for external cancellation claims."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        order_fingerprint_builder: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        self._path = Path(db_path)
        self._uow = ControlledBrokerCancellationUnitOfWork(
            self._path,
            order_fingerprint_builder=(
                order_fingerprint_builder or controlled_broker_cancellation_no_identity
            ),
        )

    def schema_available(self) -> bool:
        return controlled_broker_cancellation_table_exists(
            self._path,
            "controlled_broker_cancellation_commands",
        )

    def get(self, cancel_command_id: str) -> dict[str, Any] | None:
        if not self.schema_available():
            return None
        with sqlite3.connect(self._path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                LIMIT 1
                """,
                (str(cancel_command_id or ""),),
            ).fetchone()
        return (
            controlled_broker_cancellation_command_row(row) if row is not None else None
        )

    def get_for_intent(self, submit_intent_id: str) -> dict[str, Any] | None:
        if not self.schema_available():
            return None
        with sqlite3.connect(self._path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE submit_intent_id = ?
                LIMIT 1
                """,
                (str(submit_intent_id or ""),),
            ).fetchone()
        return (
            controlled_broker_cancellation_command_row(row) if row is not None else None
        )

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.schema_available():
            return []
        with sqlite3.connect(self._path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                ORDER BY prepared_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [controlled_broker_cancellation_command_row(row) for row in rows]

    def find_recovery(
        self,
        *,
        recovery_fingerprint: str,
        operator_approval_id: str,
    ) -> dict[str, Any] | None:
        if not controlled_broker_cancellation_table_exists(
            self._path,
            "controlled_broker_cancellation_recovery_claims",
        ):
            return None
        with sqlite3.connect(self._path) as connection:
            connection.row_factory = sqlite3.Row
            claim = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_recovery_claims
                WHERE recovery_fingerprint = ? AND operator_approval_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (recovery_fingerprint, operator_approval_id),
            ).fetchone()
            if claim is None:
                return None
            command = connection.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ? LIMIT 1
                """,
                (str(claim["cancel_command_id"]),),
            ).fetchone()
        if command is None:
            return None
        return {
            "recovery_claim_id": str(claim["recovery_claim_id"]),
            "status": str(claim["status"]),
            "result": cancellation_json_object(claim["result_json"]),
            "command": controlled_broker_cancellation_command_row(command),
        }

    def prepare(
        self,
        *,
        preview: dict[str, Any],
        operator_approval_id: str,
        prepared_at_epoch_ms: int,
        prepared_at: str,
    ) -> dict[str, Any]:
        return self._uow.prepare(
            preview=preview,
            operator_approval_id=operator_approval_id,
            prepared_at_epoch_ms=prepared_at_epoch_ms,
            prepared_at=prepared_at,
        )

    def finalize(
        self,
        *,
        cancel_command_id: str,
        status: str,
        result: dict[str, Any],
        finalized_at_epoch_ms: int,
        finalized_at: str,
    ) -> dict[str, Any]:
        return self._uow.finalize(
            cancel_command_id=cancel_command_id,
            status=status,
            result=result,
            finalized_at_epoch_ms=finalized_at_epoch_ms,
            finalized_at=finalized_at,
        )

    def claim_recovery(
        self,
        *,
        preview: dict[str, Any],
        operator_approval_id: str,
        claimed_at_epoch_ms: int,
        claimed_at: str,
    ) -> dict[str, Any]:
        return self._uow.claim_recovery(
            preview=preview,
            operator_approval_id=operator_approval_id,
            claimed_at_epoch_ms=claimed_at_epoch_ms,
            claimed_at=claimed_at,
        )

    def finalize_recovery(
        self,
        *,
        recovery_claim_id: str,
        result: dict[str, Any],
        completed_at_epoch_ms: int,
        completed_at: str,
    ) -> dict[str, Any]:
        return self._uow.finalize_recovery(
            recovery_claim_id=recovery_claim_id,
            result=result,
            completed_at_epoch_ms=completed_at_epoch_ms,
            completed_at=completed_at,
        )


def controlled_broker_cancellation_no_identity(order: dict[str, Any]) -> str:
    """Fail closed when a write store lacks the canonical identity dependency."""

    del order
    return ""
