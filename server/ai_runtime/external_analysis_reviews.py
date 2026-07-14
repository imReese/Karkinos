"""Human review and provider-quality evidence for external AI research.

The review is an append-only disposition of one exact Phase 1.10 analysis. It
may mark that output as reviewed research, but it deliberately cannot create a
memory artifact, provider promotion, Decision input, financial fact, or any
trading/capital authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from .contracts import (
    ArtifactKind,
    JsonObject,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)
from .external_memory_informed_analysis import (
    ExternalMemoryAnalysisResult,
    HumanExternalMemoryAnalysisService,
)
from .store import IdempotencyConflict

EXTERNAL_ANALYSIS_REVIEW_CONFIRMATION = (
    "record_external_analysis_review_without_memory_decision_or_trade_authority"
)
EXTERNAL_ANALYSIS_REVIEW_CONTRACT_VERSION = "karkinos.ai.external_analysis_review.v1"
_EXPECTED_ARTIFACT_KINDS = (
    ArtifactKind.CLAIM,
    ArtifactKind.DEBATE,
    ArtifactKind.REPORT,
)
_EXPECTED_STAGE_COUNT = 3


class ExternalAnalysisReviewDecision(StrEnum):
    ACCEPT_AS_REVIEWED_RESEARCH = "accept_as_reviewed_research"
    REQUEST_REVISION = "request_revision"
    REJECT = "reject"


class ExternalAnalysisReviewEffectiveStatus(StrEnum):
    REVIEWED_RESEARCH = "reviewed_research"
    REVISION_REQUESTED = "revision_requested"
    REJECTED = "rejected"
    INVALIDATED_BY_EVIDENCE_DRIFT = "invalidated_by_evidence_drift"


class ExternalAnalysisReviewRejected(ValueError):
    """Raised when an external analysis disposition fails its local gates."""


@dataclass(frozen=True)
class ExternalAnalysisQualityRubric:
    evidence_grounding: int
    contradiction_handling: int
    uncertainty_calibration: int
    decision_usefulness: int

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_grounding",
            "contradiction_handling",
            "uncertainty_calibration",
            "decision_usefulness",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field_name} must be an integer")
            if value < 1 or value > 5:
                raise ValueError(f"{field_name} must be between 1 and 5")

    @property
    def total(self) -> int:
        return sum(self.to_dict().values())

    def to_dict(self) -> dict[str, int]:
        return {
            "evidence_grounding": self.evidence_grounding,
            "contradiction_handling": self.contradiction_handling,
            "uncertainty_calibration": self.uncertainty_calibration,
            "decision_usefulness": self.decision_usefulness,
        }


@dataclass(frozen=True)
class ProviderPricingSnapshot:
    currency: str
    prompt_price_per_million_tokens: str
    completion_price_per_million_tokens: str
    source: str
    effective_at: str
    schema_version: str = "karkinos.ai.provider_pricing_snapshot.v1"

    def __post_init__(self) -> None:
        currency = self.currency.strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("pricing currency must be a three-letter code")
        object.__setattr__(self, "currency", currency)
        for field_name in (
            "prompt_price_per_million_tokens",
            "completion_price_per_million_tokens",
        ):
            normalized = _decimal_text(
                _non_negative_decimal(getattr(self, field_name), field_name)
            )
            object.__setattr__(self, field_name, normalized)
        for field_name in ("source", "effective_at", "schema_version"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"pricing {field_name} must not be empty")
        instant = datetime.fromisoformat(self.effective_at)
        if instant.tzinfo is None:
            raise ValueError("pricing effective_at must include timezone")

    def to_dict(self) -> JsonObject:
        return {
            "currency": self.currency,
            "prompt_price_per_million_tokens": (self.prompt_price_per_million_tokens),
            "completion_price_per_million_tokens": (
                self.completion_price_per_million_tokens
            ),
            "source": self.source,
            "effective_at": self.effective_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class HumanExternalAnalysisReviewRequest:
    idempotency_key: str
    reviewed_by: str
    decision: ExternalAnalysisReviewDecision
    note: str
    quality_rubric: ExternalAnalysisQualityRubric
    factual_error_count: int
    unsupported_claim_count: int
    pricing_snapshot: ProviderPricingSnapshot | None
    pricing_unavailable_reason: str | None
    confirmation: str
    schema_version: str = "karkinos.ai.external_analysis_review_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        for field_name in ("factual_error_count", "unsupported_claim_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        unavailable_reason = str(self.pricing_unavailable_reason or "").strip()
        if self.pricing_snapshot is None and not unavailable_reason:
            raise ValueError(
                "pricing_unavailable_reason is required without a pricing snapshot"
            )
        if self.pricing_snapshot is not None and unavailable_reason:
            raise ValueError(
                "pricing snapshot and pricing_unavailable_reason are mutually exclusive"
            )
        if self.pricing_snapshot is None:
            object.__setattr__(self, "pricing_unavailable_reason", unavailable_reason)
        if self.confirmation != EXTERNAL_ANALYSIS_REVIEW_CONFIRMATION:
            raise ValueError(
                "explicit external analysis review confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "reviewed_by": self.reviewed_by,
            "decision": self.decision.value,
            "note": self.note,
            "quality_rubric": self.quality_rubric.to_dict(),
            "factual_error_count": self.factual_error_count,
            "unsupported_claim_count": self.unsupported_claim_count,
            "pricing_snapshot": (
                self.pricing_snapshot.to_dict() if self.pricing_snapshot else None
            ),
            "pricing_unavailable_reason": self.pricing_unavailable_reason,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalAnalysisReviewTarget:
    analysis_id: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    provider_id: str
    model_id: str
    prompt_version: str
    report_artifact_id: str | None
    quality_evidence: JsonObject
    fingerprint: str
    acceptance_errors: tuple[str, ...]

    @property
    def acceptance_eligible(self) -> bool:
        return not self.acceptance_errors and self.report_artifact_id is not None


@dataclass(frozen=True)
class StoredExternalAnalysisReview:
    review_id: str
    analysis_id: str
    workflow_id: str
    idempotency_key: str
    request: HumanExternalAnalysisReviewRequest
    request_fingerprint: str
    analysis_target_fingerprint: str
    report_artifact_id: str | None
    provider_id: str
    model_id: str
    prompt_version: str
    quality_evidence: JsonObject
    cost_evidence: JsonObject
    created_at: str


@dataclass(frozen=True)
class ExternalAnalysisReviewAuditReplay:
    review_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalAnalysisReviewReplay:
    review_id: str
    analysis_id: str
    valid: bool
    review_event_chain_valid: bool
    analysis_target_binding_valid: bool
    reviewed_research_eligible: bool
    effective_status: ExternalAnalysisReviewEffectiveStatus
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.external_analysis_review_replay.v1",
            "review_id": self.review_id,
            "analysis_id": self.analysis_id,
            "valid": self.valid,
            "review_event_chain_valid": self.review_event_chain_valid,
            "analysis_target_binding_valid": self.analysis_target_binding_valid,
            "reviewed_research_eligible": self.reviewed_research_eligible,
            "effective_status": self.effective_status.value,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "memory_recall_eligible": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ExternalAnalysisReviewResult:
    review: StoredExternalAnalysisReview
    current_target: ExternalAnalysisReviewTarget
    audit_replay: ExternalAnalysisReviewAuditReplay
    reused: bool

    @property
    def target_binding_valid(self) -> bool:
        return (
            self.review.analysis_target_fingerprint == self.current_target.fingerprint
        )

    @property
    def reviewer_found_blocking_errors(self) -> bool:
        return (
            self.review.request.factual_error_count > 0
            or self.review.request.unsupported_claim_count > 0
        )

    @property
    def reviewed_research_eligible(self) -> bool:
        return (
            self.review.request.decision
            == ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
            and self.target_binding_valid
            and self.current_target.acceptance_eligible
            and not self.reviewer_found_blocking_errors
            and self.audit_replay.valid
        )

    @property
    def effective_status(self) -> ExternalAnalysisReviewEffectiveStatus:
        decision = self.review.request.decision
        if decision == ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH:
            if self.reviewed_research_eligible:
                return ExternalAnalysisReviewEffectiveStatus.REVIEWED_RESEARCH
            return ExternalAnalysisReviewEffectiveStatus.INVALIDATED_BY_EVIDENCE_DRIFT
        if decision == ExternalAnalysisReviewDecision.REQUEST_REVISION:
            return ExternalAnalysisReviewEffectiveStatus.REVISION_REQUESTED
        return ExternalAnalysisReviewEffectiveStatus.REJECTED

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.target_binding_valid:
            reasons.append("external_analysis_target_fingerprint_drift")
        reasons.extend(self.current_target.acceptance_errors)
        reasons.extend(self.audit_replay.errors)
        if self.review.request.factual_error_count > 0:
            reasons.append("reviewer_identified_factual_errors")
        if self.review.request.unsupported_claim_count > 0:
            reasons.append("reviewer_identified_unsupported_claims")
        return tuple(dict.fromkeys(reasons))

    @property
    def cost_evidence(self) -> JsonObject:
        return dict(self.review.cost_evidence)

    def replay(self) -> ExternalAnalysisReviewReplay:
        valid = (
            self.audit_replay.valid
            and self.target_binding_valid
            and (
                self.review.request.decision
                != ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
                or (
                    self.current_target.acceptance_eligible
                    and not self.reviewer_found_blocking_errors
                )
            )
        )
        return ExternalAnalysisReviewReplay(
            review_id=self.review.review_id,
            analysis_id=self.review.analysis_id,
            valid=valid,
            review_event_chain_valid=self.audit_replay.valid,
            analysis_target_binding_valid=self.target_binding_valid,
            reviewed_research_eligible=self.reviewed_research_eligible,
            effective_status=self.effective_status,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        request = self.review.request
        quality = dict(self.review.quality_evidence)
        quality["human_rubric"] = request.quality_rubric.to_dict()
        quality["human_rubric_total"] = request.quality_rubric.total
        quality["human_rubric_maximum"] = 20
        quality["factual_error_count"] = request.factual_error_count
        quality["unsupported_claim_count"] = request.unsupported_claim_count
        return {
            "schema_version": EXTERNAL_ANALYSIS_REVIEW_CONTRACT_VERSION,
            "review_id": self.review.review_id,
            "analysis_id": self.review.analysis_id,
            "workflow_id": self.review.workflow_id,
            "decision": request.decision.value,
            "effective_status": self.effective_status.value,
            "note": request.note,
            "reviewed_by": request.reviewed_by,
            "created_at": self.review.created_at,
            "report_artifact_id": self.review.report_artifact_id,
            "provider_id": self.review.provider_id,
            "model_id": self.review.model_id,
            "prompt_version": self.review.prompt_version,
            "stored_analysis_target_fingerprint": (
                self.review.analysis_target_fingerprint
            ),
            "current_analysis_target_fingerprint": self.current_target.fingerprint,
            "analysis_target_binding_valid": self.target_binding_valid,
            "analysis_acceptance_eligible": (self.current_target.acceptance_eligible),
            "reviewed_research_eligible": self.reviewed_research_eligible,
            "quality_evidence": quality,
            "current_quality_evidence": dict(self.current_target.quality_evidence),
            "quality_evidence_binding_valid": (
                content_fingerprint(self.review.quality_evidence)
                == content_fingerprint(self.current_target.quality_evidence)
            ),
            "cost_evidence": self.cost_evidence,
            "invalidation_reasons": list(self.invalidation_reasons),
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "reused": self.reused,
            "human_review_required": True,
            "review_external_model_invocation_count": 0,
            "research_output_is_account_fact": False,
            "memory_artifact_created": False,
            "memory_recall_eligible": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_analysis_reviews (
    review_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL UNIQUE,
    workflow_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    analysis_target_fingerprint TEXT NOT NULL,
    report_artifact_id TEXT,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    quality_evidence_json TEXT NOT NULL,
    cost_evidence_json TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN (
        'accept_as_reviewed_research', 'request_revision', 'reject'
    )),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_memory_informed_analyses(analysis_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_analysis_reviews_created
ON ai_external_analysis_reviews(created_at DESC, review_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_analysis_review_events (
    review_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id, sequence),
    FOREIGN KEY(review_id) REFERENCES ai_external_analysis_reviews(review_id)
);
"""


class ExternalAnalysisReviewStore:
    """Append-only human reviews and their one-event audit chains."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalAnalysisReview | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_analysis_reviews "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return _review_from_row(row) if row is not None else None

    def record(
        self,
        *,
        target: ExternalAnalysisReviewTarget,
        request: HumanExternalAnalysisReviewRequest,
        created_at: str,
    ) -> tuple[StoredExternalAnalysisReview, bool]:
        identity = {
            "analysis_id": target.analysis_id,
            "request_fingerprint": request.fingerprint,
            "analysis_target_fingerprint": target.fingerprint,
        }
        review_id = f"ai-external-review-{content_fingerprint(identity)[:24]}"
        cost_evidence = _cost_evidence(request, target.quality_evidence)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_external_analysis_reviews "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _review_from_row(existing)
                if (
                    stored.analysis_id != target.analysis_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "external analysis review idempotency key was reused "
                        "with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT review_id FROM ai_external_analysis_reviews "
                "WHERE analysis_id = ?",
                (target.analysis_id,),
            ).fetchone()
            if final is not None:
                raise ExternalAnalysisReviewRejected(
                    "external analysis review is already final"
                )
            conn.execute(
                """
                INSERT INTO ai_external_analysis_reviews (
                    review_id, analysis_id, workflow_id, idempotency_key,
                    request_json, request_fingerprint,
                    analysis_target_fingerprint, report_artifact_id,
                    provider_id, model_id, prompt_version,
                    quality_evidence_json, cost_evidence_json, reviewed_by,
                    decision, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    target.analysis_id,
                    target.workflow_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    target.report_artifact_id,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    canonical_json(target.quality_evidence),
                    canonical_json(cost_evidence),
                    request.reviewed_by,
                    request.decision.value,
                    request.note,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                review_id=review_id,
                event_type="external_analysis_review_recorded",
                payload={
                    "analysis_id": target.analysis_id,
                    "analysis_target_fingerprint": target.fingerprint,
                    "decision": request.decision.value,
                    "report_artifact_id": target.report_artifact_id,
                    "provider_id": target.provider_id,
                    "model_id": target.model_id,
                    "prompt_version": target.prompt_version,
                    "request_fingerprint": request.fingerprint,
                    "quality_evidence_fingerprint": content_fingerprint(
                        target.quality_evidence
                    ),
                    "cost_evidence_fingerprint": content_fingerprint(cost_evidence),
                    "memory_recall_eligible": False,
                    "provider_promotion_eligible": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_analysis_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external analysis review persistence failed")
        return _review_from_row(row), False

    def get(self, review_id: str) -> StoredExternalAnalysisReview:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_analysis_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"external analysis review not found: {review_id}")
        return _review_from_row(row)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalAnalysisReview, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("external analysis review limit must be between 1 and 200")
        sql = "SELECT * FROM ai_external_analysis_reviews"
        params: list[object] = []
        if analysis_id is not None:
            sql += " WHERE analysis_id = ?"
            params.append(analysis_id)
        sql += " ORDER BY created_at DESC, review_id DESC LIMIT ?"
        params.append(limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(_review_from_row(row) for row in rows)

    def verify_replay(self, review_id: str) -> ExternalAnalysisReviewAuditReplay:
        review = self.get(review_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_external_analysis_review_events "
                "WHERE review_id = ? ORDER BY sequence",
                (review_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("external analysis review sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("external analysis review previous hash drifted")
            expected_hash = _event_hash(
                review_id=review_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("external analysis review event hash drifted")
            expected = {
                "analysis_id": review.analysis_id,
                "analysis_target_fingerprint": review.analysis_target_fingerprint,
                "decision": review.request.decision.value,
                "report_artifact_id": review.report_artifact_id,
                "provider_id": review.provider_id,
                "model_id": review.model_id,
                "prompt_version": review.prompt_version,
                "request_fingerprint": review.request_fingerprint,
                "quality_evidence_fingerprint": content_fingerprint(
                    review.quality_evidence
                ),
                "cost_evidence_fingerprint": content_fingerprint(review.cost_evidence),
            }
            for key, value in expected.items():
                if payload.get(key) != value:
                    errors.append(f"external analysis review {key} drifted")
            if payload.get("memory_recall_eligible") is not False:
                errors.append("external analysis review memory boundary drifted")
            if payload.get("provider_promotion_eligible") is not False:
                errors.append("external analysis review provider boundary drifted")
            if payload.get("authority_effect") != "none":
                errors.append("external analysis review authority boundary drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append("external analysis review must contain exactly one event")
        return ExternalAnalysisReviewAuditReplay(
            review_id=review_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        review_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash FROM ai_external_analysis_review_events "
            "WHERE review_id = ? ORDER BY sequence DESC LIMIT 1",
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
            INSERT INTO ai_external_analysis_review_events (
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


class HumanExternalAnalysisReviewService:
    """Record and revalidate one human disposition without model I/O."""

    def __init__(
        self,
        *,
        analysis_service: HumanExternalMemoryAnalysisService,
        review_store: ExternalAnalysisReviewStore,
        now: Callable[[], str],
    ) -> None:
        self._analysis_service = analysis_service
        self._review_store = review_store
        self._now = now

    def review(
        self,
        analysis_id: str,
        request: HumanExternalAnalysisReviewRequest,
    ) -> ExternalAnalysisReviewResult:
        existing = self._review_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.analysis_id != analysis_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "external analysis review idempotency key was reused with "
                    "different input"
                )
            return self._result(existing, reused=True)

        analysis = self._analysis_service.get(analysis_id)
        target = _review_target(analysis)
        if request.decision == (
            ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
        ):
            blockers = list(target.acceptance_errors)
            if request.factual_error_count:
                blockers.append("reviewer_identified_factual_errors")
            if request.unsupported_claim_count:
                blockers.append("reviewer_identified_unsupported_claims")
            if blockers:
                raise ExternalAnalysisReviewRejected(
                    "external analysis cannot become reviewed research: "
                    + "; ".join(dict.fromkeys(blockers))
                )
        review, reused = self._review_store.record(
            target=target,
            request=request,
            created_at=self._now(),
        )
        return self._result(review, reused=reused)

    def get(self, review_id: str) -> ExternalAnalysisReviewResult:
        return self._result(self._review_store.get(review_id), reused=True)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ExternalAnalysisReviewResult, ...]:
        return tuple(
            self._result(review, reused=True)
            for review in self._review_store.list(
                analysis_id=analysis_id,
                limit=limit,
            )
        )

    def replay(self, review_id: str) -> ExternalAnalysisReviewReplay:
        return self.get(review_id).replay()

    def _result(
        self,
        review: StoredExternalAnalysisReview,
        *,
        reused: bool,
    ) -> ExternalAnalysisReviewResult:
        target = _review_target(self._analysis_service.get(review.analysis_id))
        return ExternalAnalysisReviewResult(
            review=review,
            current_target=target,
            audit_replay=self._review_store.verify_replay(review.review_id),
            reused=reused,
        )


def _review_target(
    analysis: ExternalMemoryAnalysisResult,
) -> ExternalAnalysisReviewTarget:
    errors = list(analysis.binding_errors)
    if analysis.workflow.status != WorkflowStatus.COMPLETED:
        errors.append(
            f"analysis_workflow_not_completed:{analysis.workflow.status.value}"
        )
    if analysis.workflow.partial_result:
        errors.append("analysis_workflow_is_partial")
    if not analysis.audit_valid:
        errors.append("analysis_audit_invalid")
    if not analysis.current_evidence_reads_complete:
        errors.append("analysis_current_evidence_reads_incomplete")
    if not analysis.replay_valid:
        errors.append("analysis_replay_invalid")

    artifact_evidence: list[JsonObject] = []
    report_artifacts = []
    citation_item_count = 0
    cited_item_count = 0
    latencies: list[int] = []
    for artifact in analysis.artifacts:
        actual_fingerprint = content_fingerprint(
            {
                "workflow_id": artifact.workflow_id,
                "run_id": artifact.run_id,
                "stage_id": artifact.stage_id,
                "role_id": artifact.role_id,
                "kind": artifact.kind.value,
                "content": dict(artifact.content),
                "evidence_reference_ids": list(artifact.evidence_reference_ids),
            }
        )
        if actual_fingerprint != artifact.fingerprint:
            errors.append(f"artifact_fingerprint_drift:{artifact.artifact_id}")
        if artifact.content.get("authoritative") is not False:
            errors.append(f"artifact_authority_flag_invalid:{artifact.artifact_id}")
        if artifact.content.get("requires_human_review") is not True:
            errors.append(f"artifact_human_review_flag_invalid:{artifact.artifact_id}")
        if artifact.content.get("authority_effect") != "none":
            errors.append(f"artifact_authority_effect_invalid:{artifact.artifact_id}")
        allowed_ids = set(artifact.evidence_reference_ids)
        for field_name in ("findings", "counterpoints"):
            items = artifact.content.get(field_name)
            if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
                errors.append(f"artifact_{field_name}_invalid:{artifact.artifact_id}")
                continue
            for item in items:
                citation_item_count += 1
                references = (
                    item.get("evidence_reference_ids")
                    if isinstance(item, Mapping)
                    else None
                )
                if (
                    isinstance(references, Sequence)
                    and not isinstance(references, (str, bytes))
                    and references
                    and all(str(reference) in allowed_ids for reference in references)
                ):
                    cited_item_count += 1
                else:
                    errors.append(f"artifact_citation_invalid:{artifact.artifact_id}")
        provenance = artifact.content.get("provider_provenance")
        latency = (
            provenance.get("latency_ms") if isinstance(provenance, Mapping) else None
        )
        if isinstance(latency, int) and not isinstance(latency, bool) and latency >= 0:
            latencies.append(latency)
        artifact_evidence.append(
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind.value,
                "stage_id": artifact.stage_id,
                "stored_fingerprint": artifact.fingerprint,
                "actual_fingerprint": actual_fingerprint,
                "evidence_reference_ids": list(artifact.evidence_reference_ids),
            }
        )
        if artifact.kind == ArtifactKind.REPORT:
            report_artifacts.append(artifact)

    if tuple(item.kind for item in analysis.artifacts) != _EXPECTED_ARTIFACT_KINDS:
        errors.append("analysis_artifact_lifecycle_incomplete")
    if len(report_artifacts) != 1:
        errors.append("analysis_requires_exactly_one_report_artifact")
    report_artifact_id = (
        report_artifacts[0].artifact_id if len(report_artifacts) == 1 else None
    )

    model_call_evidence = [item.to_dict() for item in analysis.model_calls]
    if len(analysis.model_calls) != _EXPECTED_STAGE_COUNT:
        errors.append("analysis_model_call_lifecycle_incomplete")
    if any(item.status != "completed" for item in analysis.model_calls):
        errors.append("analysis_model_call_not_completed")
    prompt_values = [item.usage.get("prompt_tokens") for item in analysis.model_calls]
    completion_values = [
        item.usage.get("completion_tokens") for item in analysis.model_calls
    ]
    usage_complete = (
        len(prompt_values) == _EXPECTED_STAGE_COUNT
        and all(isinstance(item, int) and item >= 0 for item in prompt_values)
        and all(isinstance(item, int) and item >= 0 for item in completion_values)
    )
    prompt_tokens = sum(prompt_values) if usage_complete else None
    completion_tokens = sum(completion_values) if usage_complete else None
    total_tokens = (
        int(prompt_tokens) + int(completion_tokens)
        if prompt_tokens is not None and completion_tokens is not None
        else None
    )
    latency_complete = (
        len(latencies) == len(analysis.artifacts) == (_EXPECTED_STAGE_COUNT)
    )
    quality_evidence: JsonObject = {
        "status": (
            "complete"
            if usage_complete
            and latency_complete
            and cited_item_count == citation_item_count
            and len(analysis.artifacts) == _EXPECTED_STAGE_COUNT
            else "partial"
        ),
        "model_call_count": len(analysis.model_calls),
        "completed_model_call_count": sum(
            item.status == "completed" for item in analysis.model_calls
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "usage_status": "complete" if usage_complete else "partial_or_missing",
        "latency_status": ("complete" if latency_complete else "partial_or_missing"),
        "total_latency_ms": sum(latencies) if latency_complete else None,
        "maximum_stage_latency_ms": max(latencies) if latency_complete else None,
        "reasoning_present_stage_count": sum(
            item.reasoning_content_present for item in analysis.model_calls
        ),
        "reasoning_content_persisted": False,
        "artifact_count": len(analysis.artifacts),
        "citation_item_count": citation_item_count,
        "cited_item_count": cited_item_count,
        "citation_status": (
            "complete"
            if citation_item_count > 0 and cited_item_count == citation_item_count
            else "incomplete"
        ),
        "current_evidence_read_count": sum(
            item.get("status") == "completed" for item in analysis.tool_calls
        ),
        "current_evidence_reads_complete": (analysis.current_evidence_reads_complete),
        "provider_reported_usage": usage_complete,
        "provider_invoice": False,
    }
    target_payload = {
        "analysis_id": analysis.record.analysis_id,
        "workflow_id": analysis.record.workflow_id,
        "workflow_status": analysis.workflow.status.value,
        "workflow_failure_code": analysis.workflow.failure_code,
        "partial_result": analysis.workflow.partial_result,
        "context_snapshot_id": analysis.record.context_snapshot_id,
        "context_fingerprint": analysis.record.context_fingerprint,
        "retrieval_target_fingerprint": (analysis.record.retrieval_target_fingerprint),
        "provider_id": analysis.record.provider_id,
        "model_id": analysis.record.model_id,
        "prompt_version": analysis.record.prompt_version,
        "binding_validity": analysis.binding_validity,
        "binding_errors": list(analysis.binding_errors),
        "current_evidence_reads_complete": (analysis.current_evidence_reads_complete),
        "artifacts": artifact_evidence,
        "model_calls": model_call_evidence,
        "tool_calls": [dict(item) for item in analysis.tool_calls],
        "quality_evidence": quality_evidence,
        "report_artifact_id": report_artifact_id,
        "audit": {
            "valid": analysis.audit_valid,
            "event_count": analysis.audit_event_count,
            "last_event_hash": analysis.audit_last_event_hash,
            "errors": list(analysis.audit_errors),
        },
    }
    return ExternalAnalysisReviewTarget(
        analysis_id=analysis.record.analysis_id,
        workflow_id=analysis.record.workflow_id,
        context_snapshot_id=analysis.record.context_snapshot_id,
        context_fingerprint=analysis.record.context_fingerprint,
        provider_id=analysis.record.provider_id,
        model_id=analysis.record.model_id,
        prompt_version=analysis.record.prompt_version,
        report_artifact_id=report_artifact_id,
        quality_evidence=quality_evidence,
        fingerprint=content_fingerprint(target_payload),
        acceptance_errors=tuple(dict.fromkeys(errors)),
    )


def _event_hash(
    *,
    review_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
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


def _review_from_row(row: sqlite3.Row) -> StoredExternalAnalysisReview:
    payload = json.loads(str(row["request_json"]))
    rubric_payload = payload["quality_rubric"]
    pricing_payload = payload.get("pricing_snapshot")
    request = HumanExternalAnalysisReviewRequest(
        idempotency_key=str(payload["idempotency_key"]),
        reviewed_by=str(payload["reviewed_by"]),
        decision=ExternalAnalysisReviewDecision(str(payload["decision"])),
        note=str(payload["note"]),
        quality_rubric=ExternalAnalysisQualityRubric(
            evidence_grounding=int(rubric_payload["evidence_grounding"]),
            contradiction_handling=int(rubric_payload["contradiction_handling"]),
            uncertainty_calibration=int(rubric_payload["uncertainty_calibration"]),
            decision_usefulness=int(rubric_payload["decision_usefulness"]),
        ),
        factual_error_count=int(payload["factual_error_count"]),
        unsupported_claim_count=int(payload["unsupported_claim_count"]),
        pricing_snapshot=(
            ProviderPricingSnapshot(
                currency=str(pricing_payload["currency"]),
                prompt_price_per_million_tokens=str(
                    pricing_payload["prompt_price_per_million_tokens"]
                ),
                completion_price_per_million_tokens=str(
                    pricing_payload["completion_price_per_million_tokens"]
                ),
                source=str(pricing_payload["source"]),
                effective_at=str(pricing_payload["effective_at"]),
                schema_version=str(pricing_payload["schema_version"]),
            )
            if isinstance(pricing_payload, Mapping)
            else None
        ),
        pricing_unavailable_reason=(
            str(payload["pricing_unavailable_reason"])
            if payload.get("pricing_unavailable_reason") is not None
            else None
        ),
        confirmation=str(payload["confirmation"]),
        schema_version=str(payload["schema_version"]),
    )
    return StoredExternalAnalysisReview(
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        workflow_id=str(row["workflow_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        analysis_target_fingerprint=str(row["analysis_target_fingerprint"]),
        report_artifact_id=(
            str(row["report_artifact_id"])
            if row["report_artifact_id"] is not None
            else None
        ),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        quality_evidence=dict(json.loads(str(row["quality_evidence_json"]))),
        cost_evidence=dict(json.loads(str(row["cost_evidence_json"]))),
        created_at=str(row["created_at"]),
    )


def _cost_evidence(
    request: HumanExternalAnalysisReviewRequest,
    quality_evidence: Mapping[str, object],
) -> JsonObject:
    pricing = request.pricing_snapshot
    if pricing is None:
        return {
            "status": "unpriced",
            "currency": None,
            "estimated_cost": None,
            "pricing_source": None,
            "pricing_effective_at": None,
            "pricing_unavailable_reason": request.pricing_unavailable_reason,
            "calculation": "not_performed",
            "provider_invoice": False,
        }
    prompt_tokens = quality_evidence.get("prompt_tokens")
    completion_tokens = quality_evidence.get("completion_tokens")
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        return {
            "status": "partial_usage",
            "currency": pricing.currency,
            "estimated_cost": None,
            "pricing_source": pricing.source,
            "pricing_effective_at": pricing.effective_at,
            "pricing_unavailable_reason": None,
            "calculation": "blocked_by_incomplete_provider_usage",
            "provider_invoice": False,
        }
    prompt_cost = (
        Decimal(prompt_tokens)
        * Decimal(pricing.prompt_price_per_million_tokens)
        / Decimal(1_000_000)
    )
    completion_cost = (
        Decimal(completion_tokens)
        * Decimal(pricing.completion_price_per_million_tokens)
        / Decimal(1_000_000)
    )
    return {
        "status": "priced_estimate",
        "currency": pricing.currency,
        "estimated_cost": _decimal_text(prompt_cost + completion_cost),
        "prompt_cost": _decimal_text(prompt_cost),
        "completion_cost": _decimal_text(completion_cost),
        "pricing_source": pricing.source,
        "pricing_effective_at": pricing.effective_at,
        "pricing_unavailable_reason": None,
        "calculation": "reviewer_pricing_x_provider_reported_tokens",
        "provider_invoice": False,
    }


def _non_negative_decimal(value: object, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative finite decimal")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
