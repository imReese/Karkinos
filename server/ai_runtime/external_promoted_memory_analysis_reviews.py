"""Human review of promoted-memory external research analyses.

Phase 1.15 records one immutable human disposition of the exact Phase 1.14
analysis, including its promoted-memory provenance and current-evidence
binding.  It reuses the canonical Phase 1.11 report-quality and cost evidence
calculations, but stores the result in isolated tables whose foreign key points
to the Phase 1.14 analysis contract.

Acceptance is research-domain evidence only.  It creates no memory artifact,
Decision input, financial fact, provider promotion, trade plan, broker action,
capital authorization, or execution authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .contracts import JsonObject, canonical_json, content_fingerprint
from .external_analysis_reviews import (
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ExternalAnalysisReviewEffectiveStatus,
    ProviderPricingSnapshot,
    _cost_evidence,
    _event_hash,
    _review_target,
)
from .external_promoted_memory_analysis import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION,
    ExternalPromotedMemoryAnalysisResult,
    HumanExternalPromotedMemoryAnalysisService,
)
from .store import IdempotencyConflict

EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION = (
    "record_external_promoted_memory_analysis_review_without_memory_decision_or_"
    "trade_authority"
)
EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION = (
    "karkinos.ai.external_promoted_memory_analysis_review.v1"
)
EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_memory_analysis_review_request.v1"
)


class ExternalPromotedMemoryAnalysisReviewRejected(ValueError):
    """Raised when a promoted-memory analysis disposition fails local gates."""


@dataclass(frozen=True)
class HumanExternalPromotedMemoryAnalysisReviewRequest:
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
    schema_version: str = EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.schema_version != (
            EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION
        ):
            raise ValueError("promoted-memory analysis review request version drifted")
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
        if self.confirmation != (EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION):
            raise ValueError(
                "explicit promoted-memory external analysis review confirmation "
                "is required"
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
class ExternalPromotedMemoryAnalysisReviewTarget:
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    context_snapshot_id: str
    context_fingerprint: str
    provider_id: str
    model_id: str
    prompt_version: str
    report_artifact_id: str | None
    promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    base_analysis_target_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    quality_evidence: JsonObject
    fingerprint: str
    acceptance_errors: tuple[str, ...]

    @property
    def acceptance_eligible(self) -> bool:
        return (
            not self.acceptance_errors
            and self.report_artifact_id is not None
            and bool(self.promotion_ids)
            and len(self.selected_memory_sources) == len(self.promotion_ids)
        )


@dataclass(frozen=True)
class StoredExternalPromotedMemoryAnalysisReview:
    review_id: str
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    idempotency_key: str
    request: HumanExternalPromotedMemoryAnalysisReviewRequest
    request_fingerprint: str
    analysis_target_fingerprint: str
    base_analysis_target_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    report_artifact_id: str | None
    provider_id: str
    model_id: str
    prompt_version: str
    promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    quality_evidence: JsonObject
    cost_evidence: JsonObject
    created_at: str


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewAuditReplay:
    review_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewReplay:
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
            "schema_version": (
                "karkinos.ai.external_promoted_memory_analysis_review_replay.v1"
            ),
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
            "memory_artifact_created": False,
            "memory_recall_eligible": False,
            "automatic_memory_promotion_enabled": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewResult:
    review: StoredExternalPromotedMemoryAnalysisReview
    current_target: ExternalPromotedMemoryAnalysisReviewTarget
    audit_replay: ExternalPromotedMemoryAnalysisReviewAuditReplay
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
            reasons.append("external_promoted_memory_analysis_target_fingerprint_drift")
        reasons.extend(self.current_target.acceptance_errors)
        reasons.extend(self.audit_replay.errors)
        if self.review.request.factual_error_count > 0:
            reasons.append("reviewer_identified_factual_errors")
        if self.review.request.unsupported_claim_count > 0:
            reasons.append("reviewer_identified_unsupported_claims")
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ExternalPromotedMemoryAnalysisReviewReplay:
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
        return ExternalPromotedMemoryAnalysisReviewReplay(
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
            "schema_version": (
                EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION
            ),
            "review_id": self.review.review_id,
            "analysis_id": self.review.analysis_id,
            "workflow_id": self.review.workflow_id,
            "retrieval_id": self.review.retrieval_id,
            "decision": request.decision.value,
            "effective_status": self.effective_status.value,
            "note": request.note,
            "reviewed_by": request.reviewed_by,
            "created_at": self.review.created_at,
            "report_artifact_id": self.review.report_artifact_id,
            "provider_id": self.review.provider_id,
            "model_id": self.review.model_id,
            "prompt_version": self.review.prompt_version,
            "promotion_ids": list(self.review.promotion_ids),
            "selected_memory_sources": [
                dict(item) for item in self.review.selected_memory_sources
            ],
            "stored_source_retrieval_target_fingerprint": (
                self.review.source_retrieval_target_fingerprint
            ),
            "current_source_retrieval_target_fingerprint": (
                self.current_target.source_retrieval_target_fingerprint
            ),
            "stored_base_analysis_target_fingerprint": (
                self.review.base_analysis_target_fingerprint
            ),
            "current_base_analysis_target_fingerprint": (
                self.current_target.base_analysis_target_fingerprint
            ),
            "stored_analysis_target_fingerprint": (
                self.review.analysis_target_fingerprint
            ),
            "current_analysis_target_fingerprint": self.current_target.fingerprint,
            "analysis_target_binding_valid": self.target_binding_valid,
            "analysis_acceptance_eligible": self.current_target.acceptance_eligible,
            "reviewed_research_eligible": self.reviewed_research_eligible,
            "quality_evidence": quality,
            "current_quality_evidence": dict(self.current_target.quality_evidence),
            "quality_evidence_binding_valid": (
                content_fingerprint(self.review.quality_evidence)
                == content_fingerprint(self.current_target.quality_evidence)
            ),
            "cost_evidence": dict(self.review.cost_evidence),
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
            "automatic_memory_promotion_enabled": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_promoted_memory_analysis_reviews (
    review_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL UNIQUE,
    workflow_id TEXT NOT NULL,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    analysis_target_fingerprint TEXT NOT NULL,
    base_analysis_target_fingerprint TEXT NOT NULL,
    source_retrieval_target_fingerprint TEXT,
    report_artifact_id TEXT,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    promotion_ids_json TEXT NOT NULL,
    selected_memory_sources_json TEXT NOT NULL,
    quality_evidence_json TEXT NOT NULL,
    cost_evidence_json TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN (
        'accept_as_reviewed_research', 'request_revision', 'reject'
    )),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_promoted_memory_analyses(analysis_id),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_promoted_analysis_reviews_created
ON ai_external_promoted_memory_analysis_reviews(created_at DESC, review_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_promoted_memory_analysis_review_events (
    review_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(
        event_type = 'external_promoted_memory_analysis_review_recorded'
    ),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id, sequence),
    FOREIGN KEY(review_id)
        REFERENCES ai_external_promoted_memory_analysis_reviews(review_id)
);
"""


class ExternalPromotedMemoryAnalysisReviewStore:
    """Append-only Phase 1.15 reviews and one-event audit chains."""

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
    ) -> StoredExternalPromotedMemoryAnalysisReview | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
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
        target: ExternalPromotedMemoryAnalysisReviewTarget,
        request: HumanExternalPromotedMemoryAnalysisReviewRequest,
        created_at: str,
    ) -> tuple[StoredExternalPromotedMemoryAnalysisReview, bool]:
        identity = {
            "analysis_id": target.analysis_id,
            "request_fingerprint": request.fingerprint,
            "analysis_target_fingerprint": target.fingerprint,
        }
        review_id = f"ai-external-promoted-review-{content_fingerprint(identity)[:24]}"
        cost_evidence = _cost_evidence(request, target.quality_evidence)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
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
                        "external promoted-memory analysis review idempotency key "
                        "was reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT review_id "
                "FROM ai_external_promoted_memory_analysis_reviews "
                "WHERE analysis_id = ?",
                (target.analysis_id,),
            ).fetchone()
            if final is not None:
                raise ExternalPromotedMemoryAnalysisReviewRejected(
                    "external promoted-memory analysis review is already final"
                )
            conn.execute(
                """
                INSERT INTO ai_external_promoted_memory_analysis_reviews (
                    review_id, analysis_id, workflow_id, retrieval_id,
                    idempotency_key, request_json, request_fingerprint,
                    analysis_target_fingerprint,
                    base_analysis_target_fingerprint,
                    source_retrieval_target_fingerprint, report_artifact_id,
                    provider_id, model_id, prompt_version, promotion_ids_json,
                    selected_memory_sources_json, quality_evidence_json,
                    cost_evidence_json, reviewed_by, decision, note, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    review_id,
                    target.analysis_id,
                    target.workflow_id,
                    target.retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    target.base_analysis_target_fingerprint,
                    target.source_retrieval_target_fingerprint,
                    target.report_artifact_id,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    canonical_json(list(target.promotion_ids)),
                    canonical_json(list(target.selected_memory_sources)),
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
                payload={
                    "analysis_id": target.analysis_id,
                    "workflow_id": target.workflow_id,
                    "retrieval_id": target.retrieval_id,
                    "analysis_target_fingerprint": target.fingerprint,
                    "base_analysis_target_fingerprint": (
                        target.base_analysis_target_fingerprint
                    ),
                    "source_retrieval_target_fingerprint": (
                        target.source_retrieval_target_fingerprint
                    ),
                    "decision": request.decision.value,
                    "report_artifact_id": target.report_artifact_id,
                    "provider_id": target.provider_id,
                    "model_id": target.model_id,
                    "prompt_version": target.prompt_version,
                    "promotion_ids": list(target.promotion_ids),
                    "selected_memory_sources_fingerprint": content_fingerprint(
                        list(target.selected_memory_sources)
                    ),
                    "request_fingerprint": request.fingerprint,
                    "quality_evidence_fingerprint": content_fingerprint(
                        target.quality_evidence
                    ),
                    "cost_evidence_fingerprint": content_fingerprint(cost_evidence),
                    "memory_artifact_created": False,
                    "memory_recall_eligible": False,
                    "automatic_memory_promotion_enabled": False,
                    "provider_promotion_eligible": False,
                    "decision_handoff_enabled": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
                "WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(
                "external promoted-memory analysis review persistence failed"
            )
        return _review_from_row(row), False

    def get(self, review_id: str) -> StoredExternalPromotedMemoryAnalysisReview:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
                    "WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(
                f"external promoted-memory analysis review not found: {review_id}"
            )
        return _review_from_row(row)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedMemoryAnalysisReview, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError(
                "external promoted-memory analysis review limit must be between "
                "1 and 200"
            )
        sql = "SELECT * FROM ai_external_promoted_memory_analysis_reviews"
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

    def verify_replay(
        self,
        review_id: str,
    ) -> ExternalPromotedMemoryAnalysisReviewAuditReplay:
        review = self.get(review_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * "
                "FROM ai_external_promoted_memory_analysis_review_events "
                "WHERE review_id = ? ORDER BY sequence",
                (review_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append(
                    "external promoted-memory analysis review sequence drifted"
                )
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append(
                    "external promoted-memory analysis review previous hash drifted"
                )
            expected_hash = _event_hash(
                review_id=review_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append(
                    "external promoted-memory analysis review event hash drifted"
                )
            expected = {
                "analysis_id": review.analysis_id,
                "workflow_id": review.workflow_id,
                "retrieval_id": review.retrieval_id,
                "analysis_target_fingerprint": review.analysis_target_fingerprint,
                "base_analysis_target_fingerprint": (
                    review.base_analysis_target_fingerprint
                ),
                "source_retrieval_target_fingerprint": (
                    review.source_retrieval_target_fingerprint
                ),
                "decision": review.request.decision.value,
                "report_artifact_id": review.report_artifact_id,
                "provider_id": review.provider_id,
                "model_id": review.model_id,
                "prompt_version": review.prompt_version,
                "promotion_ids": list(review.promotion_ids),
                "selected_memory_sources_fingerprint": content_fingerprint(
                    list(review.selected_memory_sources)
                ),
                "request_fingerprint": review.request_fingerprint,
                "quality_evidence_fingerprint": content_fingerprint(
                    review.quality_evidence
                ),
                "cost_evidence_fingerprint": content_fingerprint(review.cost_evidence),
            }
            for key, value in expected.items():
                if payload.get(key) != value:
                    errors.append(
                        "external promoted-memory analysis review " f"{key} drifted"
                    )
            for key in (
                "memory_artifact_created",
                "memory_recall_eligible",
                "automatic_memory_promotion_enabled",
                "provider_promotion_eligible",
                "decision_handoff_enabled",
            ):
                if payload.get(key) is not False:
                    errors.append(
                        "external promoted-memory analysis review "
                        f"{key} boundary drifted"
                    )
            if payload.get("authority_effect") != "none":
                errors.append(
                    "external promoted-memory analysis review authority boundary "
                    "drifted"
                )
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append(
                "external promoted-memory analysis review must contain exactly "
                "one event"
            )
        return ExternalPromotedMemoryAnalysisReviewAuditReplay(
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
        payload: JsonObject,
        created_at: str,
    ) -> None:
        event_type = "external_promoted_memory_analysis_review_recorded"
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_external_promoted_memory_analysis_review_events "
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
            INSERT INTO ai_external_promoted_memory_analysis_review_events (
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


class HumanExternalPromotedMemoryAnalysisReviewService:
    """Record and revalidate one human disposition without model I/O."""

    def __init__(
        self,
        *,
        analysis_service: HumanExternalPromotedMemoryAnalysisService,
        review_store: ExternalPromotedMemoryAnalysisReviewStore,
        now: Callable[[], str],
    ) -> None:
        self._analysis_service = analysis_service
        self._review_store = review_store
        self._now = now

    def review(
        self,
        analysis_id: str,
        request: HumanExternalPromotedMemoryAnalysisReviewRequest,
    ) -> ExternalPromotedMemoryAnalysisReviewResult:
        existing = self._review_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.analysis_id != analysis_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "external promoted-memory analysis review idempotency key "
                    "was reused with different input"
                )
            return self._result(existing, reused=True)

        target = _promoted_review_target(self._analysis_service.get(analysis_id))
        if request.decision == (
            ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
        ):
            blockers = list(target.acceptance_errors)
            if request.factual_error_count:
                blockers.append("reviewer_identified_factual_errors")
            if request.unsupported_claim_count:
                blockers.append("reviewer_identified_unsupported_claims")
            if blockers:
                raise ExternalPromotedMemoryAnalysisReviewRejected(
                    "external promoted-memory analysis cannot become reviewed "
                    "research: " + "; ".join(dict.fromkeys(blockers))
                )
        review, reused = self._review_store.record(
            target=target,
            request=request,
            created_at=self._now(),
        )
        return self._result(review, reused=reused)

    def get(self, review_id: str) -> ExternalPromotedMemoryAnalysisReviewResult:
        return self._result(self._review_store.get(review_id), reused=True)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ExternalPromotedMemoryAnalysisReviewResult, ...]:
        return tuple(
            self._result(review, reused=True)
            for review in self._review_store.list(
                analysis_id=analysis_id,
                limit=limit,
            )
        )

    def replay(self, review_id: str) -> ExternalPromotedMemoryAnalysisReviewReplay:
        return self.get(review_id).replay()

    def _result(
        self,
        review: StoredExternalPromotedMemoryAnalysisReview,
        *,
        reused: bool,
    ) -> ExternalPromotedMemoryAnalysisReviewResult:
        target = _promoted_review_target(self._analysis_service.get(review.analysis_id))
        return ExternalPromotedMemoryAnalysisReviewResult(
            review=review,
            current_target=target,
            audit_replay=self._review_store.verify_replay(review.review_id),
            reused=reused,
        )


def _promoted_review_target(
    promoted: ExternalPromotedMemoryAnalysisResult,
) -> ExternalPromotedMemoryAnalysisReviewTarget:
    analysis = promoted.analysis
    base = _review_target(analysis)
    errors = list(base.acceptance_errors)
    if analysis.record.request.schema_version != (
        EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION
    ):
        errors.append("analysis_request_is_not_promoted_memory_v1")

    source = promoted.source_retrieval
    retrieval_id = analysis.record.request.retrieval_id
    promotion_ids = promoted.promotion_ids
    selected_memory_sources: tuple[JsonObject, ...] = ()
    source_target_fingerprint: str | None = None
    source_evidence: JsonObject = {
        "retrieval_id": retrieval_id,
        "source_present": False,
    }
    if source is None:
        errors.append("source_promoted_memory_retrieval_missing")
    else:
        source_target_fingerprint = source.current_target.fingerprint
        selections = source.current_target.selections
        selected_memory_sources = tuple(
            {
                "promotion_id": item.promotion_id,
                "review_id": item.review_id,
                "source_analysis_id": item.analysis_id,
                "source_context_snapshot_id": item.source_context_snapshot_id,
                "memory_artifact_id": item.memory_artifact_id,
                "memory_artifact_fingerprint": item.memory_artifact_fingerprint,
                "selection_fingerprint": item.fingerprint,
            }
            for item in selections
        )
        source_evidence = {
            "retrieval_id": source.stored.retrieval_id,
            "source_present": True,
            "request_fingerprint": source.stored.request_fingerprint,
            "stored_target_fingerprint": (source.stored.retrieval_target_fingerprint),
            "current_target_fingerprint": source.current_target.fingerprint,
            "request_binding_valid": source.request_binding_valid,
            "target_binding_valid": source.target_binding_valid,
            "retrieval_eligible": source.retrieval_eligible,
            "promotion_ids": list(source.stored.request.promotion_ids),
            "selected_memory_source_fingerprints": [
                item.fingerprint for item in selections
            ],
            "audit": {
                "valid": source.audit_replay.valid,
                "event_count": source.audit_replay.event_count,
                "last_event_hash": source.audit_replay.last_event_hash,
                "errors": list(source.audit_replay.errors),
            },
            "invalidation_reasons": list(source.invalidation_reasons),
        }
        if source.stored.retrieval_id != retrieval_id:
            errors.append("source_promoted_memory_retrieval_id_drift")
        if not source.retrieval_eligible:
            errors.append("source_promoted_memory_retrieval_not_eligible")
        if not source.replay().valid:
            errors.append("source_promoted_memory_retrieval_replay_invalid")
        if analysis.record.retrieval_target_fingerprint != (
            source.current_target.fingerprint
        ):
            errors.append("analysis_source_retrieval_target_fingerprint_drift")

    if not promotion_ids:
        errors.append("source_promotion_ids_missing")
    if len(promotion_ids) != len(set(promotion_ids)):
        errors.append("source_promotion_ids_are_not_unique")
    selected_promotion_ids = tuple(
        str(item["promotion_id"]) for item in selected_memory_sources
    )
    if selected_promotion_ids != promotion_ids:
        errors.append("source_promotion_selection_binding_drift")

    target_payload = {
        "contract": EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION,
        "analysis_id": base.analysis_id,
        "workflow_id": base.workflow_id,
        "retrieval_id": retrieval_id,
        "context_snapshot_id": base.context_snapshot_id,
        "context_fingerprint": base.context_fingerprint,
        "provider_id": base.provider_id,
        "model_id": base.model_id,
        "prompt_version": base.prompt_version,
        "report_artifact_id": base.report_artifact_id,
        "promotion_ids": list(promotion_ids),
        "selected_memory_sources": list(selected_memory_sources),
        "base_analysis_target_fingerprint": base.fingerprint,
        "source_retrieval": source_evidence,
        "quality_evidence": base.quality_evidence,
    }
    return ExternalPromotedMemoryAnalysisReviewTarget(
        analysis_id=base.analysis_id,
        workflow_id=base.workflow_id,
        retrieval_id=retrieval_id,
        context_snapshot_id=base.context_snapshot_id,
        context_fingerprint=base.context_fingerprint,
        provider_id=base.provider_id,
        model_id=base.model_id,
        prompt_version=base.prompt_version,
        report_artifact_id=base.report_artifact_id,
        promotion_ids=promotion_ids,
        selected_memory_sources=selected_memory_sources,
        base_analysis_target_fingerprint=base.fingerprint,
        source_retrieval_target_fingerprint=source_target_fingerprint,
        quality_evidence=dict(base.quality_evidence),
        fingerprint=content_fingerprint(target_payload),
        acceptance_errors=tuple(dict.fromkeys(errors)),
    )


def _review_from_row(
    row: sqlite3.Row,
) -> StoredExternalPromotedMemoryAnalysisReview:
    payload = json.loads(str(row["request_json"]))
    rubric_payload = payload["quality_rubric"]
    pricing_payload = payload.get("pricing_snapshot")
    request = HumanExternalPromotedMemoryAnalysisReviewRequest(
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
    return StoredExternalPromotedMemoryAnalysisReview(
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        workflow_id=str(row["workflow_id"]),
        retrieval_id=str(row["retrieval_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        analysis_target_fingerprint=str(row["analysis_target_fingerprint"]),
        base_analysis_target_fingerprint=str(row["base_analysis_target_fingerprint"]),
        source_retrieval_target_fingerprint=(
            str(row["source_retrieval_target_fingerprint"])
            if row["source_retrieval_target_fingerprint"] is not None
            else None
        ),
        report_artifact_id=(
            str(row["report_artifact_id"])
            if row["report_artifact_id"] is not None
            else None
        ),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        promotion_ids=tuple(json.loads(str(row["promotion_ids_json"]))),
        selected_memory_sources=tuple(
            dict(item) for item in json.loads(str(row["selected_memory_sources_json"]))
        ),
        quality_evidence=dict(json.loads(str(row["quality_evidence_json"]))),
        cost_evidence=dict(json.loads(str(row["cost_evidence_json"]))),
        created_at=str(row["created_at"]),
    )
