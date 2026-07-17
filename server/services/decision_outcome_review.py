"""Evidence-bound, human-only post-decision reviews.

The review target is rebuilt exclusively from persisted signal, risk, order,
fill, ledger, and valuation facts.  Recording a review appends audit evidence;
it never mutates those facts or grants trading authority.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.db import _insert_event_sync
from server.models import AccountStrategyAssignment
from server.routes.account_strategy import (
    _fill_metadata,
    _linked_strategy_evidence,
    _order_source_signal_id,
)
from server.services.strategy_contribution import build_strategy_contribution_report

DECISION_OUTCOME_REVIEW_CONTRACT_VERSION = "karkinos.decision_outcome_review.v1"
DECISION_OUTCOME_REVIEW_REQUEST_VERSION = "karkinos.decision_outcome_review_request.v1"
DECISION_OUTCOME_REVIEW_TARGET_VERSION = "karkinos.decision_outcome_review_target.v1"
DECISION_OUTCOME_REVIEW_CONFIRMATION = (
    "record_evidence_bound_decision_review_without_trade_or_capital_authority"
)

_USER_DECISIONS = {"acted", "ignored", "deferred", "blocked"}
_OUTCOMES = {
    "evidence_supported",
    "evidence_not_supported",
    "risk_gate_validated",
    "not_executed",
    "inconclusive",
}


class DecisionOutcomeReviewRejected(ValueError):
    """Raised when a review request violates deterministic local gates."""


class DecisionOutcomeReviewTargetDrift(DecisionOutcomeReviewRejected):
    """Raised when persisted evidence changed after the operator previewed it."""


@dataclass(frozen=True)
class DecisionOutcomeReviewRequest:
    idempotency_key: str
    reviewed_by: str
    user_decision: str
    outcome: str
    note: str
    expected_target_fingerprint: str
    confirmation: str
    schema_version: str = DECISION_OUTCOME_REVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "expected_target_fingerprint",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.schema_version != DECISION_OUTCOME_REVIEW_REQUEST_VERSION:
            raise ValueError("decision outcome review request version drifted")
        if self.user_decision not in _USER_DECISIONS:
            raise ValueError("unsupported user_decision")
        if self.outcome not in _OUTCOMES:
            raise ValueError("unsupported outcome")
        if self.confirmation != DECISION_OUTCOME_REVIEW_CONFIRMATION:
            raise ValueError("explicit no-authority review confirmation is required")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "reviewed_by": self.reviewed_by,
            "user_decision": self.user_decision,
            "outcome": self.outcome,
            "note": self.note,
            "expected_target_fingerprint": self.expected_target_fingerprint,
            "confirmation": self.confirmation,
        }


@dataclass(frozen=True)
class DecisionOutcomeReviewTarget:
    signal_id: int
    signal: dict[str, Any]
    signal_fingerprint: str
    action_task: dict[str, Any] | None
    risk_decision: dict[str, Any] | None
    execution_evidence: dict[str, Any]
    strategy_contribution_report: dict[str, Any]
    financial_evidence_status: str
    allowed_outcomes: tuple[str, ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    fingerprint: str
    schema_version: str = DECISION_OUTCOME_REVIEW_TARGET_VERSION

    def to_dict(self) -> dict[str, Any]:
        contribution = self.strategy_contribution_report
        return {
            "schema_version": self.schema_version,
            "signal_id": self.signal_id,
            "signal": self.signal,
            "signal_fingerprint": self.signal_fingerprint,
            "action_task": self.action_task,
            "risk_decision": self.risk_decision,
            "execution_evidence": self.execution_evidence,
            "strategy_contribution_report": contribution,
            "financial_evidence_status": self.financial_evidence_status,
            "valuation_snapshot_id": contribution.get("valuation_snapshot_id"),
            "ledger_cutoff_id": contribution.get("ledger_cutoff_id", 0),
            "contribution_fingerprint": contribution.get("contribution_fingerprint"),
            "allowed_outcomes": list(self.allowed_outcomes),
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "target_fingerprint": self.fingerprint,
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class StoredDecisionOutcomeReview:
    review_id: str
    signal_id: int
    idempotency_key: str
    request: dict[str, Any]
    request_fingerprint: str
    target: dict[str, Any]
    target_fingerprint: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
            "review_id": self.review_id,
            "signal_id": self.signal_id,
            "idempotency_key": self.idempotency_key,
            "reviewed_at": self.created_at,
            "reviewed_by": self.request["reviewed_by"],
            "user_decision": self.request["user_decision"],
            "outcome": self.request["outcome"],
            "note": self.request["note"],
            "request_fingerprint": self.request_fingerprint,
            "stored_target_fingerprint": self.target_fingerprint,
            "stored_target": self.target,
        }


@dataclass(frozen=True)
class DecisionOutcomeReviewReplay:
    review_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.decision_outcome_review_replay.v1",
            "review_id": self.review_id,
            "valid": self.valid,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "persisted_facts_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class DecisionOutcomeReviewResult:
    review: StoredDecisionOutcomeReview
    current_target: DecisionOutcomeReviewTarget
    audit_replay: DecisionOutcomeReviewReplay
    reused: bool

    def to_dict(self) -> dict[str, Any]:
        binding_valid = (
            self.review.target_fingerprint == self.current_target.fingerprint
        )
        return {
            "schema_version": DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
            "review": self.review.to_dict(),
            "current_target": self.current_target.to_dict(),
            "target_binding_valid": binding_valid,
            "audit_replay": self.audit_replay.to_dict(),
            "reused": self.reused,
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": True,
            "does_not_mutate_financial_state": True,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


class DecisionOutcomeReviewStore:
    """Transactional review records plus a tamper-evident event chain."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            yield conn
        finally:
            conn.close()

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> StoredDecisionOutcomeReview | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _review_from_row(row) if row is not None else None

    def get(self, review_id: str) -> StoredDecisionOutcomeReview:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"decision outcome review not found: {review_id}")
        return _review_from_row(row)

    def record(
        self,
        *,
        signal_id: int,
        target: DecisionOutcomeReviewTarget,
        request: DecisionOutcomeReviewRequest,
        created_at: str,
    ) -> tuple[StoredDecisionOutcomeReview, bool]:
        review_id = (
            "decision-review-"
            + content_fingerprint(
                {
                    "signal_id": signal_id,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                }
            )[:24]
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _review_from_row(existing)
                if (
                    stored.signal_id != signal_id
                    or stored.request_fingerprint != request.fingerprint
                    or stored.target_fingerprint != target.fingerprint
                ):
                    raise IdempotencyConflict(
                        "decision review idempotency key was reused with different input"
                    )
                conn.commit()
                return stored, True

            conn.execute(
                """
                INSERT INTO decision_outcome_reviews (
                    review_id, signal_id, idempotency_key, request_json,
                    request_fingerprint, target_json, target_fingerprint,
                    reviewed_by, user_decision, outcome, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    signal_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    canonical_json(target.to_dict()),
                    target.fingerprint,
                    request.reviewed_by,
                    request.user_decision,
                    request.outcome,
                    request.note,
                    created_at,
                ),
            )
            self._append_review_event(
                conn,
                review_id=review_id,
                event_type="decision_outcome_review_recorded",
                payload={
                    "signal_id": signal_id,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "outcome": request.outcome,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            contribution = target.strategy_contribution_report
            _insert_event_sync(
                conn,
                event_type="decision.outcome_review.recorded",
                timestamp=created_at,
                entity_type="signal",
                entity_id=str(signal_id),
                source="decision_outcome_reviews",
                source_ref=review_id,
                payload={
                    "schema_version": DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
                    "review_id": review_id,
                    "signal_id": signal_id,
                    "reviewed_at": created_at,
                    "user_decision": request.user_decision,
                    "outcome": request.outcome,
                    "review_notes": request.note,
                    "reviewer": request.reviewed_by,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "signal_fingerprint": target.signal_fingerprint,
                    "financial_evidence_status": target.financial_evidence_status,
                    "valuation_snapshot_id": contribution.get("valuation_snapshot_id"),
                    "ledger_cutoff_id": contribution.get("ledger_cutoff_id", 0),
                    "contribution_fingerprint": contribution.get(
                        "contribution_fingerprint"
                    ),
                    "persisted_facts_only": True,
                    "provider_contacted": False,
                    "does_not_mutate_financial_state": True,
                    "authorizes_execution": False,
                    "authority_effect": "none",
                },
            )
            row = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("decision outcome review persistence failed")
        return _review_from_row(row), False

    def verify_replay(self, review_id: str) -> DecisionOutcomeReviewReplay:
        with self._connection() as conn:
            review = conn.execute(
                "SELECT review_id FROM decision_outcome_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            if review is None:
                raise LookupError(f"decision outcome review not found: {review_id}")
            rows = conn.execute(
                """
                SELECT * FROM decision_outcome_review_events
                WHERE review_id = ? ORDER BY sequence ASC
                """,
                (review_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            payload = _json_object(row["payload_json"])
            if int(row["sequence"]) != expected_sequence:
                errors.append("event_sequence_gap")
            if row["previous_hash"] != previous_hash:
                errors.append("event_previous_hash_mismatch")
            expected_hash = _event_hash(
                review_id=review_id,
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if row["event_hash"] != expected_hash:
                errors.append("event_hash_mismatch")
            previous_hash = str(row["event_hash"])
        if not rows:
            errors.append("review_event_missing")
        return DecisionOutcomeReviewReplay(
            review_id=review_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_review_event(
        conn: sqlite3.Connection,
        *,
        review_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        previous = conn.execute(
            """
            SELECT sequence, event_hash FROM decision_outcome_review_events
            WHERE review_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (review_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = _event_hash(
            review_id=review_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO decision_outcome_review_events (
                review_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )


class DecisionOutcomeReviewService:
    """Preview, record, and revalidate one human post-decision review."""

    def __init__(self, *, db: Any, store: DecisionOutcomeReviewStore, now) -> None:
        self._db = db
        self._store = store
        self._now = now

    def preview(self, signal_id: int) -> DecisionOutcomeReviewTarget:
        return build_decision_outcome_review_target(db=self._db, signal_id=signal_id)

    def review(
        self,
        signal_id: int,
        request: DecisionOutcomeReviewRequest,
    ) -> DecisionOutcomeReviewResult:
        existing = self._store.get_by_idempotency_key(request.idempotency_key)
        target = self.preview(signal_id)
        if existing is not None:
            if (
                existing.signal_id != signal_id
                or existing.request_fingerprint != request.fingerprint
                or existing.target_fingerprint != request.expected_target_fingerprint
            ):
                raise IdempotencyConflict(
                    "decision review idempotency key was reused with different input"
                )
            return self._result(existing, reused=True)
        if request.expected_target_fingerprint != target.fingerprint:
            raise DecisionOutcomeReviewTargetDrift(
                "decision review target changed; preview the persisted evidence again"
            )
        _validate_review_semantics(request=request, target=target)
        review, reused = self._store.record(
            signal_id=signal_id,
            target=target,
            request=request,
            created_at=self._now(),
        )
        return self._result(review, reused=reused)

    def get(self, review_id: str) -> DecisionOutcomeReviewResult:
        return self._result(self._store.get(review_id), reused=True)

    def replay(self, review_id: str) -> DecisionOutcomeReviewReplay:
        return self._store.verify_replay(review_id)

    def _result(
        self,
        review: StoredDecisionOutcomeReview,
        *,
        reused: bool,
    ) -> DecisionOutcomeReviewResult:
        current_target = self.preview(review.signal_id)
        return DecisionOutcomeReviewResult(
            review=review,
            current_target=current_target,
            audit_replay=self._store.verify_replay(review.review_id),
            reused=reused,
        )


def build_decision_outcome_review_target(
    *, db: Any, signal_id: int
) -> DecisionOutcomeReviewTarget:
    journal_entries = db.list_signal_journal_sync(limit=10_000, offset=0)
    entry = next(
        (
            item
            for item in journal_entries
            if int((item.get("signal") or {}).get("id") or 0) == signal_id
        ),
        None,
    )
    if entry is None:
        raise LookupError(f"signal not found: {signal_id}")

    signal = _project_signal(entry["signal"])
    signal_fingerprint = content_fingerprint(signal)
    action_task = _project_action(entry.get("action_task"))
    risk_decision = _project_risk(entry.get("risk_decision"))
    assignment = AccountStrategyAssignment(
        strategy_id=str(signal["strategy_id"]),
        strategy_name=str(signal["strategy_id"]),
        status="research_only",
        scope="symbol",
        symbol=str(signal["symbol"]),
        auto_trade_enabled=False,
        attribution_status="evidence_review",
        limitations=[
            "This symbol-scoped assignment exists only to project persisted review evidence."
        ],
    )
    linked = _linked_strategy_evidence(db, assignment)
    contribution = build_strategy_contribution_report(
        db=db,
        assignment=assignment,
        evidence=linked,
    ).model_dump(mode="json")

    risk_decision_id = str((risk_decision or {}).get("decision_id") or "")
    intent_id = str((risk_decision or {}).get("intent_id") or "")
    exact_orders = [
        _project_order(order)
        for order in linked["linked_orders"]
        if _order_source_signal_id(order) == signal_id
        or (
            risk_decision_id
            and str(order.get("risk_decision_id") or "") == risk_decision_id
        )
        or (intent_id and str(order.get("intent_id") or "") == intent_id)
    ]
    exact_order_ids = {str(order["order_id"]) for order in exact_orders}
    exact_fills = [
        _project_fill(fill)
        for fill in linked["linked_fills"]
        if str(fill.get("order_id") or "") in exact_order_ids
        or _metadata_signal_id(_fill_metadata(fill)) == signal_id
    ]
    execution_status = _execution_status(
        risk_decision=risk_decision,
        orders=exact_orders,
        fills=exact_fills,
    )
    execution_evidence = {
        "status": execution_status,
        "orders": exact_orders,
        "fills": exact_fills,
        "order_count": len(exact_orders),
        "fill_count": len(exact_fills),
    }
    financial_status, blockers = _financial_evidence_status(
        execution_status=execution_status,
        contribution=contribution,
    )
    allowed_outcomes = _allowed_outcomes(
        execution_status=execution_status,
        financial_evidence_status=financial_status,
        risk_decision=risk_decision,
    )
    limitations = (
        "Outcome labels are human conclusions; numeric P/L remains the canonical contribution projection.",
        "The contribution report is strategy-and-symbol scoped and is not silently reallocated to one signal.",
        "A review records audit evidence only and cannot submit, cancel, resume, or authorize capital.",
    )
    identity = {
        "schema_version": DECISION_OUTCOME_REVIEW_TARGET_VERSION,
        "signal_id": signal_id,
        "signal": signal,
        "signal_fingerprint": signal_fingerprint,
        "action_task": action_task,
        "risk_decision": risk_decision,
        "execution_evidence": execution_evidence,
        "strategy_contribution_report": contribution,
        "financial_evidence_status": financial_status,
        "allowed_outcomes": list(allowed_outcomes),
        "blockers": list(blockers),
        "limitations": list(limitations),
    }
    return DecisionOutcomeReviewTarget(
        signal_id=signal_id,
        signal=signal,
        signal_fingerprint=signal_fingerprint,
        action_task=action_task,
        risk_decision=risk_decision,
        execution_evidence=execution_evidence,
        strategy_contribution_report=contribution,
        financial_evidence_status=financial_status,
        allowed_outcomes=allowed_outcomes,
        blockers=blockers,
        limitations=limitations,
        fingerprint=content_fingerprint(identity),
    )


def _validate_review_semantics(
    *,
    request: DecisionOutcomeReviewRequest,
    target: DecisionOutcomeReviewTarget,
) -> None:
    if request.outcome not in target.allowed_outcomes:
        raise DecisionOutcomeReviewRejected(
            f"outcome is not supported by current evidence: {request.outcome}"
        )
    if request.outcome in {"evidence_supported", "evidence_not_supported"}:
        if request.user_decision != "acted":
            raise DecisionOutcomeReviewRejected(
                "evidence outcome requires user_decision=acted"
            )
    elif request.outcome == "risk_gate_validated":
        if request.user_decision not in {"blocked", "ignored"}:
            raise DecisionOutcomeReviewRejected(
                "risk-gate outcome requires a blocked or ignored decision"
            )
    elif request.outcome == "not_executed":
        if request.user_decision not in {"ignored", "deferred", "blocked"}:
            raise DecisionOutcomeReviewRejected(
                "not-executed outcome cannot be recorded as acted"
            )


def _financial_evidence_status(
    *,
    execution_status: str,
    contribution: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    if execution_status in {"risk_blocked_no_execution", "not_executed"}:
        return "not_applicable", ()
    if execution_status == "order_recorded_no_fill":
        return "blocked", ("signal_execution_outcome_incomplete",)
    if (
        contribution.get("evidence_binding_status") == "bound"
        and contribution.get("contribution_fingerprint")
        and contribution.get("valuation_snapshot_id")
        and int(contribution.get("ledger_cutoff_id") or 0) > 0
    ):
        return "bound", ()
    blockers = tuple(
        dict.fromkeys(
            [
                "strategy_contribution_not_evidence_bound",
                *(str(item) for item in contribution.get("blockers") or []),
            ]
        )
    )
    return "blocked", blockers


def _allowed_outcomes(
    *,
    execution_status: str,
    financial_evidence_status: str,
    risk_decision: dict[str, Any] | None,
) -> tuple[str, ...]:
    outcomes = ["inconclusive"]
    if execution_status in {"risk_blocked_no_execution", "not_executed"}:
        outcomes.append("not_executed")
    if risk_decision is not None and risk_decision.get("passed") is False:
        outcomes.append("risk_gate_validated")
    if financial_evidence_status == "bound":
        outcomes.extend(["evidence_supported", "evidence_not_supported"])
    return tuple(outcomes)


def _execution_status(
    *,
    risk_decision: dict[str, Any] | None,
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
) -> str:
    if fills:
        return "fills_linked"
    if orders:
        return "order_recorded_no_fill"
    if risk_decision is not None and risk_decision.get("passed") is False:
        return "risk_blocked_no_execution"
    return "not_executed"


def _project_signal(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "id",
            "timestamp",
            "strategy_id",
            "symbol",
            "direction",
            "target_weight",
            "price",
            "asset_class",
        )
    }


def _project_action(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        key: value.get(key)
        for key in (
            "id",
            "source_signal_id",
            "symbol",
            "direction",
            "target_weight",
            "strategy_id",
            "status",
            "timestamp",
            "updated_at",
        )
    }


def _project_risk(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        key: value.get(key)
        for key in (
            "decision_id",
            "intent_id",
            "timestamp",
            "passed",
            "symbol",
            "side",
            "reasons",
            "resulting_order_id",
            "severity",
        )
    }


def _project_order(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "order_id",
            "intent_id",
            "risk_decision_id",
            "symbol",
            "side",
            "quantity",
            "filled_quantity",
            "status",
            "execution_mode",
            "created_at",
            "updated_at",
        )
    }


def _project_fill(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "fill_id",
            "order_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "commission",
            "slippage",
            "timestamp",
        )
    }


def _metadata_signal_id(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("source_signal_id") or metadata.get("signal_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _review_from_row(row: sqlite3.Row) -> StoredDecisionOutcomeReview:
    return StoredDecisionOutcomeReview(
        review_id=str(row["review_id"]),
        signal_id=int(row["signal_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request=_json_object(row["request_json"]),
        request_fingerprint=str(row["request_fingerprint"]),
        target=_json_object(row["target_json"]),
        target_fingerprint=str(row["target_fingerprint"]),
        created_at=str(row["created_at"]),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError("stored review JSON must be an object")
    return parsed


def _event_hash(
    *,
    review_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "review_id": review_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )
