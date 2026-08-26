"""Atomic unit of work for operator-authored canonical-ledger mutations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.idempotency import IdempotencyConflict
from server.contracts.ledger_mutations import (
    LedgerAppendCommand,
    LedgerMutationConflict,
    LedgerMutationResult,
    LedgerTradeSettlementCommand,
    ledger_entry_state_fingerprint,
    validate_trade_settlement_economics,
)
from server.persistence.database_normalization import json_dict
from server.persistence.database_serialization import normalize_timestamp
from server.persistence.event_log import insert_event_sync
from server.persistence.valuation_transaction import ValuationTransactionWriter

FailureInjector = Callable[[str], None]
LedgerEntryInserter = Callable[..., int]


class LedgerMutationUnitOfWork:
    """Claim, mutate, audit, value, and publish on one SQLite transaction."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        now: Callable[[], str],
        ledger_entry_inserter: LedgerEntryInserter,
        valuation_transaction_writer: ValuationTransactionWriter,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._now = now
        self._ledger_entry_inserter = ledger_entry_inserter
        self._valuation_transaction_writer = valuation_transaction_writer
        self._failure_injector = failure_injector

    def append(self, command: LedgerAppendCommand) -> LedgerMutationResult:
        """Append one fact or replay the exact previously committed request."""

        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = self._replay_if_committed(
                    conn,
                    request_id=command.request_id,
                    operator_id=command.operator_id,
                    mutation_kind="append",
                    request_fingerprint=command.fingerprint,
                )
                if replay is not None:
                    conn.rollback()
                    return replay
                self._assert_source_identity_available(conn, command)
                created_at = command.entry.created_at or self._now()
                self._insert_claim(
                    conn,
                    request_id=command.request_id,
                    operator_id=command.operator_id,
                    mutation_kind="append",
                    request_fingerprint=command.fingerprint,
                    request_json=canonical_json(command.to_dict()),
                    created_at=created_at,
                )
                self._inject("after_claim")
                entry_values = command.entry.to_dict()
                entry_values["created_at"] = created_at
                entry_id = self._ledger_entry_inserter(
                    conn,
                    **entry_values,
                )
                self._inject("after_ledger_entry")
                entry = _load_ledger_entry(conn, entry_id)
                if entry is None:
                    raise RuntimeError("appended ledger entry could not be reloaded")
                insert_event_sync(
                    conn,
                    event_type="portfolio.ledger_mutation.accepted",
                    timestamp=str(entry["timestamp"]),
                    entity_type="ledger_entry",
                    entity_id=str(entry_id),
                    source="ledger_mutation_uow",
                    source_ref=command.request_id,
                    payload={
                        "operator_id": command.operator_id,
                        "request_id": command.request_id,
                        "request_fingerprint": command.fingerprint,
                        "entry_id": entry_id,
                        "entry_fingerprint": ledger_entry_state_fingerprint(entry),
                        "mutation_kind": "append",
                    },
                )
                self._inject("after_audit_event")
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=_load_all_ledger_entries(conn),
                )
                self._inject("after_valuation")
                result = _mutation_result(
                    command=command,
                    entry=entry,
                    valuation=valuation,
                )
                self._complete_claim(conn, result, completed_at=self._now())
                self._inject("before_commit")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result

    def settle(self, command: LedgerTradeSettlementCommand) -> LedgerMutationResult:
        """Confirm one trade settlement with request idempotency and state CAS."""

        normalized_settled_at = normalize_timestamp(command.settled_at)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = self._replay_if_committed(
                    conn,
                    request_id=command.request_id,
                    operator_id=command.operator_id,
                    mutation_kind="trade_settlement",
                    request_fingerprint=command.fingerprint,
                )
                if replay is not None:
                    conn.rollback()
                    return replay
                current = _load_ledger_entry(conn, command.entry_id)
                if current is None:
                    raise KeyError(f"ledger entry not found: {command.entry_id}")
                if str(current.get("entry_type") or "") not in {
                    "trade_buy",
                    "trade_sell",
                }:
                    raise LedgerMutationConflict(
                        "only trade ledger entries can be settled"
                    )
                if current.get("settlement_status") not in {None, ""}:
                    raise LedgerMutationConflict(
                        "trade settlement is already confirmed under another request"
                    )
                if (
                    ledger_entry_state_fingerprint(current)
                    != command.expected_entry_fingerprint
                ):
                    raise LedgerMutationConflict(
                        "ledger entry changed after review; refresh before settlement"
                    )
                validate_trade_settlement_economics(command, current)
                evidence_owner = conn.execute(
                    """
                    SELECT id FROM ledger_entries
                    WHERE settlement_source = ? AND settlement_source_ref = ?
                      AND id != ?
                    LIMIT 1
                    """,
                    (
                        command.settlement_source,
                        command.settlement_source_ref,
                        command.entry_id,
                    ),
                ).fetchone()
                if evidence_owner is not None:
                    raise LedgerMutationConflict(
                        "settlement evidence reference already confirms another entry"
                    )
                self._insert_claim(
                    conn,
                    request_id=command.request_id,
                    operator_id=command.operator_id,
                    mutation_kind="trade_settlement",
                    request_fingerprint=command.fingerprint,
                    request_json=canonical_json(command.to_dict()),
                    created_at=self._now(),
                )
                self._inject("after_claim")
                estimates = _estimated_trade_costs(current)
                cursor = conn.execute(
                    """
                    UPDATE ledger_entries
                    SET commission = ?, net_cash_impact = ?, fee_breakdown_json = ?,
                        fee_rule_id = ?, fee_rule_version = ?,
                        estimated_commission = ?, estimated_net_cash_impact = ?,
                        estimated_fee_breakdown_json = ?, estimated_fee_rule_id = ?,
                        estimated_fee_rule_version = ?, settlement_status = 'confirmed',
                        settled_at = ?, settlement_source = ?, settlement_source_ref = ?,
                        settlement_note = ?
                    WHERE id = ?
                      AND (settlement_status IS NULL OR settlement_status = '')
                    """,
                    (
                        command.commission,
                        command.net_cash_impact,
                        command.fee_breakdown_json,
                        command.fee_rule_id,
                        command.fee_rule_version,
                        estimates["commission"],
                        estimates["net_cash_impact"],
                        estimates["fee_breakdown_json"],
                        estimates["fee_rule_id"],
                        estimates["fee_rule_version"],
                        normalized_settled_at,
                        command.settlement_source,
                        command.settlement_source_ref,
                        command.settlement_note,
                        command.entry_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise LedgerMutationConflict(
                        "ledger entry changed while settlement was being committed"
                    )
                self._inject("after_ledger_cas")
                updated = _load_ledger_entry(conn, command.entry_id)
                if updated is None:
                    raise RuntimeError("settled ledger entry could not be reloaded")
                insert_event_sync(
                    conn,
                    event_type="portfolio.trade_settlement.confirmed",
                    timestamp=normalized_settled_at,
                    entity_type="ledger_entry",
                    entity_id=str(command.entry_id),
                    source=command.settlement_source,
                    source_ref=command.settlement_source_ref,
                    payload=_settlement_event_payload(
                        command=command,
                        current=current,
                        estimates=estimates,
                        updated=updated,
                    ),
                )
                self._inject("after_audit_event")
                valuation = self._valuation_transaction_writer(
                    conn,
                    candidate_ledger_rows=_load_all_ledger_entries(conn),
                )
                self._inject("after_valuation")
                result = _mutation_result(
                    command=command,
                    entry=updated,
                    valuation=valuation,
                )
                self._complete_claim(conn, result, completed_at=self._now())
                self._inject("before_commit")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result

    def load_claim_request(self, request_id: str) -> dict[str, Any] | None:
        """Read and verify one committed request for a legacy typed adapter."""

        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json, request_fingerprint FROM ledger_mutation_claims "
                "WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["request_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("stored ledger mutation request is invalid")
        if content_fingerprint(payload) != str(row["request_fingerprint"]):
            raise RuntimeError("stored ledger mutation request fingerprint mismatch")
        return payload

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._database_path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        return conn

    def _replay_if_committed(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        operator_id: str,
        mutation_kind: str,
        request_fingerprint: str,
    ) -> LedgerMutationResult | None:
        row = conn.execute(
            "SELECT * FROM ledger_mutation_claims WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            str(row["operator_id"]) != operator_id
            or str(row["mutation_kind"]) != mutation_kind
            or str(row["request_fingerprint"]) != request_fingerprint
        ):
            raise IdempotencyConflict(
                "ledger request_id was reused with different immutable input "
                "or another ledger entry"
            )
        result_json = row["result_json"]
        result_fingerprint = row["result_fingerprint"]
        if not result_json or not result_fingerprint:
            raise RuntimeError("ledger mutation claim is not terminal")
        payload = json.loads(str(result_json))
        if not isinstance(payload, dict):
            raise RuntimeError("stored ledger mutation result is invalid")
        if content_fingerprint(payload) != str(result_fingerprint):
            raise RuntimeError("stored ledger mutation result fingerprint mismatch")
        result = LedgerMutationResult.from_dict(payload, replayed=True)
        if ledger_entry_state_fingerprint(result.entry) != result.entry_fingerprint:
            raise RuntimeError("stored ledger mutation entry fingerprint mismatch")
        if mutation_kind == "trade_settlement":
            current = _load_ledger_entry(conn, int(result.entry["id"]))
            if (
                current is None
                or ledger_entry_state_fingerprint(current) != result.entry_fingerprint
            ):
                raise RuntimeError("settled ledger entry diverged after commit")
        return result

    def _assert_source_identity_available(
        self, conn: sqlite3.Connection, command: LedgerAppendCommand
    ) -> None:
        if not command.entry.source_ref:
            return
        existing = conn.execute(
            "SELECT id FROM ledger_entries WHERE source = ? AND source_ref = ?",
            (command.entry.source, command.entry.source_ref),
        ).fetchone()
        if existing is not None:
            raise LedgerMutationConflict(
                "ledger source reference is already owned by another request"
            )

    def _insert_claim(
        self,
        conn: sqlite3.Connection,
        *,
        request_id: str,
        operator_id: str,
        mutation_kind: str,
        request_fingerprint: str,
        request_json: str,
        created_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO ledger_mutation_claims (
                request_id, operator_id, mutation_kind, request_fingerprint,
                request_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                operator_id,
                mutation_kind,
                request_fingerprint,
                request_json,
                created_at,
            ),
        )

    def _complete_claim(
        self,
        conn: sqlite3.Connection,
        result: LedgerMutationResult,
        *,
        completed_at: str,
    ) -> None:
        payload = result.to_dict()
        cursor = conn.execute(
            """
            UPDATE ledger_mutation_claims
            SET ledger_entry_id = ?, result_json = ?, result_fingerprint = ?,
                completed_at = ?
            WHERE request_id = ? AND request_fingerprint = ?
              AND result_json IS NULL
            """,
            (
                int(result.entry["id"]),
                canonical_json(payload),
                content_fingerprint(payload),
                completed_at,
                result.request_id,
                result.request_fingerprint,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("ledger mutation claim could not be completed")

    def _inject(self, stage: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(stage)


def _load_ledger_entry(
    conn: sqlite3.Connection, entry_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM ledger_entries WHERE id = ? LIMIT 1",
        (entry_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _load_all_ledger_entries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM ledger_entries ORDER BY timestamp ASC, id ASC"
        ).fetchall()
    ]


def _estimated_trade_costs(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "commission": (
            current.get("estimated_commission")
            if current.get("estimated_commission") is not None
            else current.get("commission")
        ),
        "net_cash_impact": (
            current.get("estimated_net_cash_impact")
            if current.get("estimated_net_cash_impact") is not None
            else current.get("net_cash_impact")
        ),
        "fee_breakdown_json": (
            current.get("estimated_fee_breakdown_json")
            if current.get("estimated_fee_breakdown_json") is not None
            else current.get("fee_breakdown_json")
        ),
        "fee_rule_id": (
            current.get("estimated_fee_rule_id")
            if current.get("estimated_fee_rule_id") is not None
            else current.get("fee_rule_id")
        ),
        "fee_rule_version": (
            current.get("estimated_fee_rule_version")
            if current.get("estimated_fee_rule_version") is not None
            else current.get("fee_rule_version")
        ),
    }


def _settlement_event_payload(
    *,
    command: LedgerTradeSettlementCommand,
    current: dict[str, Any],
    estimates: dict[str, Any],
    updated: dict[str, Any],
) -> dict[str, Any]:
    estimated_net = estimates["net_cash_impact"]
    return {
        "entry_id": command.entry_id,
        "symbol": current.get("symbol"),
        "direction": current.get("direction"),
        "operator_id": command.operator_id,
        "request_id": command.request_id,
        "request_fingerprint": command.fingerprint,
        "expected_entry_fingerprint": command.expected_entry_fingerprint,
        "settled_entry_fingerprint": ledger_entry_state_fingerprint(updated),
        "estimated": {
            "commission": estimates["commission"],
            "net_cash_impact": estimated_net,
            "fee_breakdown": json_dict(estimates["fee_breakdown_json"]),
            "fee_rule_id": estimates["fee_rule_id"],
            "fee_rule_version": estimates["fee_rule_version"],
        },
        "settled": {
            "commission": command.commission,
            "net_cash_impact": command.net_cash_impact,
            "fee_breakdown": json_dict(command.fee_breakdown_json),
            "fee_rule_id": command.fee_rule_id,
            "fee_rule_version": command.fee_rule_version,
        },
        "cash_adjustment": (
            None
            if estimated_net is None
            else float(
                Decimal(str(command.net_cash_impact)) - Decimal(str(estimated_net))
            )
        ),
        "settlement_note": command.settlement_note,
    }


def _mutation_result(
    *,
    command: LedgerAppendCommand | LedgerTradeSettlementCommand,
    entry: dict[str, Any],
    valuation: dict[str, Any],
) -> LedgerMutationResult:
    snapshot_id = str(valuation.get("snapshot_id") or "").strip()
    snapshot_status = str(valuation.get("status") or "").strip()
    if not snapshot_id or not snapshot_status:
        raise RuntimeError("valuation publication returned no terminal identity")
    return LedgerMutationResult(
        request_id=command.request_id,
        operator_id=command.operator_id,
        request_fingerprint=command.fingerprint,
        entry=dict(entry),
        entry_fingerprint=ledger_entry_state_fingerprint(entry),
        valuation_snapshot_id=snapshot_id,
        valuation_snapshot_status=snapshot_status,
    )


__all__ = ["LedgerMutationUnitOfWork"]
