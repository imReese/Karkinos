"""One-shot, human-signed broker cancellation with query-only recovery."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from account_truth.broker_order_lifecycle import (
    resolve_broker_order_lifecycle_from_connection,
)
from server.services.manual_broker_cancellation_evidence import (
    ManualBrokerCancellationEvidenceService,
)
from server.services.operator_approval import resolve_operator_approval_with_proof
from server.services.per_order_confirmation import build_order_fingerprint

CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION = (
    "karkinos.controlled_broker_cancellation.v1"
)
CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION = (
    "karkinos.controlled_broker_cancellation_status.v1"
)
CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT = (
    "request_one_exact_broker_cancellation_once"
)
CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION = (
    "karkinos.controlled_broker_cancellation_recovery.v1"
)
CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT = (
    "query_exact_broker_cancellation_outcome_once_without_recancel"
)
CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS = 30
CONTROLLED_BROKER_CANCELLATION_GATEWAY_HEALTH_MAX_AGE_SECONDS = 60

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CANCELLABLE_LIFECYCLE_STATUSES = frozenset({"submitted", "open", "partially_filled"})
_REQUIRED_RELEASE_ASSERTIONS = (
    "broker_agreement_reviewed",
    "connector_tested",
    "program_trading_reporting_reviewed",
    "risk_controls_reviewed",
)
_CANCEL_RESULT_STATUSES = frozenset(
    {
        "accepted",
        "requested",
        "cancel_pending",
        "cancelled",
        "partial_cancelled",
        "reused",
        "rejected",
        "blocked",
        "not_found",
        "gateway_cancel_exception",
        "gateway_unavailable_after_prepare",
    }
)
_QUERY_RESULT_STATUSES = frozenset(
    {
        "accepted",
        "submitted",
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "partial_cancelled",
        "rejected",
        "not_found",
        "gateway_query_exception",
        "gateway_unavailable_after_claim",
    }
)

_COMMAND_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_broker_cancellation_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cancel_command_id TEXT NOT NULL UNIQUE,
    cancel_fingerprint TEXT NOT NULL UNIQUE,
    submit_intent_id TEXT NOT NULL UNIQUE,
    submit_fingerprint TEXT NOT NULL,
    ticket_fingerprint TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE,
    order_fingerprint TEXT NOT NULL,
    provider TEXT NOT NULL,
    gateway_id TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    broker_order_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    release_evidence_id TEXT NOT NULL,
    release_evidence_fingerprint TEXT NOT NULL,
    lifecycle_observation_id TEXT NOT NULL,
    lifecycle_evidence_fingerprint TEXT NOT NULL,
    lifecycle_source_sequence INTEGER NOT NULL CHECK(lifecycle_source_sequence >= 0),
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'prepared', 'cancel_requested', 'cancel_rejected', 'cancellation_unknown'
    )),
    prepared_at_epoch_ms INTEGER NOT NULL CHECK(prepared_at_epoch_ms >= 0),
    prepared_at TEXT NOT NULL,
    finalized_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    finalized_at TEXT NOT NULL DEFAULT '',
    last_query_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    last_query_at TEXT NOT NULL DEFAULT '',
    query_count INTEGER NOT NULL DEFAULT 0 CHECK(query_count >= 0),
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    last_query_result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_controlled_broker_cancellation_time
ON controlled_broker_cancellation_commands(prepared_at_epoch_ms DESC, id DESC);
"""

_RECOVERY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS controlled_broker_cancellation_recovery_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recovery_claim_id TEXT NOT NULL UNIQUE,
    recovery_fingerprint TEXT NOT NULL,
    cancel_command_id TEXT NOT NULL,
    query_sequence INTEGER NOT NULL CHECK(query_sequence > 0),
    operator_id TEXT NOT NULL,
    operator_approval_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('claimed', 'completed')),
    claimed_at_epoch_ms INTEGER NOT NULL CHECK(claimed_at_epoch_ms >= 0),
    claimed_at TEXT NOT NULL,
    completed_at_epoch_ms INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(cancel_command_id, query_sequence),
    FOREIGN KEY(cancel_command_id)
        REFERENCES controlled_broker_cancellation_commands(cancel_command_id)
);

CREATE INDEX IF NOT EXISTS idx_controlled_broker_cancellation_recovery_time
ON controlled_broker_cancellation_recovery_claims(
    cancel_command_id, query_sequence DESC, id DESC
);
"""


class ControlledBrokerCancellationRejected(ValueError):
    """Raised after a cancellation or recovery attempt fails closed."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class ControlledBrokerCancellationStore:
    """Append-oriented, restart-safe claim store for external cancel effects."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    def schema_available(self) -> bool:
        return self._table_exists("controlled_broker_cancellation_commands")

    def get(self, cancel_command_id: str) -> dict[str, Any] | None:
        if not self.schema_available():
            return None
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                LIMIT 1
                """,
                (str(cancel_command_id or ""),),
            ).fetchone()
            return _command_row(row) if row is not None else None

    def get_for_intent(self, submit_intent_id: str) -> dict[str, Any] | None:
        if not self.schema_available():
            return None
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE submit_intent_id = ?
                LIMIT 1
                """,
                (str(submit_intent_id or ""),),
            ).fetchone()
            return _command_row(row) if row is not None else None

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self.schema_available():
            return []
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                ORDER BY prepared_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [_command_row(row) for row in rows]

    def find_recovery(
        self,
        *,
        recovery_fingerprint: str,
        operator_approval_id: str,
    ) -> dict[str, Any] | None:
        if not self._table_exists("controlled_broker_cancellation_recovery_claims"):
            return None
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            claim = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_recovery_claims
                WHERE recovery_fingerprint = ? AND operator_approval_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (recovery_fingerprint, operator_approval_id),
            ).fetchone()
            if claim is None:
                return None
            command = conn.execute(
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
                "result": _json_object(claim["result_json"]),
                "command": _command_row(command),
            }

    def prepare(
        self,
        *,
        preview: dict[str, Any],
        operator_approval_id: str,
        prepared_at_epoch_ms: int,
        prepared_at: str,
    ) -> dict[str, Any]:
        self._ensure_schema()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
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
                row = _command_row(existing)
                if (
                    row["cancel_command_id"] == preview["cancel_command_id"]
                    and row["cancel_fingerprint"] == preview["cancel_fingerprint"]
                    and row["submit_intent_id"] == preview["submit_intent_id"]
                ):
                    conn.commit()
                    return {
                        "status": row["status"],
                        "reused": True,
                        "external_call_permitted": False,
                        "command": row,
                        "blockers": [],
                    }
                conn.rollback()
                return _store_rejection(["controlled_broker_cancel_command_conflict"])

            blockers = _transaction_blockers(conn, preview)
            if blockers:
                conn.rollback()
                return _store_rejection(blockers)

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
            identity = _mapping(preview.get("identity"))
            lifecycle = _mapping(preview.get("lifecycle_evidence"))
            conn.execute(
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
                    _json_dump(payload),
                    prepared_at,
                    prepared_at,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (preview["cancel_command_id"],),
            ).fetchone()
            conn.commit()
            if saved is None:
                raise RuntimeError("controlled broker cancellation was not persisted")
            return {
                "status": "prepared",
                "reused": False,
                "external_call_permitted": True,
                "command": _command_row(saved),
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
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ? LIMIT 1
                """,
                (cancel_command_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return _store_rejection(["controlled_broker_cancel_command_not_found"])
            existing = _command_row(row)
            if existing["status"] != "prepared":
                if existing["status"] == status and existing["result"] == result:
                    conn.commit()
                    return {
                        "status": status,
                        "reused": True,
                        "command": existing,
                        "blockers": [],
                    }
                conn.rollback()
                return _store_rejection(["controlled_broker_cancel_finalize_conflict"])
            conn.execute(
                """
                UPDATE controlled_broker_cancellation_commands
                SET status = ?, result_json = ?, finalized_at_epoch_ms = ?,
                    finalized_at = ?, updated_at = ?
                WHERE cancel_command_id = ? AND status = 'prepared'
                """,
                (
                    status,
                    _json_dump(result),
                    int(finalized_at_epoch_ms),
                    finalized_at,
                    finalized_at,
                    cancel_command_id,
                ),
            )
            saved = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (cancel_command_id,),
            ).fetchone()
            conn.commit()
            return {
                "status": status,
                "reused": False,
                "command": _command_row(saved),
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
        self._ensure_schema()
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            command_row = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ? LIMIT 1
                """,
                (preview["cancel_command_id"],),
            ).fetchone()
            if command_row is None:
                conn.rollback()
                return _store_rejection(
                    ["controlled_broker_cancel_recovery_command_not_found"]
                )
            command = _command_row(command_row)
            expected_sequence = int(command["query_count"]) + 1
            recovery_claim_id = _fingerprint(
                {
                    "domain": (
                        "karkinos.controlled_broker_cancellation_recovery_claim_id.v1"
                    ),
                    "cancel_command_id": preview["cancel_command_id"],
                    "recovery_fingerprint": preview["recovery_fingerprint"],
                    "operator_approval_id": operator_approval_id,
                }
            )
            existing = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_recovery_claims
                WHERE recovery_claim_id = ? LIMIT 1
                """,
                (recovery_claim_id,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return {
                    "status": str(existing["status"]),
                    "reused": True,
                    "external_call_permitted": False,
                    "recovery_claim_id": recovery_claim_id,
                    "command": command,
                    "blockers": [],
                }
            if int(preview["query_sequence"]) != expected_sequence:
                conn.rollback()
                return _store_rejection(
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
                conn.rollback()
                return _store_rejection(
                    ["controlled_broker_cancel_recovery_query_wait_required"]
                )
            blockers = _transaction_blockers(
                conn,
                _mapping(preview.get("source_preview")),
                require_command=command,
            )
            if blockers:
                conn.rollback()
                return _store_rejection(blockers)

            conn.execute(
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
            conn.execute(
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
            saved = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (preview["cancel_command_id"],),
            ).fetchone()
            conn.commit()
            return {
                "status": "claimed",
                "reused": False,
                "external_call_permitted": True,
                "recovery_claim_id": recovery_claim_id,
                "command": _command_row(saved),
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
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_recovery_claims
                WHERE recovery_claim_id = ? LIMIT 1
                """,
                (recovery_claim_id,),
            ).fetchone()
            if claim is None:
                conn.rollback()
                return _store_rejection(
                    ["controlled_broker_cancel_recovery_claim_not_found"]
                )
            if str(claim["status"]) == "completed":
                existing_result = _json_object(claim["result_json"])
                if existing_result != result:
                    conn.rollback()
                    return _store_rejection(
                        ["controlled_broker_cancel_recovery_finalize_conflict"]
                    )
                command = conn.execute(
                    """
                    SELECT * FROM controlled_broker_cancellation_commands
                    WHERE cancel_command_id = ?
                    """,
                    (str(claim["cancel_command_id"]),),
                ).fetchone()
                conn.commit()
                return {
                    "status": "completed",
                    "reused": True,
                    "command": _command_row(command),
                    "result": existing_result,
                    "blockers": [],
                }
            conn.execute(
                """
                UPDATE controlled_broker_cancellation_recovery_claims
                SET status = 'completed', result_json = ?,
                    completed_at_epoch_ms = ?, completed_at = ?, updated_at = ?
                WHERE recovery_claim_id = ? AND status = 'claimed'
                """,
                (
                    _json_dump(result),
                    int(completed_at_epoch_ms),
                    completed_at,
                    completed_at,
                    recovery_claim_id,
                ),
            )
            conn.execute(
                """
                UPDATE controlled_broker_cancellation_commands
                SET last_query_result_json = ?, updated_at = ?
                WHERE cancel_command_id = ?
                """,
                (
                    _json_dump(result),
                    completed_at,
                    str(claim["cancel_command_id"]),
                ),
            )
            command = conn.execute(
                """
                SELECT * FROM controlled_broker_cancellation_commands
                WHERE cancel_command_id = ?
                """,
                (str(claim["cancel_command_id"]),),
            ).fetchone()
            conn.commit()
            return {
                "status": "completed",
                "reused": False,
                "command": _command_row(command),
                "result": result,
                "blockers": [],
            }

    def _ensure_schema(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_COMMAND_TABLE_SQL)
            conn.executescript(_RECOVERY_TABLE_SQL)
            conn.commit()

    def _table_exists(self, table_name: str) -> bool:
        if not self._path.exists():
            return False
        with sqlite3.connect(self._path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = ? LIMIT 1
                """,
                (table_name,),
            ).fetchone()
            return row is not None


class ControlledBrokerCancellationService:
    """Issue one exact cancel command; broker responses remain non-authoritative."""

    def __init__(
        self,
        *,
        db: Any,
        gateways: list[Any] | tuple[Any, ...] = (),
        release_evidence_provider: Callable[[str], dict[str, Any]] | None = None,
        trusted_operator_identities: list[Any] | tuple[Any, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._gateways = list(gateways or [])
        self._release_evidence_provider = release_evidence_provider
        self._trusted_operator_identities = tuple(trusted_operator_identities)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        db_path = getattr(db, "_path", None)
        self._store = (
            ControlledBrokerCancellationStore(Path(db_path))
            if db_path is not None
            else None
        )
        self._ticket_service = ManualBrokerCancellationEvidenceService(
            db=db,
            clock=self._clock,
        )

    def get_status(self) -> dict[str, Any]:
        gateway_ids = [
            str(getattr(item, "gateway_id", "") or "")
            for item in self._gateways
            if str(getattr(item, "gateway_id", "") or "")
        ]
        duplicates = sorted(
            item for item in set(gateway_ids) if gateway_ids.count(item) > 1
        )
        ready = bool(
            gateway_ids
            and not duplicates
            and callable(self._release_evidence_provider)
            and self._trusted_operator_identities
            and self._store is not None
        )
        return {
            "schema_version": CONTROLLED_BROKER_CANCELLATION_STATUS_SCHEMA_VERSION,
            "contract_status": (
                "signed_exact_cancellation_available"
                if ready
                else "disabled_waiting_for_explicit_write_gateway_and_release_evidence"
            ),
            "registered_gateway_ids": sorted(set(gateway_ids)),
            "duplicate_gateway_ids": duplicates,
            "release_evidence_provider_configured": callable(
                self._release_evidence_provider
            ),
            "trusted_operator_signature_configured": bool(
                self._trusted_operator_identities
            ),
            "audit_store_configured": self._store is not None,
            "audit_schema_available": bool(
                self._store is not None and self._store.schema_available()
            ),
            "default_broker_cancellation_enabled": False,
            "automatic_cancellation_enabled": False,
            "strategy_direct_cancellation_enabled": False,
            "ai_direct_cancellation_enabled": False,
            "cancellation_retry_enabled": False,
            "query_only_recovery_enabled": True,
            "minimum_query_wait_seconds": (
                CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS
            ),
            "kill_switch_behavior": (
                "does_not_block_separately_signed_risk_reducing_cancellation"
            ),
            "safety": _safety_flags(),
        }

    def preview(self, *, submit_intent_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized = str(submit_intent_id or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            blockers.append("controlled_broker_cancel_submit_intent_id_invalid")

        try:
            ticket = self._ticket_service.preview(submit_intent_id=normalized)
        except Exception:
            ticket = {
                "ready": False,
                "blockers": ["controlled_broker_cancel_ticket_source_failed"],
            }
        blockers.extend(str(item) for item in ticket.get("blockers") or [])
        intent = (
            self._db.get_controlled_broker_submit_intent_sync(normalized)
            if _FINGERPRINT_PATTERN.fullmatch(normalized)
            else None
        ) or {}
        if not intent:
            blockers.append("controlled_broker_cancel_submit_intent_not_found")

        identity = _mapping(ticket.get("identity"))
        gateway_id = str(identity.get("gateway_id") or "")
        account_alias = str(identity.get("account_alias") or "")
        gateway, gateway_blockers = self._gateway(gateway_id)
        blockers.extend(gateway_blockers)
        capabilities, capability_blockers = _cancel_capabilities(gateway)
        blockers.extend(capability_blockers)
        health, health_blockers = _gateway_health(gateway, now=now)
        blockers.extend(health_blockers)

        release_evidence_id = str(intent.get("release_evidence_id") or "")
        release = self._resolve_release(
            release_evidence_id,
            expected_gateway_id=gateway_id,
            expected_account_alias=account_alias,
            now=now,
        )
        blockers.extend(str(item) for item in release.get("blockers") or [])
        operator_id = str(intent.get("operator_id") or "")
        if not _ID_PATTERN.fullmatch(operator_id):
            blockers.append("controlled_broker_cancel_operator_identity_invalid")
        if not self._trusted_operator_identities:
            blockers.append("controlled_broker_cancel_operator_signature_unconfigured")
        if self._store is None:
            blockers.append("controlled_broker_cancel_audit_store_unavailable")

        cancel_core = {
            "schema_version": CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
            "action": "cancel_exact_controlled_broker_order",
            "submit_intent_id": normalized,
            "submit_fingerprint": str(intent.get("submit_fingerprint") or ""),
            "ticket_fingerprint": str(ticket.get("ticket_fingerprint") or ""),
            "order_id": str(ticket.get("order_id") or ""),
            "order_fingerprint": str(ticket.get("order_fingerprint") or ""),
            "provider": str(ticket.get("provider") or ""),
            "identity": identity,
            "order": _mapping(ticket.get("order")),
            "lifecycle_evidence": _mapping(ticket.get("lifecycle_evidence")),
            "release_evidence_id": release_evidence_id,
            "release_evidence_fingerprint": str(
                release.get("evidence_fingerprint") or ""
            ),
            "gateway_health_source_fingerprint": str(
                health.get("source_fingerprint") or ""
            ),
            "operator_id": operator_id,
        }
        cancel_fingerprint = _fingerprint(cancel_core)
        cancel_command_id = _fingerprint(
            {
                "domain": "karkinos.controlled_broker_cancellation.command_id.v1",
                "cancel_fingerprint": cancel_fingerprint,
            }
        )
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **cancel_core,
            "cancel_command_id": cancel_command_id,
            "cancel_fingerprint": cancel_fingerprint,
            "generated_at": now.isoformat(),
            "status": "ready_for_final_signature" if not unique_blockers else "blocked",
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "gateway_capabilities": capabilities,
            "gateway_health": health,
            "release_evidence": release,
            "required_operator_approval": {
                "action": "cancel_exact_controlled_broker_order",
                "artifact_type": "controlled_broker_cancellation",
                "artifact_fingerprint": cancel_fingerprint,
            },
            "required_acknowledgement": (
                CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT
            ),
            "broker_cancel_performed": False,
            "cancellation_proven": False,
            "safety": _safety_flags(),
            "limitations": [
                "Preview reads persisted lifecycle evidence and cached gateway health only.",
                "A gateway response is audit telemetry, not canonical lifecycle or Account Truth.",
                "Only newer explicitly ingested lifecycle evidence can prove cancellation.",
                "The kill switch blocks new submissions but does not silently create cancellation authority.",
            ],
        }

    def cancel(
        self,
        *,
        submit_intent_id: str,
        cancel_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        normalized = str(submit_intent_id or "").strip().lower()
        if self._store is not None:
            existing = self._store.get_for_intent(normalized)
            if existing is not None:
                if existing["cancel_fingerprint"] == str(cancel_fingerprint or ""):
                    return _command_response(
                        existing,
                        reused=True,
                        external_call_performed=False,
                    )
                raise ControlledBrokerCancellationRejected(
                    "controlled broker cancellation conflicts with persisted command",
                    evidence={
                        "status": "rejected",
                        "submit_intent_id": normalized,
                        "cancel_command_id": existing["cancel_command_id"],
                        "blockers": ["controlled_broker_cancel_retry_conflict"],
                        "broker_cancel_performed": False,
                        "cancellation_proven": False,
                        "safety": _safety_flags(),
                    },
                )

        preview = self.preview(submit_intent_id=normalized)
        rejection_reasons: list[str] = []
        if str(cancel_fingerprint or "") != preview["cancel_fingerprint"]:
            rejection_reasons.append("controlled_broker_cancel_fingerprint_mismatch")
        if acknowledgement != CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_broker_cancel_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_broker_cancel_review_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="cancel_exact_controlled_broker_order",
            expected_artifact_type="controlled_broker_cancellation",
            expected_artifact_fingerprint=preview["cancel_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "controlled_broker_cancel_operator_approval_blocked"
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append("controlled_broker_cancel_operator_mismatch")
        if rejection_reasons:
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=str(cancel_fingerprint or ""),
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
                recovery=False,
            )
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation rejected",
                evidence=evidence,
            )
        if self._store is None:
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation audit store unavailable",
                evidence={
                    "status": "rejected",
                    "blockers": ["controlled_broker_cancel_audit_store_unavailable"],
                    "safety": _safety_flags(),
                },
            )

        now = _aware_utc(self._clock())
        transaction = self._store.prepare(
            preview=preview,
            operator_approval_id=operator_approval_id,
            prepared_at_epoch_ms=int(now.timestamp() * 1000),
            prepared_at=now.isoformat(),
        )
        if transaction["status"] == "rejected":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=str(cancel_fingerprint or ""),
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_broker_cancel_prepare_rejected"],
                transaction_blockers=transaction["blockers"],
                recovery=False,
            )
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation claim rejected",
                evidence=evidence,
            )
        if not transaction["external_call_permitted"]:
            return _command_response(
                transaction["command"],
                reused=True,
                external_call_performed=False,
            )

        fresh = self.preview(submit_intent_id=normalized)
        pre_call_blockers = list(fresh["blockers"])
        if fresh["cancel_fingerprint"] != preview["cancel_fingerprint"]:
            pre_call_blockers.append("controlled_broker_cancel_evidence_changed")
        if pre_call_blockers:
            result = {
                "status": "rejected_before_gateway_call",
                "blockers": list(dict.fromkeys(pre_call_blockers)),
                "cancel_requested": False,
            }
            finalized = self._store.finalize(
                cancel_command_id=preview["cancel_command_id"],
                status="cancel_rejected",
                result=result,
                finalized_at_epoch_ms=int(now.timestamp() * 1000),
                finalized_at=now.isoformat(),
            )
            return _command_response(
                finalized["command"],
                reused=False,
                external_call_performed=False,
            )

        gateway, gateway_blockers = self._gateway(
            str(preview["identity"].get("gateway_id") or "")
        )
        canceller = (
            getattr(gateway, "cancel_order", None) if not gateway_blockers else None
        )
        external_call_performed = callable(canceller)
        try:
            raw_result = (
                canceller(
                    client_order_id=preview["identity"]["client_order_id"],
                    cancel_command_id=preview["cancel_command_id"],
                    command_fingerprint=preview["cancel_fingerprint"],
                )
                if callable(canceller)
                else {
                    "status": "gateway_unavailable_after_prepare",
                    "cancel_requested": None,
                }
            )
            raw_result = raw_result if isinstance(raw_result, dict) else {}
        except Exception as exc:
            raw_result = {
                "status": "gateway_cancel_exception",
                "error_type": type(exc).__name__,
                "cancel_requested": None,
            }
        sanitized = _sanitize_cancel_result(raw_result)
        classification = _classify_cancel_result(
            sanitized,
            expected=preview,
        )
        finalized_at = _aware_utc(self._clock())
        finalized = self._store.finalize(
            cancel_command_id=preview["cancel_command_id"],
            status=classification,
            result=sanitized,
            finalized_at_epoch_ms=int(finalized_at.timestamp() * 1000),
            finalized_at=finalized_at.isoformat(),
        )
        if finalized["status"] == "rejected":
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation result persistence rejected",
                evidence=finalized,
            )
        return _command_response(
            finalized["command"],
            reused=False,
            external_call_performed=external_call_performed,
        )

    def preview_recovery(self, *, cancel_command_id: str) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        normalized = str(cancel_command_id or "").strip().lower()
        blockers: list[str] = []
        if not _FINGERPRINT_PATTERN.fullmatch(normalized):
            blockers.append("controlled_broker_cancel_command_id_invalid")
        command = self._store.get(normalized) if self._store is not None else None
        if command is None:
            blockers.append("controlled_broker_cancel_recovery_command_not_found")
            command = {}
        source_preview = (
            self.preview(submit_intent_id=str(command.get("submit_intent_id") or ""))
            if command
            else {}
        )
        blockers.extend(str(item) for item in source_preview.get("blockers") or [])
        if command and str(source_preview.get("cancel_fingerprint") or "") != str(
            command.get("cancel_fingerprint") or ""
        ):
            blockers.append("controlled_broker_cancel_recovery_source_drift")
        previous_epoch_ms = max(
            int(command.get("prepared_at_epoch_ms") or 0),
            int(command.get("last_query_at_epoch_ms") or 0),
        )
        elapsed_seconds = max(
            0,
            int(now.timestamp()) - previous_epoch_ms // 1000,
        )
        wait_remaining = max(
            0,
            CONTROLLED_BROKER_CANCELLATION_MINIMUM_QUERY_WAIT_SECONDS - elapsed_seconds,
        )
        if command and wait_remaining:
            blockers.append("controlled_broker_cancel_recovery_query_wait_required")
        gateway, gateway_blockers = self._gateway(str(command.get("gateway_id") or ""))
        blockers.extend(gateway_blockers)
        capabilities, capability_blockers = _cancel_capabilities(gateway)
        blockers.extend(capability_blockers)
        health, health_blockers = _gateway_health(gateway, now=now)
        blockers.extend(health_blockers)
        release = self._resolve_release(
            str(command.get("release_evidence_id") or ""),
            expected_gateway_id=str(command.get("gateway_id") or ""),
            expected_account_alias=str(command.get("account_alias") or ""),
            now=now,
        )
        blockers.extend(str(item) for item in release.get("blockers") or [])
        query_sequence = int(command.get("query_count") or 0) + 1
        recovery_core = {
            "schema_version": CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION,
            "action": "query_exact_broker_cancellation_outcome",
            "cancel_command_id": normalized,
            "cancel_fingerprint": str(command.get("cancel_fingerprint") or ""),
            "submit_intent_id": str(command.get("submit_intent_id") or ""),
            "order_id": str(command.get("order_id") or ""),
            "gateway_id": str(command.get("gateway_id") or ""),
            "account_alias": str(command.get("account_alias") or ""),
            "broker_order_id": str(command.get("broker_order_id") or ""),
            "client_order_id": str(command.get("client_order_id") or ""),
            "lifecycle_evidence_fingerprint": str(
                _mapping(source_preview.get("lifecycle_evidence")).get(
                    "evidence_fingerprint"
                )
                or ""
            ),
            "release_evidence_fingerprint": str(
                release.get("evidence_fingerprint") or ""
            ),
            "gateway_health_source_fingerprint": str(
                health.get("source_fingerprint") or ""
            ),
            "operator_id": str(command.get("operator_id") or ""),
            "query_sequence": query_sequence,
        }
        recovery_fingerprint = _fingerprint(recovery_core)
        unique_blockers = list(dict.fromkeys(blockers))
        return {
            **recovery_core,
            "recovery_fingerprint": recovery_fingerprint,
            "generated_at": now.isoformat(),
            "status": "ready_for_query_signature" if not unique_blockers else "blocked",
            "ready": not unique_blockers,
            "blockers": unique_blockers,
            "recovery_wait_remaining_seconds": wait_remaining,
            "gateway_capabilities": capabilities,
            "gateway_health": health,
            "release_evidence": release,
            "source_preview": source_preview,
            "required_operator_approval": {
                "action": "query_exact_broker_cancellation_outcome",
                "artifact_type": "controlled_broker_cancellation_recovery",
                "artifact_fingerprint": recovery_fingerprint,
            },
            "required_acknowledgement": (
                CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT
            ),
            "query_only": True,
            "recancel_enabled": False,
            "cancellation_proven": False,
            "safety": _safety_flags(),
        }

    def recover(
        self,
        *,
        cancel_command_id: str,
        recovery_fingerprint: str,
        operator_approval_id: str,
        operator_proof_signature_base64: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        if self._store is not None:
            existing = self._store.find_recovery(
                recovery_fingerprint=str(recovery_fingerprint or ""),
                operator_approval_id=str(operator_approval_id or ""),
            )
            if existing is not None:
                return {
                    **_command_response(
                        existing["command"],
                        reused=True,
                        external_call_performed=False,
                    ),
                    "recovery_claim_id": existing["recovery_claim_id"],
                    "recovery_fingerprint": str(recovery_fingerprint or ""),
                    "recovery_operator_approval_id": str(operator_approval_id or ""),
                    "recovery_query_performed": False,
                    "query_result": existing["result"],
                    "query_result_authoritative": False,
                    "query_only": True,
                    "recancel_enabled": False,
                }
        preview = self.preview_recovery(cancel_command_id=cancel_command_id)
        rejection_reasons: list[str] = []
        if str(recovery_fingerprint or "") != preview["recovery_fingerprint"]:
            rejection_reasons.append(
                "controlled_broker_cancel_recovery_fingerprint_mismatch"
            )
        if acknowledgement != CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT:
            rejection_reasons.append(
                "controlled_broker_cancel_recovery_acknowledgement_mismatch"
            )
        if preview["blockers"]:
            rejection_reasons.append("controlled_broker_cancel_recovery_blocked")
        approval, approval_blockers = resolve_operator_approval_with_proof(
            db=self._db,
            trusted_identities=self._trusted_operator_identities,
            approval_id=operator_approval_id,
            proof_signature_base64=operator_proof_signature_base64,
            expected_action="query_exact_broker_cancellation_outcome",
            expected_artifact_type="controlled_broker_cancellation_recovery",
            expected_artifact_fingerprint=preview["recovery_fingerprint"],
            clock=self._clock,
        )
        if approval_blockers:
            rejection_reasons.append(
                "controlled_broker_cancel_recovery_operator_approval_blocked"
            )
        elif str(approval.get("operator_id") or "") != preview["operator_id"]:
            rejection_reasons.append(
                "controlled_broker_cancel_recovery_operator_mismatch"
            )
        if rejection_reasons:
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=str(recovery_fingerprint or ""),
                operator_approval_id=operator_approval_id,
                rejection_reasons=rejection_reasons,
                transaction_blockers=[],
                recovery=True,
            )
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation recovery rejected",
                evidence=evidence,
            )
        if self._store is None:
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation recovery store unavailable",
                evidence={
                    "status": "rejected",
                    "blockers": ["controlled_broker_cancel_audit_store_unavailable"],
                    "safety": _safety_flags(),
                },
            )

        now = _aware_utc(self._clock())
        transaction = self._store.claim_recovery(
            preview=preview,
            operator_approval_id=operator_approval_id,
            claimed_at_epoch_ms=int(now.timestamp() * 1000),
            claimed_at=now.isoformat(),
        )
        if transaction["status"] == "rejected":
            evidence = self._record_rejection(
                preview=preview,
                submitted_fingerprint=str(recovery_fingerprint or ""),
                operator_approval_id=operator_approval_id,
                rejection_reasons=["controlled_broker_cancel_recovery_claim_rejected"],
                transaction_blockers=transaction["blockers"],
                recovery=True,
            )
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation recovery claim rejected",
                evidence=evidence,
            )
        if not transaction["external_call_permitted"]:
            return {
                **_command_response(
                    transaction["command"],
                    reused=True,
                    external_call_performed=False,
                ),
                "recovery_claim_id": transaction["recovery_claim_id"],
                "recovery_query_performed": False,
                "query_only": True,
                "recancel_enabled": False,
            }

        command = transaction["command"]
        gateway, gateway_blockers = self._gateway(command["gateway_id"])
        query = getattr(gateway, "query_order", None) if not gateway_blockers else None
        external_call_performed = callable(query)
        try:
            raw_result = (
                query(command["client_order_id"])
                if callable(query)
                else {
                    "status": "gateway_unavailable_after_claim",
                    "definitive": False,
                }
            )
            raw_result = raw_result if isinstance(raw_result, dict) else {}
        except Exception as exc:
            raw_result = {
                "status": "gateway_query_exception",
                "error_type": type(exc).__name__,
                "definitive": False,
            }
        sanitized = _sanitize_query_result(raw_result)
        completed_at = _aware_utc(self._clock())
        finalized = self._store.finalize_recovery(
            recovery_claim_id=transaction["recovery_claim_id"],
            result=sanitized,
            completed_at_epoch_ms=int(completed_at.timestamp() * 1000),
            completed_at=completed_at.isoformat(),
        )
        if finalized["status"] == "rejected":
            raise ControlledBrokerCancellationRejected(
                "controlled broker cancellation recovery persistence rejected",
                evidence=finalized,
            )
        return {
            **_command_response(
                finalized["command"],
                reused=False,
                external_call_performed=False,
            ),
            "recovery_claim_id": transaction["recovery_claim_id"],
            "recovery_fingerprint": preview["recovery_fingerprint"],
            "recovery_operator_approval_id": operator_approval_id,
            "recovery_query_performed": external_call_performed,
            "query_result": sanitized,
            "query_result_authoritative": False,
            "query_only": True,
            "recancel_enabled": False,
        }

    def get_command(self, cancel_command_id: str) -> dict[str, Any]:
        row = self._store.get(cancel_command_id) if self._store is not None else None
        if row is None:
            return {
                "status": "not_found",
                "cancel_command_id": cancel_command_id,
                "default_broker_cancellation_enabled": False,
                "safety": _safety_flags(),
            }
        return _command_response(row, reused=False, external_call_performed=False)

    def list_commands(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._store.list(limit=limit) if self._store is not None else []
        return [
            _command_response(row, reused=False, external_call_performed=False)
            for row in rows
        ]

    def _gateway(self, gateway_id: str) -> tuple[Any | None, list[str]]:
        matches = [
            item
            for item in self._gateways
            if str(getattr(item, "gateway_id", "") or "") == gateway_id
        ]
        if not matches:
            return None, ["controlled_broker_cancel_gateway_not_registered"]
        if len(matches) > 1:
            return None, ["controlled_broker_cancel_gateway_id_duplicated"]
        return matches[0], []

    def _resolve_release(
        self,
        release_evidence_id: str,
        *,
        expected_gateway_id: str,
        expected_account_alias: str,
        now: datetime,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        if not callable(self._release_evidence_provider):
            raw: dict[str, Any] = {}
            blockers.append("controlled_broker_cancel_release_provider_unavailable")
        else:
            try:
                value = self._release_evidence_provider(release_evidence_id) or {}
            except Exception:
                value = {}
                blockers.append("controlled_broker_cancel_release_provider_failed")
            raw = value if isinstance(value, dict) else {}
        evidence_fingerprint = str(raw.get("evidence_fingerprint") or "")
        if raw.get("status") != "current_clear_signed_release":
            blockers.append("controlled_broker_cancel_release_not_current")
        if str(raw.get("release_evidence_id") or "") != release_evidence_id:
            blockers.append("controlled_broker_cancel_release_identity_mismatch")
        if not _FINGERPRINT_PATTERN.fullmatch(evidence_fingerprint):
            blockers.append("controlled_broker_cancel_release_fingerprint_invalid")
        if str(raw.get("gateway_id") or "") != expected_gateway_id:
            blockers.append("controlled_broker_cancel_release_gateway_mismatch")
        if str(raw.get("account_alias") or "") != expected_account_alias:
            blockers.append("controlled_broker_cancel_release_account_mismatch")
        if raw.get("operator_identity_verified") is not True:
            blockers.append("controlled_broker_cancel_release_operator_unverified")
        if raw.get("execution_mode") != "manual_each_order":
            blockers.append("controlled_broker_cancel_release_mode_invalid")
        if raw.get("automatic_execution_allowed") is not False:
            blockers.append("controlled_broker_cancel_release_automatic_mode_invalid")
        if raw.get("strategy_direct_submission_allowed") is not False:
            blockers.append("controlled_broker_cancel_release_strategy_path_invalid")
        for field in _REQUIRED_RELEASE_ASSERTIONS:
            if raw.get(field) is not True:
                blockers.append(f"controlled_broker_cancel_release_{field}_missing")
        effective_at = _parse_timestamp(raw.get("effective_at"))
        expires_at = _parse_timestamp(raw.get("expires_at"))
        if effective_at is None or expires_at is None or expires_at <= effective_at:
            blockers.append("controlled_broker_cancel_release_window_invalid")
        elif now < effective_at or now >= expires_at:
            blockers.append("controlled_broker_cancel_release_not_effective")
        return {
            "status": "clear" if not blockers else "blocked",
            "release_evidence_id": release_evidence_id,
            "evidence_fingerprint": evidence_fingerprint,
            "gateway_id": str(raw.get("gateway_id") or ""),
            "account_alias": str(raw.get("account_alias") or ""),
            "effective_at": str(raw.get("effective_at") or ""),
            "expires_at": str(raw.get("expires_at") or ""),
            "blockers": list(dict.fromkeys(blockers)),
        }

    def _record_rejection(
        self,
        *,
        preview: dict[str, Any],
        submitted_fingerprint: str,
        operator_approval_id: str,
        rejection_reasons: list[str],
        transaction_blockers: list[str],
        recovery: bool,
    ) -> dict[str, Any]:
        now = _aware_utc(self._clock())
        payload = {
            "schema_version": (
                CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION
                if recovery
                else CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION
            ),
            "status": "rejected",
            "action": "recovery_query" if recovery else "cancel",
            "submit_intent_id": str(preview.get("submit_intent_id") or ""),
            "order_id": str(preview.get("order_id") or ""),
            "cancel_command_id": str(preview.get("cancel_command_id") or ""),
            "expected_fingerprint": str(
                preview.get(
                    "recovery_fingerprint" if recovery else "cancel_fingerprint"
                )
                or ""
            ),
            "submitted_fingerprint": submitted_fingerprint,
            "operator_approval_id": str(operator_approval_id or ""),
            "review_blockers": [str(item) for item in preview.get("blockers") or []],
            "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
            "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
            "broker_cancel_performed": False,
            "broker_query_performed": False,
            "cancellation_proven": False,
            "oms_mutated": False,
            "production_ledger_mutated": False,
            "capital_authority_changed": False,
        }
        attempt_id = _fingerprint({**payload, "attempted_at": now.isoformat()})
        event_id = self._db.append_event_sync(
            event_type=(
                "controlled_broker.cancellation_recovery_rejected"
                if recovery
                else "controlled_broker.cancellation_rejected"
            ),
            timestamp=now.isoformat(),
            entity_type=(
                "controlled_broker_cancellation_recovery_rejection"
                if recovery
                else "controlled_broker_cancellation_rejection"
            ),
            entity_id=attempt_id,
            source="controlled_broker_cancellation",
            source_ref=payload["expected_fingerprint"],
            payload={"attempt_id": attempt_id, **payload},
        )
        return {
            "event_id": event_id,
            "attempt_id": attempt_id,
            "recorded_at": now.isoformat(),
            "persisted": True,
            **payload,
            "safety": _safety_flags(),
        }


def _transaction_blockers(
    conn: sqlite3.Connection,
    preview: dict[str, Any],
    *,
    require_command: dict[str, Any] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not preview:
        return ["controlled_broker_cancel_transaction_preview_missing"]
    intent = conn.execute(
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
        "gateway_id": _mapping(preview.get("identity")).get("gateway_id"),
        "broker_order_id": _mapping(preview.get("identity")).get("broker_order_id"),
        "client_order_id": _mapping(preview.get("identity")).get("client_order_id"),
    }
    for field, expected in comparisons.items():
        if str(intent[field] or "") != str(expected or ""):
            blockers.append(f"controlled_broker_cancel_transaction_{field}_changed")
    payload = _json_object(intent["payload_json"])
    account_alias = str(_mapping(preview.get("identity")).get("account_alias") or "")
    if str(payload.get("account_alias") or "") != account_alias:
        blockers.append("controlled_broker_cancel_transaction_account_alias_changed")

    order = conn.execute(
        "SELECT * FROM oms_orders WHERE order_id = ? LIMIT 1",
        (str(preview.get("order_id") or ""),),
    ).fetchone()
    if order is None:
        blockers.append("controlled_broker_cancel_transaction_order_not_found")
    else:
        order_dict = dict(order)
        if str(order["status"]) != "submitted":
            blockers.append("controlled_broker_cancel_transaction_order_not_submitted")
        if build_order_fingerprint(order_dict) != str(
            preview.get("order_fingerprint") or ""
        ):
            blockers.append("controlled_broker_cancel_transaction_order_changed")

    identity = _mapping(preview.get("identity"))
    resolution = resolve_broker_order_lifecycle_from_connection(
        conn,
        gateway_id=str(identity.get("gateway_id") or ""),
        account_alias=account_alias,
        broker_order_id=str(identity.get("broker_order_id") or ""),
        client_order_id=str(identity.get("client_order_id") or ""),
    )
    if str(resolution.get("status") or "") != "found":
        blockers.append("controlled_broker_cancel_transaction_lifecycle_unavailable")
        blockers.extend(str(item) for item in resolution.get("blockers") or [])
    collector = _mapping(resolution.get("collector_evidence"))
    if bool(collector.get("required")) and str(collector.get("status") or "") != (
        "healthy"
    ):
        blockers.append("controlled_broker_cancel_transaction_collector_unhealthy")
    observation = _mapping(resolution.get("observation"))
    expected_lifecycle = _mapping(preview.get("lifecycle_evidence"))
    for field, expected in (
        ("observation_id", expected_lifecycle.get("observation_id")),
        ("evidence_fingerprint", expected_lifecycle.get("evidence_fingerprint")),
        ("source_sequence", expected_lifecycle.get("source_sequence")),
    ):
        if str(observation.get(field) or "") != str(expected or ""):
            blockers.append(
                f"controlled_broker_cancel_transaction_lifecycle_{field}_changed"
            )
    lifecycle_order = _mapping(resolution.get("order"))
    if str(lifecycle_order.get("status") or "") not in (
        _CANCELLABLE_LIFECYCLE_STATUSES
    ):
        blockers.append(
            "controlled_broker_cancel_transaction_lifecycle_not_cancellable"
        )
    expected_order = _mapping(preview.get("order"))
    for field in (
        "symbol",
        "side",
        "order_quantity",
        "filled_quantity",
        "cancelled_quantity",
        "remaining_quantity",
    ):
        actual_value = (
            _remaining_quantity(lifecycle_order)
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
            if _decimal(actual_value) != _decimal(expected_order.get(field)):
                blockers.append(
                    f"controlled_broker_cancel_transaction_lifecycle_{field}_changed"
                )
        elif str(actual_value or "") != str(expected_order.get(field) or ""):
            blockers.append(
                f"controlled_broker_cancel_transaction_lifecycle_{field}_changed"
            )
    if _decimal(_remaining_quantity(lifecycle_order)) <= 0:
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
                _mapping(preview.get("identity")).get(field)
                if field
                in {"gateway_id", "account_alias", "broker_order_id", "client_order_id"}
                else preview.get(field)
            )
            if str(require_command.get(field) or "") != str(source_value or ""):
                blockers.append(
                    f"controlled_broker_cancel_recovery_command_{field}_changed"
                )
    return list(dict.fromkeys(blockers))


def _cancel_capabilities(gateway: Any | None) -> tuple[dict[str, bool], list[str]]:
    raw = getattr(gateway, "capabilities", {}) if gateway is not None else {}
    values = {
        field: bool(
            raw.get(field) if isinstance(raw, dict) else getattr(raw, field, False)
        )
        for field in (
            "can_cancel_orders",
            "can_query_orders",
            "supports_idempotent_client_order_id",
        )
    }
    blockers = [
        f"controlled_broker_cancel_capability_missing:{field}"
        for field, value in values.items()
        if not value
    ]
    if gateway is not None and not callable(getattr(gateway, "cancel_order", None)):
        blockers.append("controlled_broker_cancel_method_missing")
    if gateway is not None and not callable(getattr(gateway, "query_order", None)):
        blockers.append("controlled_broker_cancel_query_method_missing")
    return values, blockers


def _gateway_health(
    gateway: Any | None,
    *,
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    getter = getattr(gateway, "get_health", None)
    if not callable(getter):
        return _missing_health(), ["controlled_broker_cancel_health_unavailable"]
    try:
        value = getter() or {}
    except Exception:
        return _missing_health(), ["controlled_broker_cancel_health_failed"]
    raw = value if isinstance(value, dict) else {}
    captured_at = _parse_timestamp(raw.get("captured_at"))
    source_fingerprint = str(raw.get("source_fingerprint") or "")
    blockers: list[str] = []
    if raw.get("status") != "healthy":
        blockers.append("controlled_broker_cancel_gateway_unhealthy")
    if captured_at is None:
        blockers.append("controlled_broker_cancel_health_timestamp_invalid")
        age_seconds = None
    else:
        age = (now - captured_at).total_seconds()
        age_seconds = int(max(0, age))
        if age < -30:
            blockers.append("controlled_broker_cancel_health_timestamp_future")
        elif age > CONTROLLED_BROKER_CANCELLATION_GATEWAY_HEALTH_MAX_AGE_SECONDS:
            blockers.append("controlled_broker_cancel_health_stale")
    if not _FINGERPRINT_PATTERN.fullmatch(source_fingerprint):
        blockers.append("controlled_broker_cancel_health_fingerprint_invalid")
    return {
        "status": str(raw.get("status") or "missing"),
        "captured_at": captured_at.isoformat() if captured_at else "",
        "source_fingerprint": source_fingerprint,
        "age_seconds": age_seconds,
    }, list(dict.fromkeys(blockers))


def _classify_cancel_result(
    result: dict[str, Any],
    *,
    expected: dict[str, Any],
) -> str:
    identity = _mapping(expected.get("identity"))
    exact = (
        str(result.get("client_order_id") or "")
        == str(identity.get("client_order_id") or "")
        and str(result.get("broker_order_id") or "")
        == str(identity.get("broker_order_id") or "")
        and str(result.get("cancel_command_id") or "")
        == str(expected.get("cancel_command_id") or "")
        and str(result.get("command_fingerprint") or "")
        == str(expected.get("cancel_fingerprint") or "")
    )
    status = str(result.get("status") or "")
    if exact and status in {
        "accepted",
        "requested",
        "cancel_pending",
        "cancelled",
        "partial_cancelled",
        "reused",
    }:
        return "cancel_requested"
    if (
        exact
        and result.get("definitive") is True
        and status
        in {
            "rejected",
            "blocked",
            "not_found",
        }
    ):
        return "cancel_rejected"
    return "cancellation_unknown"


def _sanitize_cancel_result(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "")
    return {
        "status": status if status in _CANCEL_RESULT_STATUSES else "unknown",
        "client_order_id": str(raw.get("client_order_id") or ""),
        "broker_order_id": str(raw.get("broker_order_id") or ""),
        "cancel_command_id": str(raw.get("cancel_command_id") or ""),
        "command_fingerprint": str(raw.get("command_fingerprint") or ""),
        "filled_quantity": _decimal_string(raw.get("filled_quantity")),
        "cancelled_quantity": _decimal_string(raw.get("cancelled_quantity")),
        "definitive": raw.get("definitive") is True,
        "error_type": str(raw.get("error_type") or "")[:128],
        "reason": str(raw.get("reason") or "")[:256],
    }


def _sanitize_query_result(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "")
    return {
        "status": status if status in _QUERY_RESULT_STATUSES else "unknown",
        "client_order_id": str(raw.get("client_order_id") or ""),
        "broker_order_id": str(raw.get("broker_order_id") or ""),
        "order_fingerprint": str(raw.get("order_fingerprint") or ""),
        "filled_quantity": _decimal_string(raw.get("filled_quantity")),
        "cancelled_quantity": _decimal_string(raw.get("cancelled_quantity")),
        "definitive": raw.get("definitive") is True,
        "error_type": str(raw.get("error_type") or "")[:128],
        "reason": str(raw.get("reason") or "")[:256],
    }


def _command_response(
    row: dict[str, Any],
    *,
    reused: bool,
    external_call_performed: bool,
) -> dict[str, Any]:
    result = _mapping(row.get("result"))
    return {
        "schema_version": CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
        "status": str(row.get("status") or "unknown"),
        "cancel_command_id": str(row.get("cancel_command_id") or ""),
        "cancel_fingerprint": str(row.get("cancel_fingerprint") or ""),
        "submit_intent_id": str(row.get("submit_intent_id") or ""),
        "submit_fingerprint": str(row.get("submit_fingerprint") or ""),
        "ticket_fingerprint": str(row.get("ticket_fingerprint") or ""),
        "order_id": str(row.get("order_id") or ""),
        "order_fingerprint": str(row.get("order_fingerprint") or ""),
        "provider": str(row.get("provider") or ""),
        "gateway_id": str(row.get("gateway_id") or ""),
        "account_alias": str(row.get("account_alias") or ""),
        "broker_order_id": str(row.get("broker_order_id") or ""),
        "client_order_id": str(row.get("client_order_id") or ""),
        "release_evidence_id": str(row.get("release_evidence_id") or ""),
        "release_evidence_fingerprint": str(
            row.get("release_evidence_fingerprint") or ""
        ),
        "lifecycle_observation_id": str(row.get("lifecycle_observation_id") or ""),
        "lifecycle_evidence_fingerprint": str(
            row.get("lifecycle_evidence_fingerprint") or ""
        ),
        "lifecycle_source_sequence": int(row.get("lifecycle_source_sequence") or 0),
        "operator_id": str(row.get("operator_id") or ""),
        "operator_approval_id": str(row.get("operator_approval_id") or ""),
        "prepared_at": str(row.get("prepared_at") or ""),
        "finalized_at": str(row.get("finalized_at") or ""),
        "last_query_at": str(row.get("last_query_at") or ""),
        "query_count": int(row.get("query_count") or 0),
        "result": result,
        "last_query_result": _mapping(row.get("last_query_result")),
        "reused": reused,
        "external_call_performed": external_call_performed,
        "broker_cancel_request_sent": bool(
            external_call_performed
            and str(row.get("status") or "")
            in {"cancel_requested", "cancel_rejected", "cancellation_unknown"}
        ),
        "cancellation_proven": False,
        "canonical_lifecycle_mutated": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "risk_state_mutated": False,
        "kill_switch_mutated": False,
        "capital_authority_changed": False,
        "automatic_cancellation_enabled": False,
        "strategy_direct_cancellation_enabled": False,
        "ai_direct_cancellation_enabled": False,
        "cancellation_retry_enabled": False,
        "safety": _safety_flags(),
    }


def _command_row(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    result["payload"] = _json_object(result.get("payload_json"))
    result["result"] = _json_object(result.get("result_json"))
    result["last_query_result"] = _json_object(result.get("last_query_result_json"))
    return result


def _store_rejection(blockers: list[str]) -> dict[str, Any]:
    return {
        "status": "rejected",
        "reused": False,
        "external_call_permitted": False,
        "command": {},
        "blockers": list(dict.fromkeys(str(item) for item in blockers)),
    }


def _remaining_quantity(order: dict[str, Any]) -> Decimal:
    return (
        abs(_decimal(order.get("order_quantity")))
        - abs(_decimal(order.get("cumulative_filled_quantity")))
        - abs(_decimal(order.get("cancelled_quantity")))
    )


def _missing_health() -> dict[str, Any]:
    return {
        "status": "missing",
        "captured_at": "",
        "source_fingerprint": "",
        "age_seconds": None,
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "reads_persisted_financial_facts_only": True,
        "preview_contacts_provider": False,
        "default_broker_cancellation_enabled": False,
        "automatic_cancellation_enabled": False,
        "strategy_direct_cancellation_enabled": False,
        "ai_direct_cancellation_enabled": False,
        "cancellation_retry_enabled": False,
        "query_only_recovery": True,
        "cancellation_proven": False,
        "canonical_lifecycle_mutated": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "risk_state_mutated": False,
        "kill_switch_mutated": False,
        "capital_authority_changed": False,
        "releases_submission_interlock": False,
    }


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value if value not in {None, ""} else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")


def _decimal_string(value: Any) -> str:
    parsed = _decimal(value)
    text = format(parsed, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
