"""Evidence-bound daily Decision Quality Score and immutable captures.

The current projection is calculated only from the canonical Decision payload.
Capturing it appends audit evidence; it never mutates financial facts, risk
decisions, execution state, or authority.
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

DECISION_QUALITY_TARGET_VERSION = "karkinos.decision_quality_target.v1"
DECISION_QUALITY_CAPTURE_VERSION = "karkinos.decision_quality_capture.v1"
DECISION_QUALITY_REPORT_VERSION = "karkinos.decision_quality_report.v1"
DECISION_QUALITY_REQUEST_VERSION = "karkinos.decision_quality_capture_request.v1"
DECISION_QUALITY_CONFIRMATION = (
    "capture_decision_quality_evidence_without_financial_or_trading_authority"
)

_DIMENSION_NAMES = (
    "data_complete",
    "risk_checked",
    "benchmark_aware",
    "journaled",
    "later_reviewable",
)
_TRUSTED_MARKET_STATUSES = {"confirmed", "live"}
_TRUSTED_CANDIDATE_DATA_STATUSES = {
    "complete",
    "confirmed",
    "fresh",
    "live",
    "pass",
}
_UNTRUSTED_ESTIMATE_SOURCES = {"eastmoney_fund_estimate"}
_CHECKED_RISK_STATUSES = {"blocked", "passed"}


class DecisionQualityCaptureRejected(ValueError):
    """Raised when a capture violates the deterministic local contract."""


class DecisionQualityTargetDrift(DecisionQualityCaptureRejected):
    """Raised when Decision evidence changed after the operator previewed it."""


@dataclass(frozen=True)
class DecisionQualityDimension:
    name: str
    passed: bool
    status: str
    evidence: dict[str, Any]
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "status": self.status,
            "evidence": self.evidence,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class DecisionQualityTarget:
    decision_date: str
    decision: str
    candidate_count: int
    decision_fingerprint: str
    dimensions: tuple[DecisionQualityDimension, ...]
    valuation_snapshot_id: str | None
    ledger_cutoff_id: int
    ledger_fingerprint: str | None
    quote_set_fingerprint: str | None
    fingerprint: str
    schema_version: str = DECISION_QUALITY_TARGET_VERSION

    @property
    def passed_dimension_count(self) -> int:
        return sum(1 for item in self.dimensions if item.passed)

    @property
    def qualified(self) -> bool:
        return self.passed_dimension_count == len(_DIMENSION_NAMES)

    @property
    def diagnostic_score_percent(self) -> float:
        return round(100 * self.passed_dimension_count / len(_DIMENSION_NAMES), 2)

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                blocker
                for dimension in self.dimensions
                for blocker in dimension.blockers
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_date": self.decision_date,
            "decision": self.decision,
            "candidate_count": self.candidate_count,
            "decision_fingerprint": self.decision_fingerprint,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "passed_dimension_count": self.passed_dimension_count,
            "dimension_count": len(_DIMENSION_NAMES),
            "diagnostic_score_percent": self.diagnostic_score_percent,
            "qualified": self.qualified,
            "qualification_status": "qualified" if self.qualified else "blocked",
            "blockers": list(self.blockers),
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "ledger_cutoff_id": self.ledger_cutoff_id,
            "ledger_fingerprint": self.ledger_fingerprint,
            "quote_set_fingerprint": self.quote_set_fingerprint,
            "target_fingerprint": self.fingerprint,
            "persisted_facts_only": True,
            "runtime_cache_used": False,
            "provider_contacted": False,
            "database_writes_performed": False,
            "authorizes_execution": False,
            "authority_effect": "none",
            "limitations": [
                "The diagnostic percentage shows satisfied dimensions; the North Star daily result is binary qualified or blocked.",
                "Longitudinal coverage includes explicitly captured days only and must not be presented as all trading days.",
                "A blocked or risk-rejected decision may still be high quality when every required check is complete.",
            ],
        }


@dataclass(frozen=True)
class DecisionQualityCaptureRequest:
    idempotency_key: str
    captured_by: str
    expected_target_fingerprint: str
    confirmation: str
    schema_version: str = DECISION_QUALITY_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "captured_by",
            "expected_target_fingerprint",
            "confirmation",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.schema_version != DECISION_QUALITY_REQUEST_VERSION:
            raise ValueError("decision quality capture request version drifted")
        if self.confirmation != DECISION_QUALITY_CONFIRMATION:
            raise ValueError("explicit no-authority capture confirmation is required")
        if len(self.expected_target_fingerprint) != 64:
            raise ValueError("expected_target_fingerprint must be a sha256 digest")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "captured_by": self.captured_by,
            "expected_target_fingerprint": self.expected_target_fingerprint,
            "confirmation": self.confirmation,
        }


@dataclass(frozen=True)
class StoredDecisionQualityCapture:
    snapshot_id: str
    decision_date: str
    idempotency_key: str
    request: dict[str, Any]
    request_fingerprint: str
    target: dict[str, Any]
    target_fingerprint: str
    qualified: bool
    captured_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_QUALITY_CAPTURE_VERSION,
            "snapshot_id": self.snapshot_id,
            "decision_date": self.decision_date,
            "captured_at": self.captured_at,
            "captured_by": self.request["captured_by"],
            "qualified": self.qualified,
            "request_fingerprint": self.request_fingerprint,
            "stored_target_fingerprint": self.target_fingerprint,
            "stored_target": self.target,
        }


@dataclass(frozen=True)
class DecisionQualityReplay:
    snapshot_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.decision_quality_replay.v1",
            "snapshot_id": self.snapshot_id,
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
class DecisionQualityReport:
    status: str
    score_percent: float | None
    evaluated_day_count: int
    qualified_day_count: int
    blocked_day_count: int
    total_capture_count: int
    coverage_start: str | None
    coverage_end: str | None
    latest_by_day: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_QUALITY_REPORT_VERSION,
            "status": self.status,
            "score_percent": self.score_percent,
            "evaluated_day_count": self.evaluated_day_count,
            "qualified_day_count": self.qualified_day_count,
            "blocked_day_count": self.blocked_day_count,
            "total_capture_count": self.total_capture_count,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "latest_by_day": list(self.latest_by_day),
            "blockers": list(self.blockers),
            "coverage_scope": "explicitly_captured_decision_days_only",
            "persisted_facts_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "authority_effect": "none",
            "limitations": [
                "Uncaptured days are visible as missing coverage, not silently counted as qualified or blocked.",
                "This score measures decision-process evidence, not investment return or investment advice.",
            ],
        }


@dataclass(frozen=True)
class DecisionQualityView:
    current_target: DecisionQualityTarget
    report: DecisionQualityReport
    current_day_capture: StoredDecisionQualityCapture | None
    current_binding_valid: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.decision_quality_view.v1",
            "current_target": self.current_target.to_dict(),
            "report": self.report.to_dict(),
            "current_day_capture": (
                self.current_day_capture.to_dict()
                if self.current_day_capture is not None
                else None
            ),
            "current_day_captured": self.current_day_capture is not None,
            "current_binding_valid": self.current_binding_valid,
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class DecisionQualityCaptureResult:
    capture: StoredDecisionQualityCapture
    current_target: DecisionQualityTarget
    report: DecisionQualityReport
    audit_replay: DecisionQualityReplay
    reused: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_QUALITY_CAPTURE_VERSION,
            "capture": self.capture.to_dict(),
            "current_target": self.current_target.to_dict(),
            "target_binding_valid": (
                self.capture.target_fingerprint == self.current_target.fingerprint
            ),
            "report": self.report.to_dict(),
            "audit_replay": self.audit_replay.to_dict(),
            "reused": self.reused,
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": True,
            "does_not_mutate_financial_state": True,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


class DecisionQualityStore:
    """Append-only quality captures plus a tamper-evident event chain."""

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
    ) -> StoredDecisionQualityCapture | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _capture_from_row(row) if row is not None else None

    def get(self, snapshot_id: str) -> StoredDecisionQualityCapture:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"decision quality snapshot not found: {snapshot_id}")
        return _capture_from_row(row)

    def list(self, *, limit: int = 500) -> list[StoredDecisionQualityCapture]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM decision_quality_snapshots
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_capture_from_row(row) for row in rows]

    def record(
        self,
        *,
        target: DecisionQualityTarget,
        request: DecisionQualityCaptureRequest,
        captured_at: str,
    ) -> tuple[StoredDecisionQualityCapture, bool]:
        snapshot_id = (
            "decision-quality-"
            + content_fingerprint(
                {
                    "decision_date": target.decision_date,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                }
            )[:24]
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _capture_from_row(existing)
                if (
                    stored.request_fingerprint != request.fingerprint
                    or stored.target_fingerprint != target.fingerprint
                ):
                    raise IdempotencyConflict(
                        "decision quality idempotency key was reused with different input"
                    )
                conn.commit()
                return stored, True

            target_document = target.to_dict()
            conn.execute(
                """
                INSERT INTO decision_quality_snapshots (
                    snapshot_id, decision_date, idempotency_key, request_json,
                    request_fingerprint, target_json, target_fingerprint,
                    qualified, captured_by, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    target.decision_date,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    canonical_json(target_document),
                    target.fingerprint,
                    int(target.qualified),
                    request.captured_by,
                    captured_at,
                ),
            )
            self._append_event(
                conn,
                snapshot_id=snapshot_id,
                event_type="decision_quality_captured",
                payload={
                    "decision_date": target.decision_date,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "target_document_fingerprint": content_fingerprint(target_document),
                    "qualified": target.qualified,
                    "authority_effect": "none",
                },
                created_at=captured_at,
            )
            _insert_event_sync(
                conn,
                event_type="decision.quality.captured",
                timestamp=captured_at,
                entity_type="decision_day",
                entity_id=target.decision_date,
                source="decision_quality_snapshots",
                source_ref=snapshot_id,
                payload={
                    "schema_version": DECISION_QUALITY_CAPTURE_VERSION,
                    "snapshot_id": snapshot_id,
                    "decision_date": target.decision_date,
                    "qualified": target.qualified,
                    "diagnostic_score_percent": target.diagnostic_score_percent,
                    "decision_fingerprint": target.decision_fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "valuation_snapshot_id": target.valuation_snapshot_id,
                    "ledger_cutoff_id": target.ledger_cutoff_id,
                    "persisted_facts_only": True,
                    "provider_contacted": False,
                    "does_not_mutate_financial_state": True,
                    "authorizes_execution": False,
                    "authority_effect": "none",
                },
            )
            row = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("decision quality capture persistence failed")
        return _capture_from_row(row), False

    def verify_replay(self, snapshot_id: str) -> DecisionQualityReplay:
        with self._connection() as conn:
            capture = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if capture is None:
                raise LookupError(f"decision quality snapshot not found: {snapshot_id}")
            rows = conn.execute(
                """
                SELECT * FROM decision_quality_snapshot_events
                WHERE snapshot_id = ? ORDER BY sequence ASC
                """,
                (snapshot_id,),
            ).fetchall()
        errors: list[str] = []
        stored = _capture_from_row(capture)
        if content_fingerprint(stored.request) != stored.request_fingerprint:
            errors.append("request_fingerprint_mismatch")
        if stored.target.get("target_fingerprint") != stored.target_fingerprint:
            errors.append("target_fingerprint_mismatch")
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            payload = _json_object(row["payload_json"])
            if int(row["sequence"]) != expected_sequence:
                errors.append("event_sequence_gap")
            if row["previous_hash"] != previous_hash:
                errors.append("event_previous_hash_mismatch")
            expected_hash = _event_hash(
                snapshot_id=snapshot_id,
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if row["event_hash"] != expected_hash:
                errors.append("event_hash_mismatch")
            if payload.get("request_fingerprint") != stored.request_fingerprint:
                errors.append("event_request_fingerprint_mismatch")
            if payload.get("target_fingerprint") != stored.target_fingerprint:
                errors.append("event_target_fingerprint_mismatch")
            if payload.get("target_document_fingerprint") != content_fingerprint(
                stored.target
            ):
                errors.append("target_document_fingerprint_mismatch")
            previous_hash = str(row["event_hash"])
        if not rows:
            errors.append("capture_event_missing")
        return DecisionQualityReplay(
            snapshot_id=snapshot_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        snapshot_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        previous = conn.execute(
            """
            SELECT sequence, event_hash FROM decision_quality_snapshot_events
            WHERE snapshot_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = _event_hash(
            snapshot_id=snapshot_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO decision_quality_snapshot_events (
                snapshot_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )


class DecisionQualityService:
    """Build, capture, replay, and aggregate daily decision-quality evidence."""

    def __init__(self, *, store: DecisionQualityStore, now) -> None:
        self._store = store
        self._now = now

    def view(self, decision_payload: dict[str, Any]) -> DecisionQualityView:
        target = build_decision_quality_target(decision_payload)
        report = self.report()
        current_capture = next(
            (
                item
                for item in self._latest_by_day()
                if item.decision_date == target.decision_date
            ),
            None,
        )
        return DecisionQualityView(
            current_target=target,
            report=report,
            current_day_capture=current_capture,
            current_binding_valid=(
                current_capture.target_fingerprint == target.fingerprint
                if current_capture is not None
                else None
            ),
        )

    def capture(
        self,
        decision_payload: dict[str, Any],
        request: DecisionQualityCaptureRequest,
    ) -> DecisionQualityCaptureResult:
        existing = self._store.get_by_idempotency_key(request.idempotency_key)
        target = build_decision_quality_target(decision_payload)
        if existing is not None:
            if (
                existing.request_fingerprint != request.fingerprint
                or existing.target_fingerprint != request.expected_target_fingerprint
            ):
                raise IdempotencyConflict(
                    "decision quality idempotency key was reused with different input"
                )
            return self._result(existing, target=target, reused=True)
        if request.expected_target_fingerprint != target.fingerprint:
            raise DecisionQualityTargetDrift(
                "decision quality evidence changed; preview the current target again"
            )
        capture, reused = self._store.record(
            target=target,
            request=request,
            captured_at=self._now(),
        )
        return self._result(capture, target=target, reused=reused)

    def get(
        self,
        snapshot_id: str,
        decision_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capture = self._store.get(snapshot_id)
        result = {
            "capture": capture.to_dict(),
            "audit_replay": self._store.verify_replay(snapshot_id).to_dict(),
            "persisted_facts_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }
        if decision_payload is not None:
            current = build_decision_quality_target(decision_payload)
            result["current_target"] = current.to_dict()
            result["target_binding_valid"] = (
                capture.target_fingerprint == current.fingerprint
            )
        return result

    def replay(self, snapshot_id: str) -> DecisionQualityReplay:
        return self._store.verify_replay(snapshot_id)

    def report(self) -> DecisionQualityReport:
        captures = self._store.list()
        latest = self._latest_by_day(captures)
        invalid = [
            item.snapshot_id
            for item in latest
            if not self._store.verify_replay(item.snapshot_id).valid
        ]
        summaries = tuple(
            {
                "snapshot_id": item.snapshot_id,
                "decision_date": item.decision_date,
                "captured_at": item.captured_at,
                "qualified": item.qualified,
                "diagnostic_score_percent": item.target.get("diagnostic_score_percent"),
                "target_fingerprint": item.target_fingerprint,
                "audit_valid": item.snapshot_id not in invalid,
            }
            for item in latest
        )
        evaluated = len(latest)
        qualified = sum(1 for item in latest if item.qualified)
        decision_dates = sorted(item.decision_date for item in latest)
        if invalid:
            status = "blocked"
            score = None
            blockers = ("decision_quality_audit_integrity_failure",)
        elif evaluated == 0:
            status = "empty"
            score = None
            blockers = ("no_captured_decision_days",)
        else:
            status = "complete"
            score = round(100 * qualified / evaluated, 2)
            blockers = ()
        return DecisionQualityReport(
            status=status,
            score_percent=score,
            evaluated_day_count=evaluated,
            qualified_day_count=qualified,
            blocked_day_count=evaluated - qualified,
            total_capture_count=len(captures),
            coverage_start=decision_dates[0] if decision_dates else None,
            coverage_end=decision_dates[-1] if decision_dates else None,
            latest_by_day=summaries,
            blockers=blockers,
        )

    def _latest_by_day(
        self,
        captures: list[StoredDecisionQualityCapture] | None = None,
    ) -> list[StoredDecisionQualityCapture]:
        latest: dict[str, StoredDecisionQualityCapture] = {}
        for capture in captures if captures is not None else self._store.list():
            if capture.decision_date not in latest:
                latest[capture.decision_date] = capture
        return [latest[key] for key in sorted(latest, reverse=True)]

    def _result(
        self,
        capture: StoredDecisionQualityCapture,
        *,
        target: DecisionQualityTarget,
        reused: bool,
    ) -> DecisionQualityCaptureResult:
        return DecisionQualityCaptureResult(
            capture=capture,
            current_target=target,
            report=self.report(),
            audit_replay=self._store.verify_replay(capture.snapshot_id),
            reused=reused,
        )


def build_decision_quality_target(
    decision_payload: dict[str, Any],
) -> DecisionQualityTarget:
    summary = _mapping(decision_payload.get("summary"))
    portfolio = _mapping(summary.get("portfolio"))
    market_data = _mapping(summary.get("market_data"))
    account_truth = _mapping(summary.get("account_truth"))
    candidates = [
        _mapping(item) for item in list(decision_payload.get("candidates") or [])
    ]
    decision_date = str(decision_payload.get("decision_date") or "").strip()
    if not decision_date:
        raise DecisionQualityCaptureRejected("decision_date is required")
    decision = str(decision_payload.get("decision") or "no_action")
    candidate_identity = [_candidate_identity(item) for item in candidates]
    decision_fingerprint = content_fingerprint(
        {
            "decision_date": decision_date,
            "decision": decision,
            "candidates": candidate_identity,
            "no_action_reasons": list(decision_payload.get("no_action_reasons") or []),
        }
    )
    dimensions = (
        _data_complete_dimension(
            candidates=candidates,
            portfolio=portfolio,
            market_data=market_data,
            account_truth=account_truth,
        ),
        _risk_checked_dimension(candidates),
        _benchmark_aware_dimension(candidates),
        _journaled_dimension(candidates),
        _later_reviewable_dimension(candidates),
    )
    identity = {
        "schema_version": DECISION_QUALITY_TARGET_VERSION,
        "decision_date": decision_date,
        "decision": decision,
        "candidate_count": len(candidates),
        "decision_fingerprint": decision_fingerprint,
        "dimensions": [item.to_dict() for item in dimensions],
        "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
        "ledger_cutoff_id": int(portfolio.get("ledger_cutoff_id") or 0),
        "ledger_fingerprint": portfolio.get("ledger_fingerprint"),
        "quote_set_fingerprint": portfolio.get("quote_set_fingerprint"),
    }
    return DecisionQualityTarget(
        decision_date=decision_date,
        decision=decision,
        candidate_count=len(candidates),
        decision_fingerprint=decision_fingerprint,
        dimensions=dimensions,
        valuation_snapshot_id=_optional_text(portfolio.get("valuation_snapshot_id")),
        ledger_cutoff_id=int(portfolio.get("ledger_cutoff_id") or 0),
        ledger_fingerprint=_optional_text(portfolio.get("ledger_fingerprint")),
        quote_set_fingerprint=_optional_text(portfolio.get("quote_set_fingerprint")),
        fingerprint=content_fingerprint(identity),
    )


def _data_complete_dimension(
    *,
    candidates: list[dict[str, Any]],
    portfolio: dict[str, Any],
    market_data: dict[str, Any],
    account_truth: dict[str, Any],
) -> DecisionQualityDimension:
    blockers: list[str] = []
    if portfolio.get("fact_authority") != "persisted_valuation_snapshot":
        blockers.append("decision_not_bound_to_persisted_valuation_snapshot")
    if not portfolio.get("valuation_snapshot_id"):
        blockers.append("valuation_snapshot_id_missing")
    if portfolio.get("valuation_status") != "complete":
        blockers.append("valuation_snapshot_not_complete")
    if int(portfolio.get("ledger_cutoff_id") or 0) <= 0:
        blockers.append("ledger_cutoff_missing")
    if not portfolio.get("ledger_fingerprint"):
        blockers.append("ledger_fingerprint_missing")
    if not portfolio.get("quote_set_fingerprint"):
        blockers.append("quote_set_fingerprint_missing")
    if str(account_truth.get("gate_status") or "blocked") != "pass":
        blockers.append("account_truth_gate_not_passed")
    if str(market_data.get("source_health") or "unknown") not in (
        _TRUSTED_MARKET_STATUSES
    ):
        blockers.append("market_data_not_complete")
    incomplete_candidates = []
    for item in candidates:
        data = _mapping(_mapping(item.get("evidence")).get("data_freshness"))
        status = str(data.get("status") or "unknown").strip().lower()
        source = str(data.get("quote_source") or "").strip().lower()
        if (
            status not in _TRUSTED_CANDIDATE_DATA_STATUSES
            or source in _UNTRUSTED_ESTIMATE_SOURCES
        ):
            incomplete_candidates.append(_candidate_ref(item))
    if incomplete_candidates:
        blockers.append("candidate_data_not_complete")
    return DecisionQualityDimension(
        name="data_complete",
        passed=not blockers,
        status="pass" if not blockers else "blocked",
        evidence={
            "fact_authority": portfolio.get("fact_authority"),
            "valuation_snapshot_id": portfolio.get("valuation_snapshot_id"),
            "valuation_status": portfolio.get("valuation_status"),
            "ledger_cutoff_id": int(portfolio.get("ledger_cutoff_id") or 0),
            "ledger_fingerprint": portfolio.get("ledger_fingerprint"),
            "quote_set_fingerprint": portfolio.get("quote_set_fingerprint"),
            "market_data_status": market_data.get("source_health"),
            "account_truth_gate_status": account_truth.get("gate_status"),
            "incomplete_candidates": incomplete_candidates,
        },
        blockers=tuple(blockers),
    )


def _risk_checked_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="risk_checked",
            passed=True,
            status="not_applicable_no_action",
            evidence={"candidate_count": 0, "checked_count": 0},
        )
    unchecked = []
    checked = []
    for candidate in candidates:
        risk = _mapping(_mapping(candidate.get("evidence")).get("risk_gate"))
        status = str(risk.get("status") or "not_checked")
        reference = _candidate_ref(candidate)
        if status in _CHECKED_RISK_STATUSES and risk.get("decision_id"):
            checked.append(reference)
        else:
            unchecked.append(reference)
    return DecisionQualityDimension(
        name="risk_checked",
        passed=not unchecked,
        status="pass" if not unchecked else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "checked_count": len(checked),
            "checked_candidates": checked,
            "unchecked_candidates": unchecked,
        },
        blockers=("pre_trade_risk_evidence_incomplete",) if unchecked else (),
    )


def _benchmark_aware_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="benchmark_aware",
            passed=True,
            status="not_applicable_no_strategy_action",
            evidence={"candidate_count": 0, "aware_count": 0},
        )
    aware: list[str] = []
    missing: list[str] = []
    benchmark_evidence: list[dict[str, Any]] = []
    for candidate in candidates:
        validation = _mapping(
            _mapping(candidate.get("evidence")).get("after_cost_oos_validation")
        )
        oos = _mapping(validation.get("oos_validation"))
        supplied = (
            validation.get("status") == "attached"
            and validation.get("backtest_result_id") is not None
            and bool(str(oos.get("benchmark_role") or "").strip())
            and oos.get("benchmark_return") is not None
            and oos.get("validation_status") != "benchmark_not_supplied"
        )
        reference = _candidate_ref(candidate)
        if supplied:
            aware.append(reference)
        else:
            missing.append(reference)
        benchmark_evidence.append(
            {
                "candidate": reference,
                "backtest_result_id": validation.get("backtest_result_id"),
                "benchmark_role": oos.get("benchmark_role"),
                "benchmark_return": oos.get("benchmark_return"),
                "passed_benchmark": oos.get("passed_benchmark"),
                "validation_status": oos.get("validation_status"),
            }
        )
    return DecisionQualityDimension(
        name="benchmark_aware",
        passed=not missing,
        status="pass" if not missing else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "aware_count": len(aware),
            "missing_candidates": missing,
            "benchmarks": benchmark_evidence,
        },
        blockers=("benchmark_evidence_incomplete",) if missing else (),
    )


def _journaled_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="journaled",
            passed=True,
            status="satisfied_by_daily_capture",
            evidence={
                "candidate_count": 0,
                "journaled_count": 0,
                "no_action_decision_will_be_journaled_by_capture": True,
            },
        )
    journaled: list[str] = []
    missing: list[str] = []
    for candidate in candidates:
        evidence = _mapping(candidate.get("evidence"))
        journal = _mapping(evidence.get("journal"))
        signal = _mapping(evidence.get("signal"))
        reference = _candidate_ref(candidate)
        if journal.get("has_journal_entry") is True and signal.get("id") is not None:
            journaled.append(reference)
        else:
            missing.append(reference)
    return DecisionQualityDimension(
        name="journaled",
        passed=not missing,
        status="pass" if not missing else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "journaled_count": len(journaled),
            "missing_candidates": missing,
        },
        blockers=("signal_journal_evidence_incomplete",) if missing else (),
    )


def _later_reviewable_dimension(
    candidates: list[dict[str, Any]],
) -> DecisionQualityDimension:
    if not candidates:
        return DecisionQualityDimension(
            name="later_reviewable",
            passed=True,
            status="satisfied_by_content_addressed_capture",
            evidence={
                "candidate_count": 0,
                "reviewable_count": 0,
                "capture_is_replayable": True,
            },
        )
    reviewable: list[str] = []
    missing: list[str] = []
    for candidate in candidates:
        evidence = _mapping(candidate.get("evidence"))
        journal = _mapping(evidence.get("journal"))
        signal_id = _mapping(evidence.get("signal")).get("id")
        reference = _candidate_ref(candidate)
        try:
            stable_signal_id = int(signal_id) > 0
        except (TypeError, ValueError):
            stable_signal_id = False
        if stable_signal_id and journal.get("has_journal_entry") is True:
            reviewable.append(reference)
        else:
            missing.append(reference)
    return DecisionQualityDimension(
        name="later_reviewable",
        passed=not missing,
        status="pass" if not missing else "blocked",
        evidence={
            "candidate_count": len(candidates),
            "reviewable_count": len(reviewable),
            "missing_candidates": missing,
            "review_contract": "karkinos.decision_outcome_review.v1",
        },
        blockers=("post_decision_review_identity_incomplete",) if missing else (),
    )


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = _mapping(candidate.get("evidence"))
    signal = _mapping(evidence.get("signal"))
    risk = _mapping(evidence.get("risk_gate"))
    validation = _mapping(evidence.get("after_cost_oos_validation"))
    oos = _mapping(validation.get("oos_validation"))
    journal = _mapping(evidence.get("journal"))
    data = _mapping(evidence.get("data_freshness"))
    return {
        "action_id": candidate.get("action_id"),
        "action": candidate.get("action"),
        "symbol": candidate.get("symbol"),
        "target_weight": candidate.get("target_weight"),
        "signal_id": signal.get("id"),
        "risk_decision_id": risk.get("decision_id"),
        "risk_status": risk.get("status"),
        "backtest_result_id": validation.get("backtest_result_id"),
        "benchmark_role": oos.get("benchmark_role"),
        "benchmark_return": oos.get("benchmark_return"),
        "benchmark_validation_status": oos.get("validation_status"),
        "data_status": data.get("status"),
        "journaled": journal.get("has_journal_entry") is True,
    }


def _candidate_ref(candidate: dict[str, Any]) -> str:
    return f"{candidate.get('action_id') or 'action'}:{candidate.get('symbol') or 'unknown'}"


def _capture_from_row(row: sqlite3.Row) -> StoredDecisionQualityCapture:
    return StoredDecisionQualityCapture(
        snapshot_id=str(row["snapshot_id"]),
        decision_date=str(row["decision_date"]),
        idempotency_key=str(row["idempotency_key"]),
        request=_json_object(row["request_json"]),
        request_fingerprint=str(row["request_fingerprint"]),
        target=_json_object(row["target_json"]),
        target_fingerprint=str(row["target_fingerprint"]),
        qualified=bool(row["qualified"]),
        captured_at=str(row["captured_at"]),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError("stored decision quality JSON must be an object")
    return parsed


def _event_hash(
    *,
    snapshot_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "snapshot_id": snapshot_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )
