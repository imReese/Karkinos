"""Exact idempotency claims for operator-authored portfolio mutations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from typing import Any

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.portfolio_mutations import PortfolioMutationConflict


def claim_portfolio_mutation(
    conn: sqlite3.Connection,
    *,
    command: object,
    mutation_kind: str,
    created_at: str,
) -> dict[str, Any] | None:
    """Claim a command or return its integrity-checked committed result."""

    payload = _command_payload(command)
    command_id = _required_identity(payload, "command_id")
    operator_id = _required_identity(payload, "operator_id")
    request_json = canonical_json(payload)
    request_fingerprint = content_fingerprint(payload)
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT * FROM portfolio_mutation_claims WHERE command_id = ?",
        (command_id,),
    ).fetchone()
    if existing is not None:
        row = dict(existing)
        if (
            str(row.get("operator_id") or "") != operator_id
            or str(row.get("mutation_kind") or "") != mutation_kind
            or str(row.get("request_json") or "") != request_json
            or str(row.get("request_fingerprint") or "") != request_fingerprint
        ):
            raise PortfolioMutationConflict(
                "portfolio command_id already belongs to a different request"
            )
        result_json = row.get("result_json")
        result_fingerprint = str(row.get("result_fingerprint") or "")
        if not result_json or not row.get("completed_at"):
            raise RuntimeError("portfolio mutation claim is incomplete")
        try:
            result = json.loads(str(result_json))
        except json.JSONDecodeError:
            raise RuntimeError("portfolio mutation claim result is invalid") from None
        if (
            not isinstance(result, dict)
            or content_fingerprint(result) != result_fingerprint
        ):
            raise RuntimeError("portfolio mutation claim result is invalid")
        return result

    conn.execute(
        """
        INSERT INTO portfolio_mutation_claims (
            command_id, operator_id, mutation_kind, request_fingerprint,
            request_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            command_id,
            operator_id,
            mutation_kind,
            request_fingerprint,
            request_json,
            created_at,
        ),
    )
    return None


def complete_portfolio_mutation(
    conn: sqlite3.Connection,
    *,
    command_id: str,
    result: dict[str, Any],
    completed_at: str,
) -> None:
    """Persist the immutable result before the caller commits its transaction."""

    result_json = canonical_json(result)
    cursor = conn.execute(
        """
        UPDATE portfolio_mutation_claims
        SET result_json = ?, result_fingerprint = ?, completed_at = ?
        WHERE command_id = ? AND result_json IS NULL
        """,
        (
            result_json,
            content_fingerprint(result),
            completed_at,
            command_id,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("portfolio mutation claim completion lost serialization")


def validate_portfolio_mutation_valuation(
    conn: sqlite3.Connection,
    result: dict[str, Any],
) -> None:
    """Fail closed when a replay's immutable valuation identity disappeared."""

    snapshot_id = str(result.get("valuation_snapshot_id") or "")
    snapshot_status = str(result.get("valuation_snapshot_status") or "")
    if not snapshot_id or not snapshot_status:
        raise RuntimeError("portfolio mutation valuation result is invalid")
    row = conn.execute(
        "SELECT status FROM valuation_snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None or str(row[0]) != snapshot_status:
        raise RuntimeError("portfolio mutation valuation result drifted")


def _command_payload(command: object) -> dict[str, Any]:
    if not is_dataclass(command):
        raise TypeError("portfolio mutation command must be a dataclass")
    payload = asdict(command)
    if not isinstance(payload, dict):
        raise TypeError("portfolio mutation command payload is invalid")
    return payload


def _required_identity(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required")
    return value


__all__ = [
    "PortfolioMutationConflict",
    "claim_portfolio_mutation",
    "complete_portfolio_mutation",
    "validate_portfolio_mutation_valuation",
]
