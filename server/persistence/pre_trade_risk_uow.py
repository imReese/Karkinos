"""Atomic final evidence validation and persistence for pre-trade risk batches."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from core.types import InstrumentKey
from server.persistence.connection import DateTimeNow
from server.persistence.event_log import insert_event_sync
from server.persistence.quote_current_materialization import (
    assert_quote_current_materialization_on_connection,
)

_ACTION_COLUMNS = (
    "id",
    "source_signal_id",
    "symbol",
    "title",
    "detail",
    "direction",
    "urgency",
    "target_weight",
    "price",
    "strategy_id",
    "timestamp",
    "asset_class",
    "status",
    "created_at",
    "updated_at",
)
_ACTION_SELECT = ", ".join(_ACTION_COLUMNS)


class PreTradeRiskUnitOfWork:
    """Own the lock, final revalidation, and all writes for one risk batch."""

    def __init__(self, database_path: str | Path, *, now: DateTimeNow) -> None:
        self._path = Path(database_path)
        self._now = now

    def capture_guard_sync(
        self,
        *,
        tasks: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Capture the persisted identities that a later write must revalidate."""

        blockers: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                materialization = assert_quote_current_materialization_on_connection(
                    conn
                )
            except RuntimeError as exc:
                blockers.append(
                    {
                        "code": "quote_current_materialization_unavailable",
                        "reason": str(exc),
                    }
                )
                quote_revision: int | None = None
            else:
                quote_revision = materialization.revision

            valuation = _published_valuation_identity(conn, blockers=blockers)
            for task in tasks:
                binding = _capture_action_binding(conn, task, blockers=blockers)
                if binding is not None:
                    bindings.append(binding)

        return {
            "status": "ready" if not blockers else "blocked",
            "quote_current_revision": quote_revision,
            "valuation_snapshot_id": valuation.get("valuation_snapshot_id"),
            "ledger_cutoff_id": valuation.get("ledger_cutoff_id"),
            "valuation_status": valuation.get("valuation_status"),
            "action_task_bindings": bindings,
            "blockers": blockers,
        }

    def commit_batch_sync(
        self,
        *,
        writes: Sequence[tuple[Any, Any]],
        evidence_binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Revalidate all evidence before the first insert, then commit atomically."""

        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            conn.execute("BEGIN IMMEDIATE")
            blockers = _final_validation_blockers(
                conn,
                writes=writes,
                evidence_binding=evidence_binding,
            )
            if blockers:
                conn.rollback()
                return {
                    "status": "blocked",
                    "write_count": 0,
                    "event_count": 0,
                    "blockers": blockers,
                }

            row_ids: list[int] = []
            created_at = self._now().isoformat()
            try:
                for intent, decision in writes:
                    row_ids.append(
                        _insert_risk_decision(
                            conn,
                            intent=intent,
                            decision=decision,
                            created_at=created_at,
                        )
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "status": "committed",
            "write_count": len(row_ids),
            "event_count": len(row_ids),
            "risk_decision_row_ids": row_ids,
            "blockers": [],
        }


def _capture_action_binding(
    conn: sqlite3.Connection,
    task: Mapping[str, Any],
    *,
    blockers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    action_id = _positive_int(task.get("id"))
    if action_id is None:
        blockers.append({"code": "action_task_identity_missing"})
        return None
    row = conn.execute(
        f"SELECT {_ACTION_SELECT} FROM action_tasks WHERE id = ? LIMIT 1",
        (action_id,),
    ).fetchone()
    if row is None:
        blockers.append({"code": "action_task_missing", "action_id": action_id})
        return None
    expected = _action_identity(task)
    current = _action_identity(dict(row))
    if _fingerprint(expected) != _fingerprint(current):
        blockers.append({"code": "action_task_identity_drift", "action_id": action_id})
        return None
    return {
        "action_id": action_id,
        "source_signal_id": int(row["source_signal_id"]),
        "fingerprint": _fingerprint(current),
        "risk_gate_status": str(task.get("risk_gate_status") or "not_checked"),
    }


def _final_validation_blockers(
    conn: sqlite3.Connection,
    *,
    writes: Sequence[tuple[Any, Any]],
    evidence_binding: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    _validate_decision_identities(conn, writes=writes, blockers=blockers)
    _validate_actions(
        conn,
        bindings=evidence_binding.get("action_task_bindings"),
        writes=writes,
        blockers=blockers,
    )
    _validate_valuation(conn, evidence_binding=evidence_binding, blockers=blockers)
    _validate_quote_revision(
        conn,
        expected=evidence_binding.get("quote_current_revision"),
        blockers=blockers,
    )
    _validate_candidate_quotes(
        conn,
        bindings=evidence_binding.get("candidate_quote_bindings"),
        writes=writes,
        blockers=blockers,
    )
    return blockers


def _validate_decision_identities(
    conn: sqlite3.Connection,
    *,
    writes: Sequence[tuple[Any, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    decision_ids = [str(decision.decision_id or "").strip() for _, decision in writes]
    intent_ids = [str(intent.intent_id or "").strip() for intent, _ in writes]
    if not decision_ids or any(not value for value in decision_ids + intent_ids):
        blockers.append({"code": "risk_decision_identity_missing"})
        return
    if len(set(decision_ids)) != len(decision_ids) or len(set(intent_ids)) != len(
        intent_ids
    ):
        blockers.append({"code": "risk_decision_identity_duplicate"})
        return
    for decision_id, intent_id in zip(decision_ids, intent_ids, strict=True):
        row = conn.execute(
            """
            SELECT decision_id, intent_id FROM risk_decisions
            WHERE decision_id = ? OR intent_id = ?
            LIMIT 1
            """,
            (decision_id, intent_id),
        ).fetchone()
        if row is not None:
            blockers.append(
                {
                    "code": "risk_decision_identity_conflict",
                    "decision_id": decision_id,
                    "intent_id": intent_id,
                }
            )


def _validate_actions(
    conn: sqlite3.Connection,
    *,
    bindings: Any,
    writes: Sequence[tuple[Any, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    if not isinstance(bindings, list):
        blockers.append({"code": "action_task_bindings_missing"})
        return
    by_id: dict[int, Mapping[str, Any]] = {}
    for item in bindings:
        if not isinstance(item, Mapping):
            continue
        action_id = _positive_int(item.get("action_id"))
        if action_id is not None:
            by_id[action_id] = item
    writes_by_action: dict[int, tuple[Any, Any]] = {}
    raw_required_ids: set[int | None] = set()
    for intent, decision in writes:
        action_id = _positive_int(getattr(intent, "metadata", {}).get("action_id"))
        raw_required_ids.add(action_id)
        if action_id is not None:
            if action_id in writes_by_action:
                blockers.append(
                    {
                        "code": "risk_batch_action_identity_duplicate",
                        "action_id": action_id,
                    }
                )
            writes_by_action[action_id] = (intent, decision)
    if None in raw_required_ids or not raw_required_ids:
        blockers.append({"code": "risk_batch_action_identity_missing"})
        return
    required_ids = {
        action_id for action_id in raw_required_ids if action_id is not None
    }
    if not required_ids.issubset(by_id):
        blockers.append({"code": "risk_batch_action_binding_incomplete"})
        return

    existing_risk_signal_ids = _risk_decision_source_signal_ids(conn)
    for action_id in sorted(required_ids):
        binding = by_id[action_id]
        row = conn.execute(
            f"SELECT {_ACTION_SELECT} FROM action_tasks WHERE id = ? LIMIT 1",
            (action_id,),
        ).fetchone()
        if row is None:
            blockers.append({"code": "action_task_missing", "action_id": action_id})
            continue
        if _fingerprint(_action_identity(dict(row))) != str(
            binding.get("fingerprint") or ""
        ):
            blockers.append(
                {"code": "action_task_identity_drift", "action_id": action_id}
            )
            continue
        intent, decision = writes_by_action[action_id]
        if not _intent_matches_action(intent, decision, row):
            blockers.append(
                {"code": "risk_batch_action_intent_drift", "action_id": action_id}
            )
            continue
        if int(row["source_signal_id"]) in existing_risk_signal_ids:
            blockers.append(
                {"code": "action_task_risk_gate_drift", "action_id": action_id}
            )


def _validate_valuation(
    conn: sqlite3.Connection,
    *,
    evidence_binding: Mapping[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    expected_snapshot_id = str(
        evidence_binding.get("valuation_snapshot_id") or ""
    ).strip()
    expected_cutoff = _positive_int(evidence_binding.get("ledger_cutoff_id"))
    expected_status = str(evidence_binding.get("valuation_status") or "").lower()
    if (
        not expected_snapshot_id
        or expected_cutoff is None
        or expected_status != "complete"
    ):
        blockers.append({"code": "valuation_publication_binding_missing"})
        return
    current_blockers: list[dict[str, Any]] = []
    current = _published_valuation_identity(conn, blockers=current_blockers)
    if current_blockers:
        blockers.extend(current_blockers)
        return
    if current.get("valuation_snapshot_id") != expected_snapshot_id:
        blockers.append({"code": "valuation_publication_snapshot_drift"})
    if current.get("ledger_cutoff_id") != expected_cutoff:
        blockers.append({"code": "valuation_publication_ledger_cutoff_drift"})
    if current.get("valuation_status") != expected_status:
        blockers.append({"code": "valuation_publication_status_drift"})
    ledger_head = int(
        conn.execute("SELECT COALESCE(MAX(id), 0) FROM ledger_entries").fetchone()[0]
    )
    if ledger_head != expected_cutoff:
        blockers.append(
            {
                "code": "valuation_ledger_head_drift",
                "expected_ledger_cutoff_id": expected_cutoff,
                "current_ledger_cutoff_id": ledger_head,
            }
        )


def _validate_quote_revision(
    conn: sqlite3.Connection,
    *,
    expected: Any,
    blockers: list[dict[str, Any]],
) -> None:
    expected_revision = _non_negative_int(expected)
    if expected_revision is None:
        blockers.append({"code": "quote_current_revision_binding_missing"})
        return
    try:
        current = assert_quote_current_materialization_on_connection(conn)
    except RuntimeError as exc:
        blockers.append(
            {
                "code": "quote_current_materialization_unavailable",
                "reason": str(exc),
            }
        )
        return
    if current.revision != expected_revision:
        blockers.append(
            {
                "code": "quote_current_materialization_revision_drift",
                "expected_revision": expected_revision,
                "current_revision": current.revision,
            }
        )


def _validate_candidate_quotes(
    conn: sqlite3.Connection,
    *,
    bindings: Any,
    writes: Sequence[tuple[Any, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    if not isinstance(bindings, list):
        blockers.append({"code": "candidate_quote_bindings_missing"})
        return
    by_identity = {
        (str(item.get("symbol") or ""), str(item.get("instrument_type") or "")): item
        for item in bindings
        if isinstance(item, Mapping)
    }
    required: set[tuple[str, str]] = set()
    for intent, _decision in writes:
        try:
            metadata = getattr(intent, "metadata", {})
            instrument_type = (
                metadata.get("instrument_type")
                if isinstance(metadata, Mapping)
                else None
            )
            key = InstrumentKey.from_values(
                str(intent.symbol),
                instrument_type
                or (
                    intent.asset_class.value if intent.asset_class is not None else None
                ),
            )
        except (TypeError, ValueError):
            blockers.append({"code": "risk_batch_instrument_identity_missing"})
            continue
        required.add((key.symbol, key.instrument_type.value))
    if not required.issubset(by_identity):
        blockers.append({"code": "candidate_quote_binding_incomplete"})
        return

    for identity in sorted(required):
        binding = by_identity[identity]
        quote_id = _positive_int(binding.get("quote_id"))
        expected_fingerprint = str(
            binding.get("persisted_row_fingerprint") or ""
        ).strip()
        if quote_id is None or not expected_fingerprint.startswith("sha256:"):
            blockers.append(
                {
                    "code": "candidate_quote_identity_missing",
                    "symbol": identity[0],
                    "instrument_type": identity[1],
                }
            )
            continue
        row = conn.execute(
            "SELECT * FROM latest_quotes WHERE id = ? LIMIT 1",
            (quote_id,),
        ).fetchone()
        if row is None:
            blockers.append(
                {
                    "code": "candidate_quote_row_missing",
                    "symbol": identity[0],
                    "instrument_type": identity[1],
                }
            )
            continue
        current = dict(row)
        try:
            current_key = InstrumentKey.from_values(
                current.get("symbol"), current.get("asset_type")
            )
        except (TypeError, ValueError):
            current_key = None
        if (
            current_key is None
            or (
                current_key.symbol,
                current_key.instrument_type.value,
            )
            != identity
        ):
            blockers.append(
                {
                    "code": "candidate_quote_instrument_identity_drift",
                    "symbol": identity[0],
                    "instrument_type": identity[1],
                }
            )
        elif _fingerprint(current) != expected_fingerprint:
            blockers.append(
                {
                    "code": "candidate_quote_content_drift",
                    "symbol": identity[0],
                    "instrument_type": identity[1],
                }
            )


def _published_valuation_identity(
    conn: sqlite3.Connection,
    *,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    control = conn.execute("""
        SELECT value_json FROM runtime_controls
        WHERE key = 'valuation_snapshot_publication'
        LIMIT 1
        """).fetchone()
    if control is None:
        blockers.append({"code": "valuation_publication_unavailable"})
        return {}
    try:
        publication = json.loads(str(control["value_json"]))
    except (TypeError, json.JSONDecodeError):
        blockers.append({"code": "valuation_publication_invalid"})
        return {}
    if not isinstance(publication, dict) or publication.get("status") != "ready":
        blockers.append({"code": "valuation_publication_not_ready"})
        return {}
    snapshot_id = str(publication.get("snapshot_id") or "").strip()
    if not snapshot_id:
        blockers.append({"code": "valuation_publication_invalid"})
        return {}
    row = conn.execute(
        """
        SELECT snapshot_id, ledger_cutoff_id, status
        FROM valuation_snapshots WHERE snapshot_id = ? LIMIT 1
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        blockers.append({"code": "valuation_publication_snapshot_missing"})
        return {}
    return {
        "valuation_snapshot_id": str(row["snapshot_id"]),
        "ledger_cutoff_id": int(row["ledger_cutoff_id"] or 0),
        "valuation_status": str(row["status"]),
    }


def _risk_decision_source_signal_ids(conn: sqlite3.Connection) -> set[int]:
    result: set[int] = set()
    rows = conn.execute(
        "SELECT id, payload_json FROM risk_decisions ORDER BY timestamp DESC, id DESC"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        intent_payload = payload.get("intent") if isinstance(payload, dict) else None
        if not isinstance(intent_payload, dict):
            continue
        source_signal_id = _positive_int(intent_payload.get("source_signal_id"))
        if source_signal_id is not None:
            result.add(source_signal_id)
    return result


def _intent_matches_action(intent: Any, decision: Any, row: sqlite3.Row) -> bool:
    metadata = getattr(intent, "metadata", {})
    if not isinstance(metadata, Mapping):
        return False
    try:
        intent_key = InstrumentKey.from_values(
            str(intent.symbol),
            metadata.get("instrument_type")
            or (intent.asset_class.value if intent.asset_class is not None else None),
        )
        action_key = InstrumentKey.from_values(row["symbol"], row["asset_class"])
    except (AttributeError, TypeError, ValueError):
        return False
    direction = str(row["direction"] or "").lower()
    side = str(intent.side.value).lower()
    if direction != "rebalance" and direction != side:
        return False
    checks = (
        (str(intent.source_signal_id or ""), str(row["source_signal_id"])),
        (str(intent.strategy_id or ""), str(row["strategy_id"])),
        (intent.timestamp.isoformat(), str(row["timestamp"])),
        (intent_key.storage_tuple(), action_key.storage_tuple()),
        (str(decision.intent_id or ""), str(intent.intent_id)),
        (str(decision.symbol), str(intent.symbol)),
        (str(decision.side.value).lower(), side),
    )
    if any(actual != expected for actual, expected in checks):
        return False
    return _same_decimal(
        metadata.get("raw_target_weight", intent.target_weight),
        row["target_weight"],
    )


def _insert_risk_decision(
    conn: sqlite3.Connection,
    *,
    intent: Any,
    decision: Any,
    created_at: str,
) -> int:
    payload = _risk_decision_payload(intent=intent, decision=decision)
    cursor = conn.execute(
        """
        INSERT INTO risk_decisions
            (decision_id, intent_id, timestamp, passed, symbol, side,
             reasons_json, resulting_order_id, severity, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.decision_id,
            decision.intent_id,
            decision.timestamp.isoformat(),
            1 if decision.passed else 0,
            str(decision.symbol),
            decision.side.value,
            json.dumps(decision.reasons, ensure_ascii=False),
            decision.resulting_order_id,
            decision.severity,
            json.dumps(payload, ensure_ascii=False),
            created_at,
        ),
    )
    row_id = int(cursor.lastrowid or 0)
    insert_event_sync(
        conn,
        event_type="risk.signal.recorded",
        timestamp=decision.timestamp.isoformat(),
        entity_type="risk_signal",
        entity_id=decision.decision_id,
        source="risk_decisions",
        source_ref=decision.decision_id,
        payload={
            "intent": {
                "timestamp": intent.timestamp.isoformat(),
                "intent_id": intent.intent_id,
                "strategy_id": intent.strategy_id,
                "symbol": str(intent.symbol),
                "side": intent.side.value,
                "target_weight": str(intent.target_weight),
                "quantity": str(intent.quantity),
                "reference_price": str(intent.reference_price),
                "reason": intent.reason,
            },
            "decision": {
                "timestamp": decision.timestamp.isoformat(),
                "decision_id": decision.decision_id,
                "intent_id": decision.intent_id,
                "passed": decision.passed,
                "symbol": str(decision.symbol),
                "side": decision.side.value,
                "reasons": decision.reasons,
                "severity": decision.severity,
            },
            "risk_decision_id": row_id,
        },
    )
    return row_id


def _risk_decision_payload(*, intent: Any, decision: Any) -> dict[str, Any]:
    return {
        "intent": {
            "timestamp": intent.timestamp.isoformat(),
            "intent_id": intent.intent_id,
            "strategy_id": intent.strategy_id,
            "symbol": str(intent.symbol),
            "side": intent.side.value,
            "target_weight": str(intent.target_weight),
            "quantity": str(intent.quantity),
            "reference_price": str(intent.reference_price),
            "asset_class": (
                intent.asset_class.value if intent.asset_class is not None else None
            ),
            "source_signal_id": intent.source_signal_id,
            "reason": intent.reason,
            "metadata": intent.metadata,
        },
        "decision": {
            "timestamp": decision.timestamp.isoformat(),
            "decision_id": decision.decision_id,
            "intent_id": decision.intent_id,
            "passed": decision.passed,
            "symbol": str(decision.symbol),
            "side": decision.side.value,
            "reasons": decision.reasons,
            "resulting_order_id": decision.resulting_order_id,
            "severity": decision.severity,
            "metadata": decision.metadata,
        },
    }


def _action_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value.get(key) for key in _ACTION_COLUMNS}


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _same_decimal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _positive_int(value: Any) -> int | None:
    parsed = _non_negative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = ["PreTradeRiskUnitOfWork"]
