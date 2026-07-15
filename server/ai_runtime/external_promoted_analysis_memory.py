"""Explicit Phase 1.16 promotion of reviewed promoted-memory analysis.

This boundary consumes only a currently eligible Phase 1.15 human review.  It
copies the exact normalized Phase 1.14 report into a new, versioned historical
research-memory artifact and records an independent append-only audit chain.
Revocation removes recall eligibility without deleting the promotion, review,
report, source-memory lineage, or audit evidence.

The Phase 1.12 memory schema remains unchanged.  Promotion and revocation are
local, model-free operations and cannot write Account Truth, Decision, OMS,
ledger, risk, broker, capital, permission, or execution state.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .contracts import (
    ArtifactKind,
    JsonObject,
    StoredArtifact,
    canonical_json,
    content_fingerprint,
)
from .external_promoted_memory_analysis_reviews import (
    HumanExternalPromotedMemoryAnalysisReviewService,
)
from .store import AiAuditStore, IdempotencyConflict

EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION = (
    "promote_reviewed_promoted_memory_analysis_to_revocable_historical_"
    "memory_without_current_fact_decision_or_trade_authority"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION = (
    "revoke_promoted_analysis_memory_recall_without_deleting_history_or_"
    "changing_trade_authority"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_promotion.v1"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_request.v1"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_revocation_request.v1"
)


class ExternalPromotedAnalysisMemoryEffectiveStatus(StrEnum):
    RECALL_ELIGIBLE = "recall_eligible"
    REVOKED = "revoked"
    INVALIDATED_BY_SOURCE_DRIFT = "invalidated_by_source_drift"


class ExternalPromotedAnalysisMemoryRejected(ValueError):
    """Raised when a Phase 1.16 promotion or revocation fails closed."""


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryPromotionRequest:
    idempotency_key: str
    promoted_by: str
    rationale: str
    confirmation: str
    schema_version: str = EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "promoted_by",
            "rationale",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != (
            EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION
        ):
            raise ValueError(
                "explicit promoted-analysis memory confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "promoted_by": self.promoted_by,
            "rationale": self.rationale,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryRevocationRequest:
    idempotency_key: str
    revoked_by: str
    reason: str
    confirmation: str
    schema_version: str = EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "revoked_by",
            "reason",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != (
            EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION
        ):
            raise ValueError(
                "explicit promoted-analysis memory revocation confirmation is "
                "required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "revoked_by": self.revoked_by,
            "reason": self.reason,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryTarget:
    review_id: str
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    source_context_snapshot_id: str
    source_context_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    source_promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    report_artifact_id: str | None
    report_artifact_fingerprint: str | None
    evidence_reference_ids: tuple[str, ...]
    provider_id: str
    model_id: str
    prompt_version: str
    review_target_fingerprint: str
    review_event_hash: str | None
    quality_evidence_fingerprint: str
    cost_evidence_fingerprint: str
    memory_content: JsonObject | None
    memory_artifact_fingerprint: str | None
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return (
            not self.errors
            and self.report_artifact_id is not None
            and self.report_artifact_fingerprint is not None
            and bool(self.evidence_reference_ids)
            and bool(self.source_promotion_ids)
            and len(self.source_promotion_ids) == len(self.selected_memory_sources)
            and self.memory_content is not None
            and self.memory_artifact_fingerprint is not None
        )


@dataclass(frozen=True)
class StoredExternalPromotedAnalysisMemoryPromotion:
    promotion_id: str
    review_id: str
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    request: ExternalPromotedAnalysisMemoryPromotionRequest
    request_fingerprint: str
    promotion_target_fingerprint: str
    memory_artifact_id: str
    memory_content: JsonObject
    memory_artifact_fingerprint: str
    evidence_reference_ids: tuple[str, ...]
    source_context_snapshot_id: str
    source_context_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    source_promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    report_artifact_id: str
    report_artifact_fingerprint: str
    provider_id: str
    model_id: str
    prompt_version: str
    review_target_fingerprint: str
    review_event_hash: str | None
    quality_evidence_fingerprint: str
    cost_evidence_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class StoredExternalPromotedAnalysisMemoryRevocation:
    revocation_id: str
    promotion_id: str
    request: ExternalPromotedAnalysisMemoryRevocationRequest
    request_fingerprint: str
    promotion_target_fingerprint: str
    memory_artifact_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryAuditReplay:
    promotion_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryReplay:
    promotion_id: str
    review_id: str
    valid: bool
    event_chain_valid: bool
    promotion_binding_valid: bool
    source_binding_valid: bool
    memory_artifact_binding_valid: bool
    revocation_binding_valid: bool
    revoked: bool
    memory_recall_eligible: bool
    effective_status: ExternalPromotedAnalysisMemoryEffectiveStatus
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": (
                "karkinos.ai.external_promoted_analysis_memory_replay.v1"
            ),
            "promotion_id": self.promotion_id,
            "review_id": self.review_id,
            "valid": self.valid,
            "event_chain_valid": self.event_chain_valid,
            "promotion_binding_valid": self.promotion_binding_valid,
            "source_binding_valid": self.source_binding_valid,
            "memory_artifact_binding_valid": self.memory_artifact_binding_valid,
            "revocation_binding_valid": self.revocation_binding_valid,
            "revoked": self.revoked,
            "memory_recall_eligible": self.memory_recall_eligible,
            "effective_status": self.effective_status.value,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "automatic_recall_enabled": False,
            "retrieval_contract_available": True,
            "retrieval_contract_version": (
                "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
            ),
            "legacy_phase_1_12_contract_modified": False,
            "provider_invocation_count": 0,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryPromotionResult:
    promotion: StoredExternalPromotedAnalysisMemoryPromotion
    current_target: ExternalPromotedAnalysisMemoryTarget
    revocation: StoredExternalPromotedAnalysisMemoryRevocation | None
    audit_replay: ExternalPromotedAnalysisMemoryAuditReplay
    reused: bool

    @property
    def promotion_binding_valid(self) -> bool:
        return (
            self.promotion.promotion_target_fingerprint
            == self.current_target.fingerprint
        )

    @property
    def source_binding_valid(self) -> bool:
        target = self.current_target
        promotion = self.promotion
        return (
            target.eligible
            and promotion.review_id == target.review_id
            and promotion.analysis_id == target.analysis_id
            and promotion.workflow_id == target.workflow_id
            and promotion.retrieval_id == target.retrieval_id
            and promotion.source_context_snapshot_id
            == target.source_context_snapshot_id
            and promotion.source_context_fingerprint
            == target.source_context_fingerprint
            and promotion.source_retrieval_target_fingerprint
            == target.source_retrieval_target_fingerprint
            and promotion.source_promotion_ids == target.source_promotion_ids
            and content_fingerprint(list(promotion.selected_memory_sources))
            == content_fingerprint(list(target.selected_memory_sources))
            and promotion.report_artifact_id == target.report_artifact_id
            and promotion.report_artifact_fingerprint
            == target.report_artifact_fingerprint
            and promotion.evidence_reference_ids == target.evidence_reference_ids
            and promotion.provider_id == target.provider_id
            and promotion.model_id == target.model_id
            and promotion.prompt_version == target.prompt_version
            and promotion.review_target_fingerprint == target.review_target_fingerprint
            and promotion.review_event_hash == target.review_event_hash
            and promotion.quality_evidence_fingerprint
            == target.quality_evidence_fingerprint
            and promotion.cost_evidence_fingerprint == target.cost_evidence_fingerprint
        )

    @property
    def memory_artifact_binding_valid(self) -> bool:
        target = self.current_target
        if (
            target.memory_content is None
            or target.memory_artifact_fingerprint is None
            or target.report_artifact_id is None
        ):
            return False
        expected = content_fingerprint(
            _memory_artifact_payload(
                review_id=target.review_id,
                analysis_id=target.analysis_id,
                report_artifact_id=target.report_artifact_id,
                content=target.memory_content,
                evidence_reference_ids=target.evidence_reference_ids,
            )
        )
        return (
            self.promotion.memory_content == target.memory_content
            and self.promotion.memory_artifact_fingerprint == expected
            and target.memory_artifact_fingerprint == expected
            and self.promotion.memory_artifact_id
            == f"ai-external-promoted-analysis-memory-{expected[:24]}"
        )

    @property
    def revocation_binding_valid(self) -> bool:
        revocation = self.revocation
        if revocation is None:
            return True
        return (
            revocation.promotion_id == self.promotion.promotion_id
            and revocation.promotion_target_fingerprint
            == self.promotion.promotion_target_fingerprint
            and revocation.memory_artifact_fingerprint
            == self.promotion.memory_artifact_fingerprint
        )

    @property
    def revoked(self) -> bool:
        return self.revocation is not None

    @property
    def historical_record_valid(self) -> bool:
        return (
            self.promotion_binding_valid
            and self.source_binding_valid
            and self.memory_artifact_binding_valid
            and self.revocation_binding_valid
            and self.audit_replay.valid
        )

    @property
    def memory_recall_eligible(self) -> bool:
        return self.historical_record_valid and not self.revoked

    @property
    def effective_status(self) -> ExternalPromotedAnalysisMemoryEffectiveStatus:
        if not self.historical_record_valid:
            return (
                ExternalPromotedAnalysisMemoryEffectiveStatus.INVALIDATED_BY_SOURCE_DRIFT
            )
        if self.revoked:
            return ExternalPromotedAnalysisMemoryEffectiveStatus.REVOKED
        return ExternalPromotedAnalysisMemoryEffectiveStatus.RECALL_ELIGIBLE

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.promotion_binding_valid:
            reasons.append("promoted_analysis_memory_target_fingerprint_drift")
        if not self.source_binding_valid:
            reasons.extend(self.current_target.errors)
            reasons.append("promoted_analysis_memory_source_binding_drift")
        if not self.memory_artifact_binding_valid:
            reasons.append("promoted_analysis_memory_artifact_binding_drift")
        if not self.revocation_binding_valid:
            reasons.append("promoted_analysis_memory_revocation_binding_drift")
        reasons.extend(self.audit_replay.errors)
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ExternalPromotedAnalysisMemoryReplay:
        return ExternalPromotedAnalysisMemoryReplay(
            promotion_id=self.promotion.promotion_id,
            review_id=self.promotion.review_id,
            valid=self.historical_record_valid,
            event_chain_valid=self.audit_replay.valid,
            promotion_binding_valid=self.promotion_binding_valid,
            source_binding_valid=self.source_binding_valid,
            memory_artifact_binding_valid=self.memory_artifact_binding_valid,
            revocation_binding_valid=self.revocation_binding_valid,
            revoked=self.revoked,
            memory_recall_eligible=self.memory_recall_eligible,
            effective_status=self.effective_status,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        promotion = self.promotion
        revocation = self.revocation
        return {
            "schema_version": EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
            "promotion_id": promotion.promotion_id,
            "review_id": promotion.review_id,
            "analysis_id": promotion.analysis_id,
            "workflow_id": promotion.workflow_id,
            "retrieval_id": promotion.retrieval_id,
            "effective_status": self.effective_status.value,
            "promoted_by": promotion.request.promoted_by,
            "rationale": promotion.request.rationale,
            "created_at": promotion.created_at,
            "source_promotion_ids": list(promotion.source_promotion_ids),
            "selected_memory_sources": [
                dict(item) for item in promotion.selected_memory_sources
            ],
            "source_context_snapshot_id": promotion.source_context_snapshot_id,
            "source_context_fingerprint": promotion.source_context_fingerprint,
            "source_retrieval_target_fingerprint": (
                promotion.source_retrieval_target_fingerprint
            ),
            "report_artifact_id": promotion.report_artifact_id,
            "report_artifact_fingerprint": promotion.report_artifact_fingerprint,
            "provider_id": promotion.provider_id,
            "model_id": promotion.model_id,
            "prompt_version": promotion.prompt_version,
            "review_target_fingerprint": promotion.review_target_fingerprint,
            "review_event_hash": promotion.review_event_hash,
            "quality_evidence_fingerprint": (promotion.quality_evidence_fingerprint),
            "cost_evidence_fingerprint": promotion.cost_evidence_fingerprint,
            "stored_promotion_target_fingerprint": (
                promotion.promotion_target_fingerprint
            ),
            "current_promotion_target_fingerprint": self.current_target.fingerprint,
            "promotion_binding_valid": self.promotion_binding_valid,
            "source_binding_valid": self.source_binding_valid,
            "memory_artifact_binding_valid": self.memory_artifact_binding_valid,
            "memory_artifact": {
                "artifact_id": promotion.memory_artifact_id,
                "artifact_kind": ArtifactKind.MEMORY.value,
                "artifact_fingerprint": promotion.memory_artifact_fingerprint,
                "evidence_reference_ids": list(promotion.evidence_reference_ids),
                "content": (
                    dict(promotion.memory_content)
                    if self.memory_recall_eligible
                    else None
                ),
            },
            "revoked": self.revoked,
            "revocation": (
                {
                    "revocation_id": revocation.revocation_id,
                    "revoked_by": revocation.request.revoked_by,
                    "reason": revocation.request.reason,
                    "created_at": revocation.created_at,
                }
                if revocation is not None
                else None
            ),
            "revocation_binding_valid": self.revocation_binding_valid,
            "memory_recall_eligible": self.memory_recall_eligible,
            "invalidation_reasons": list(self.invalidation_reasons),
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "reused": self.reused,
            "explicit_human_promotion_required": True,
            "automatic_memory_promotion_enabled": False,
            "automatic_recall_enabled": False,
            "retrieval_contract_available": True,
            "retrieval_contract_version": (
                "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
            ),
            "legacy_phase_1_12_contract_modified": False,
            "external_model_invocation_count": 0,
            "research_output_is_account_fact": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_promotions (
    promotion_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL UNIQUE,
    analysis_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    promotion_target_fingerprint TEXT NOT NULL,
    memory_artifact_id TEXT NOT NULL UNIQUE,
    memory_content_json TEXT NOT NULL,
    memory_artifact_fingerprint TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    source_context_snapshot_id TEXT NOT NULL,
    source_context_fingerprint TEXT NOT NULL,
    source_retrieval_target_fingerprint TEXT,
    source_promotion_ids_json TEXT NOT NULL,
    selected_memory_sources_json TEXT NOT NULL,
    report_artifact_id TEXT NOT NULL,
    report_artifact_fingerprint TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    review_target_fingerprint TEXT NOT NULL,
    review_event_hash TEXT,
    quality_evidence_fingerprint TEXT NOT NULL,
    cost_evidence_fingerprint TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(review_id)
        REFERENCES ai_external_promoted_memory_analysis_reviews(review_id),
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_promoted_memory_analyses(analysis_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(source_context_snapshot_id)
        REFERENCES ai_context_snapshots(snapshot_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_promoted_analysis_memory_created
ON ai_external_promoted_analysis_memory_promotions(
    created_at DESC, promotion_id DESC
);

CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_revocations (
    revocation_id TEXT PRIMARY KEY,
    promotion_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    promotion_target_fingerprint TEXT NOT NULL,
    memory_artifact_fingerprint TEXT NOT NULL,
    revoked_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(promotion_id)
        REFERENCES ai_external_promoted_analysis_memory_promotions(promotion_id)
);

CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_events (
    promotion_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(event_type IN (
        'external_promoted_analysis_memory_promoted',
        'external_promoted_analysis_memory_revoked'
    )),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(promotion_id, sequence),
    FOREIGN KEY(promotion_id)
        REFERENCES ai_external_promoted_analysis_memory_promotions(promotion_id)
);
"""


class ExternalPromotedAnalysisMemoryStore:
    """Append-only Phase 1.16 promotion, revocation, and event storage."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedAnalysisMemoryPromotion | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return _promotion_from_row(row) if row is not None else None

    def record_promotion(
        self,
        *,
        request: ExternalPromotedAnalysisMemoryPromotionRequest,
        target: ExternalPromotedAnalysisMemoryTarget,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryPromotion, bool]:
        if not target.eligible or target.memory_content is None:
            raise ExternalPromotedAnalysisMemoryRejected(
                "promoted-analysis memory target is not eligible"
            )
        if (
            target.report_artifact_id is None
            or target.report_artifact_fingerprint is None
            or target.memory_artifact_fingerprint is None
        ):
            raise ExternalPromotedAnalysisMemoryRejected(
                "promoted-analysis memory target is incomplete"
            )
        identity = {
            "review_id": target.review_id,
            "request_fingerprint": request.fingerprint,
            "promotion_target_fingerprint": target.fingerprint,
        }
        promotion_id = (
            "ai-external-promoted-analysis-memory-promotion-"
            f"{content_fingerprint(identity)[:24]}"
        )
        memory_artifact_id = (
            "ai-external-promoted-analysis-memory-"
            f"{target.memory_artifact_fingerprint[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = _promotion_from_row(row)
                if (
                    stored.review_id != target.review_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "promoted-analysis memory promotion idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT promotion_id "
                "FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE review_id = ?",
                (target.review_id,),
            ).fetchone()
            if final is not None:
                raise ExternalPromotedAnalysisMemoryRejected(
                    "promoted-memory analysis review already has a final memory "
                    "promotion"
                )
            conn.execute(
                """
                INSERT INTO ai_external_promoted_analysis_memory_promotions (
                    promotion_id, review_id, analysis_id, workflow_id,
                    retrieval_id, idempotency_key, request_json,
                    request_fingerprint, promotion_target_fingerprint,
                    memory_artifact_id, memory_content_json,
                    memory_artifact_fingerprint, evidence_reference_ids_json,
                    source_context_snapshot_id, source_context_fingerprint,
                    source_retrieval_target_fingerprint,
                    source_promotion_ids_json, selected_memory_sources_json,
                    report_artifact_id, report_artifact_fingerprint,
                    provider_id, model_id, prompt_version,
                    review_target_fingerprint, review_event_hash,
                    quality_evidence_fingerprint, cost_evidence_fingerprint,
                    promoted_by, rationale, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    promotion_id,
                    target.review_id,
                    target.analysis_id,
                    target.workflow_id,
                    target.retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    memory_artifact_id,
                    canonical_json(target.memory_content),
                    target.memory_artifact_fingerprint,
                    canonical_json(list(target.evidence_reference_ids)),
                    target.source_context_snapshot_id,
                    target.source_context_fingerprint,
                    target.source_retrieval_target_fingerprint,
                    canonical_json(list(target.source_promotion_ids)),
                    canonical_json(list(target.selected_memory_sources)),
                    target.report_artifact_id,
                    target.report_artifact_fingerprint,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    target.review_target_fingerprint,
                    target.review_event_hash,
                    target.quality_evidence_fingerprint,
                    target.cost_evidence_fingerprint,
                    request.promoted_by,
                    request.rationale,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                promotion_id=promotion_id,
                event_type="external_promoted_analysis_memory_promoted",
                payload={
                    "review_id": target.review_id,
                    "analysis_id": target.analysis_id,
                    "request_fingerprint": request.fingerprint,
                    "promotion_target_fingerprint": target.fingerprint,
                    "memory_artifact_id": memory_artifact_id,
                    "memory_artifact_fingerprint": (target.memory_artifact_fingerprint),
                    "review_target_fingerprint": target.review_target_fingerprint,
                    "review_event_hash": target.review_event_hash,
                    "source_promotion_ids": list(target.source_promotion_ids),
                    "automatic_recall_enabled": False,
                    "retrieval_contract_available": False,
                    "legacy_phase_1_12_contract_modified": False,
                    "provider_invocation_count": 0,
                    "decision_handoff_enabled": False,
                    "trade_plan_created": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE promotion_id = ?",
                (promotion_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("promoted-analysis memory promotion persistence failed")
        return _promotion_from_row(row), False

    def record_revocation(
        self,
        *,
        promotion: StoredExternalPromotedAnalysisMemoryPromotion,
        request: ExternalPromotedAnalysisMemoryRevocationRequest,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRevocation, bool]:
        identity = {
            "promotion_id": promotion.promotion_id,
            "request_fingerprint": request.fingerprint,
            "promotion_target_fingerprint": promotion.promotion_target_fingerprint,
            "memory_artifact_fingerprint": promotion.memory_artifact_fingerprint,
        }
        revocation_id = (
            "ai-external-promoted-analysis-memory-revocation-"
            f"{content_fingerprint(identity)[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_revocations "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = _revocation_from_row(row)
                if (
                    stored.promotion_id != promotion.promotion_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "promoted-analysis memory revocation idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT revocation_id "
                "FROM ai_external_promoted_analysis_memory_revocations "
                "WHERE promotion_id = ?",
                (promotion.promotion_id,),
            ).fetchone()
            if final is not None:
                raise ExternalPromotedAnalysisMemoryRejected(
                    "promoted-analysis memory is already revoked"
                )
            conn.execute(
                """
                INSERT INTO ai_external_promoted_analysis_memory_revocations (
                    revocation_id, promotion_id, idempotency_key, request_json,
                    request_fingerprint, promotion_target_fingerprint,
                    memory_artifact_fingerprint, revoked_by, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revocation_id,
                    promotion.promotion_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    promotion.promotion_target_fingerprint,
                    promotion.memory_artifact_fingerprint,
                    request.revoked_by,
                    request.reason,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                promotion_id=promotion.promotion_id,
                event_type="external_promoted_analysis_memory_revoked",
                payload={
                    "revocation_id": revocation_id,
                    "request_fingerprint": request.fingerprint,
                    "promotion_target_fingerprint": (
                        promotion.promotion_target_fingerprint
                    ),
                    "memory_artifact_fingerprint": (
                        promotion.memory_artifact_fingerprint
                    ),
                    "automatic_recall_enabled": False,
                    "retrieval_contract_available": False,
                    "legacy_phase_1_12_contract_modified": False,
                    "provider_invocation_count": 0,
                    "decision_handoff_enabled": False,
                    "trade_plan_created": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_revocations "
                "WHERE revocation_id = ?",
                (revocation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("promoted-analysis memory revocation persistence failed")
        return _revocation_from_row(row), False

    def get(
        self,
        promotion_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryPromotion:
        row = self._one_or_none(
            "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
            "WHERE promotion_id = ?",
            (promotion_id,),
        )
        if row is None:
            raise LookupError(f"promoted-analysis memory not found: {promotion_id}")
        return _promotion_from_row(row)

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryPromotion, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("memory promotion limit must be between 1 and 200")
        params: tuple[object, ...]
        if review_id is None:
            sql = (
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "ORDER BY created_at DESC, promotion_id DESC LIMIT ?"
            )
            params = (limit,)
        else:
            sql = (
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE review_id = ? "
                "ORDER BY created_at DESC, promotion_id DESC LIMIT ?"
            )
            params = (review_id, limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(_promotion_from_row(row) for row in rows)

    def get_revocation(
        self,
        promotion_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryRevocation | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_promoted_analysis_memory_revocations "
            "WHERE promotion_id = ?",
            (promotion_id,),
        )
        return _revocation_from_row(row) if row is not None else None

    def verify_replay(
        self,
        promotion_id: str,
    ) -> ExternalPromotedAnalysisMemoryAuditReplay:
        promotion = self.get(promotion_id)
        revocation = self.get_revocation(promotion_id)
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * "
                    "FROM ai_external_promoted_analysis_memory_events "
                    "WHERE promotion_id = ? ORDER BY sequence",
                    (promotion_id,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        errors: list[str] = []
        previous_hash: str | None = None
        expected_types = ["external_promoted_analysis_memory_promoted"]
        if revocation is not None:
            expected_types.append("external_promoted_analysis_memory_revoked")
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            event_type = str(row["event_type"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("promoted-analysis memory audit sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("promoted-analysis memory audit previous hash drifted")
            expected_hash = _event_hash(
                promotion_id=promotion_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("promoted-analysis memory audit event hash drifted")
            if expected_sequence <= len(expected_types) and event_type != (
                expected_types[expected_sequence - 1]
            ):
                errors.append("promoted-analysis memory audit lifecycle drifted")
            if event_type == "external_promoted_analysis_memory_promoted":
                expected = {
                    "review_id": promotion.review_id,
                    "analysis_id": promotion.analysis_id,
                    "request_fingerprint": promotion.request_fingerprint,
                    "promotion_target_fingerprint": (
                        promotion.promotion_target_fingerprint
                    ),
                    "memory_artifact_id": promotion.memory_artifact_id,
                    "memory_artifact_fingerprint": (
                        promotion.memory_artifact_fingerprint
                    ),
                    "review_target_fingerprint": (promotion.review_target_fingerprint),
                    "review_event_hash": promotion.review_event_hash,
                    "source_promotion_ids": list(promotion.source_promotion_ids),
                }
            else:
                expected = {}
                if revocation is None:
                    errors.append(
                        "promoted-analysis memory revocation event has no row"
                    )
                else:
                    expected = {
                        "revocation_id": revocation.revocation_id,
                        "request_fingerprint": revocation.request_fingerprint,
                        "promotion_target_fingerprint": (
                            revocation.promotion_target_fingerprint
                        ),
                        "memory_artifact_fingerprint": (
                            revocation.memory_artifact_fingerprint
                        ),
                    }
            for key, value in expected.items():
                if payload.get(key) != value:
                    errors.append(f"promoted-analysis memory audit {key} drifted")
            for key in (
                "automatic_recall_enabled",
                "retrieval_contract_available",
                "legacy_phase_1_12_contract_modified",
                "decision_handoff_enabled",
                "trade_plan_created",
            ):
                if payload.get(key) is not False:
                    errors.append(f"promoted-analysis memory {key} boundary drifted")
            if payload.get("provider_invocation_count") != 0:
                errors.append(
                    "promoted-analysis memory provider invocation boundary drifted"
                )
            if payload.get("authority_effect") != "none":
                errors.append("promoted-analysis memory authority boundary drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != len(expected_types):
            errors.append("promoted-analysis memory audit event count drifted")
        return ExternalPromotedAnalysisMemoryAuditReplay(
            promotion_id=promotion_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    def _one_or_none(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> sqlite3.Row | None:
        try:
            with self._connection() as conn:
                return conn.execute(sql, params).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            return None

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        promotion_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_external_promoted_analysis_memory_events "
            "WHERE promotion_id = ? ORDER BY sequence DESC LIMIT 1",
            (promotion_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = _event_hash(
            promotion_id=promotion_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_promoted_analysis_memory_events (
                promotion_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                promotion_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )


class ExternalPromotedAnalysisMemoryPromotionService:
    """Promote and revoke an exact Phase 1.15 result without model I/O."""

    def __init__(
        self,
        *,
        review_service: HumanExternalPromotedMemoryAnalysisReviewService,
        ai_store: AiAuditStore,
        promotion_store: ExternalPromotedAnalysisMemoryStore,
        now: Callable[[], str],
    ) -> None:
        self._review_service = review_service
        self._ai_store = ai_store
        self._promotion_store = promotion_store
        self._now = now

    def promote(
        self,
        review_id: str,
        request: ExternalPromotedAnalysisMemoryPromotionRequest,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        existing = self._promotion_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.review_id != review_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "promoted-analysis memory promotion idempotency key was "
                    "reused with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(review_id)
        if not target.eligible:
            raise ExternalPromotedAnalysisMemoryRejected(
                "reviewed promoted-memory analysis cannot become historical "
                "memory: " + "; ".join(target.errors)
            )
        promotion, reused = self._promotion_store.record_promotion(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(promotion, reused=reused)

    def revoke(
        self,
        promotion_id: str,
        request: ExternalPromotedAnalysisMemoryRevocationRequest,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        promotion = self._promotion_store.get(promotion_id)
        _, reused = self._promotion_store.record_revocation(
            promotion=promotion,
            request=request,
            created_at=self._now(),
        )
        return self._result(promotion, reused=reused)

    def get(
        self,
        promotion_id: str,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        return self._result(self._promotion_store.get(promotion_id), reused=True)

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ExternalPromotedAnalysisMemoryPromotionResult, ...]:
        return tuple(
            self._result(promotion, reused=True)
            for promotion in self._promotion_store.list(
                review_id=review_id,
                limit=limit,
            )
        )

    def replay(self, promotion_id: str) -> ExternalPromotedAnalysisMemoryReplay:
        return self.get(promotion_id).replay()

    def _result(
        self,
        promotion: StoredExternalPromotedAnalysisMemoryPromotion,
        *,
        reused: bool,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        return ExternalPromotedAnalysisMemoryPromotionResult(
            promotion=promotion,
            current_target=self._target(promotion.review_id),
            revocation=self._promotion_store.get_revocation(promotion.promotion_id),
            audit_replay=self._promotion_store.verify_replay(promotion.promotion_id),
            reused=reused,
        )

    def _target(self, review_id: str) -> ExternalPromotedAnalysisMemoryTarget:
        errors: list[str] = []
        review = self._review_service.get(review_id)
        if not review.reviewed_research_eligible:
            errors.extend(review.invalidation_reasons)
            if not review.invalidation_reasons:
                errors.append(f"review_not_eligible:{review.effective_status.value}")
        review_replay = review.replay()
        if not review_replay.valid:
            errors.append("promoted_memory_analysis_review_replay_invalid")

        report: StoredArtifact | None = None
        report_id = review.review.report_artifact_id
        if report_id is None:
            errors.append("review_has_no_report_artifact")
        else:
            matches = [
                artifact
                for artifact in self._ai_store.list_artifacts(review.review.workflow_id)
                if artifact.artifact_id == report_id
                and artifact.kind == ArtifactKind.REPORT
            ]
            if len(matches) != 1:
                errors.append("review_must_bind_exactly_one_report_artifact")
            else:
                report = matches[0]

        memory_content: JsonObject | None = None
        memory_artifact_fingerprint: str | None = None
        evidence_reference_ids: tuple[str, ...] = ()
        if report is not None:
            report_content = dict(report.content)
            if report_content.get("authoritative") is not False:
                errors.append("report_authority_flag_invalid")
            if report_content.get("requires_human_review") is not True:
                errors.append("report_human_review_flag_invalid")
            if report_content.get("authority_effect") != "none":
                errors.append("report_authority_effect_invalid")
            if report_content.get("memory_created") is not False:
                errors.append("source_report_memory_flag_invalid")
            if report_content.get("retrieval_id") != review.review.retrieval_id:
                errors.append("report_retrieval_id_binding_drift")
            if report_content.get("retrieval_target_fingerprint") != (
                review.current_target.source_retrieval_target_fingerprint
            ):
                errors.append("report_retrieval_target_binding_drift")
            evidence_reference_ids = tuple(report.evidence_reference_ids)
            if not evidence_reference_ids:
                errors.append("source_report_has_no_evidence_references")
            memory_content = _memory_content(
                review_id=review.review.review_id,
                analysis_id=review.review.analysis_id,
                retrieval_id=review.review.retrieval_id,
                report=report,
                source_context_snapshot_id=(review.current_target.context_snapshot_id),
                source_context_fingerprint=(review.current_target.context_fingerprint),
                source_retrieval_target_fingerprint=(
                    review.current_target.source_retrieval_target_fingerprint
                ),
                source_promotion_ids=review.review.promotion_ids,
                selected_memory_sources=review.review.selected_memory_sources,
                provider_id=review.review.provider_id,
                model_id=review.review.model_id,
                prompt_version=review.review.prompt_version,
                review_note=review.review.request.note,
                reviewed_by=review.review.request.reviewed_by,
                human_rubric=review.review.request.quality_rubric.to_dict(),
                factual_error_count=(review.review.request.factual_error_count),
                unsupported_claim_count=(review.review.request.unsupported_claim_count),
                quality_evidence_fingerprint=content_fingerprint(
                    review.review.quality_evidence
                ),
                cost_evidence_fingerprint=content_fingerprint(
                    review.review.cost_evidence
                ),
            )
            memory_artifact_fingerprint = content_fingerprint(
                _memory_artifact_payload(
                    review_id=review.review.review_id,
                    analysis_id=review.review.analysis_id,
                    report_artifact_id=report.artifact_id,
                    content=memory_content,
                    evidence_reference_ids=evidence_reference_ids,
                )
            )

        target_payload: JsonObject = {
            "contract": EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
            "review_id": review.review.review_id,
            "review_target_fingerprint": review.current_target.fingerprint,
            "review_event_hash": review.audit_replay.last_event_hash,
            "review_replay_valid": review_replay.valid,
            "analysis_id": review.review.analysis_id,
            "workflow_id": review.review.workflow_id,
            "retrieval_id": review.review.retrieval_id,
            "source_context_snapshot_id": (review.current_target.context_snapshot_id),
            "source_context_fingerprint": review.current_target.context_fingerprint,
            "source_retrieval_target_fingerprint": (
                review.current_target.source_retrieval_target_fingerprint
            ),
            "source_promotion_ids": list(review.review.promotion_ids),
            "selected_memory_sources": list(review.review.selected_memory_sources),
            "report_artifact_id": report.artifact_id if report is not None else None,
            "report_artifact_fingerprint": (
                report.fingerprint if report is not None else None
            ),
            "evidence_reference_ids": list(evidence_reference_ids),
            "provider_id": review.review.provider_id,
            "model_id": review.review.model_id,
            "prompt_version": review.review.prompt_version,
            "quality_evidence_fingerprint": content_fingerprint(
                review.review.quality_evidence
            ),
            "cost_evidence_fingerprint": content_fingerprint(
                review.review.cost_evidence
            ),
            "memory_artifact_fingerprint": memory_artifact_fingerprint,
            "errors": list(dict.fromkeys(errors)),
        }
        return ExternalPromotedAnalysisMemoryTarget(
            review_id=review.review.review_id,
            analysis_id=review.review.analysis_id,
            workflow_id=review.review.workflow_id,
            retrieval_id=review.review.retrieval_id,
            source_context_snapshot_id=review.current_target.context_snapshot_id,
            source_context_fingerprint=review.current_target.context_fingerprint,
            source_retrieval_target_fingerprint=(
                review.current_target.source_retrieval_target_fingerprint
            ),
            source_promotion_ids=review.review.promotion_ids,
            selected_memory_sources=review.review.selected_memory_sources,
            report_artifact_id=report.artifact_id if report is not None else None,
            report_artifact_fingerprint=(
                report.fingerprint if report is not None else None
            ),
            evidence_reference_ids=evidence_reference_ids,
            provider_id=review.review.provider_id,
            model_id=review.review.model_id,
            prompt_version=review.review.prompt_version,
            review_target_fingerprint=review.current_target.fingerprint,
            review_event_hash=review.audit_replay.last_event_hash,
            quality_evidence_fingerprint=content_fingerprint(
                review.review.quality_evidence
            ),
            cost_evidence_fingerprint=content_fingerprint(review.review.cost_evidence),
            memory_content=memory_content,
            memory_artifact_fingerprint=memory_artifact_fingerprint,
            fingerprint=content_fingerprint(target_payload),
            errors=tuple(dict.fromkeys(errors)),
        )


def _memory_content(
    *,
    review_id: str,
    analysis_id: str,
    retrieval_id: str,
    report: StoredArtifact,
    source_context_snapshot_id: str,
    source_context_fingerprint: str,
    source_retrieval_target_fingerprint: str | None,
    source_promotion_ids: Sequence[str],
    selected_memory_sources: Sequence[JsonObject],
    provider_id: str,
    model_id: str,
    prompt_version: str,
    review_note: str,
    reviewed_by: str,
    human_rubric: dict[str, int],
    factual_error_count: int,
    unsupported_claim_count: int,
    quality_evidence_fingerprint: str,
    cost_evidence_fingerprint: str,
) -> JsonObject:
    source = dict(report.content)
    normalized_report = {
        field_name: source[field_name]
        for field_name in (
            "title",
            "summary",
            "findings",
            "counterpoints",
            "limitations",
            "follow_up_checks",
            "conclusion",
        )
        if field_name in source
    }
    provenance = source.get("provider_provenance")
    safe_provenance: JsonObject = {}
    if isinstance(provenance, Mapping):
        for field_name in (
            "provider_id",
            "model_id",
            "response_model",
            "prompt_version",
            "request_payload_fingerprint",
            "response_fingerprint",
            "http_status",
            "latency_ms",
            "timeout_seconds",
            "usage",
            "finish_reason",
            "reasoning_mode_requested",
            "reasoning_effort_requested",
            "reasoning_content_present",
            "reasoning_content_char_count",
            "reasoning_content_persisted",
        ):
            if field_name in provenance:
                safe_provenance[field_name] = provenance[field_name]
    return {
        "schema_version": ("karkinos.ai.external_promoted_analysis_memory_artifact.v1"),
        "scope": f"external-promoted-memory-analysis/{analysis_id}",
        "source_review_id": review_id,
        "source_analysis_id": analysis_id,
        "source_report_artifact_id": report.artifact_id,
        "source_report_artifact_fingerprint": report.fingerprint,
        "source_retrieval_id": retrieval_id,
        "source_retrieval_target_fingerprint": (source_retrieval_target_fingerprint),
        "source_context_snapshot_id": source_context_snapshot_id,
        "source_context_fingerprint": source_context_fingerprint,
        "source_promotion_ids": list(source_promotion_ids),
        "selected_memory_source_fingerprints": [
            item.get("selection_fingerprint") for item in selected_memory_sources
        ],
        "source_provider_id": provider_id,
        "source_model_id": model_id,
        "source_prompt_version": prompt_version,
        "reviewed_by": reviewed_by,
        "review_note": review_note,
        "human_quality_rubric": dict(human_rubric),
        "factual_error_count": factual_error_count,
        "unsupported_claim_count": unsupported_claim_count,
        "quality_evidence_fingerprint": quality_evidence_fingerprint,
        "cost_evidence_fingerprint": cost_evidence_fingerprint,
        "historical_report": normalized_report,
        "provider_provenance": safe_provenance,
        "validity_status": (
            "reviewed_historical_research_invalid_on_source_evidence_audit_or_"
            "lineage_drift_and_explicitly_revocable"
        ),
        "human_review_required_on_retrieval": True,
        "automatic_recall_allowed": False,
        "is_current_fact": False,
        "requires_current_evidence_rebinding": True,
        "decision_input_created": False,
        "trade_plan_created": False,
        "authority_effect": "none",
    }


def _memory_artifact_payload(
    *,
    review_id: str,
    analysis_id: str,
    report_artifact_id: str,
    content: JsonObject,
    evidence_reference_ids: Sequence[str],
) -> JsonObject:
    return {
        "kind": ArtifactKind.MEMORY.value,
        "source_review_id": review_id,
        "source_analysis_id": analysis_id,
        "source_artifact_ids": [report_artifact_id],
        "content": dict(content),
        "evidence_reference_ids": list(evidence_reference_ids),
        "authority_effect": "none",
    }


def _event_hash(
    *,
    promotion_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "promotion_id": promotion_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )


def _promotion_from_row(
    row: sqlite3.Row,
) -> StoredExternalPromotedAnalysisMemoryPromotion:
    request_payload = json.loads(str(row["request_json"]))
    request = ExternalPromotedAnalysisMemoryPromotionRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        promoted_by=str(request_payload["promoted_by"]),
        rationale=str(request_payload["rationale"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalPromotedAnalysisMemoryPromotion(
        promotion_id=str(row["promotion_id"]),
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        workflow_id=str(row["workflow_id"]),
        retrieval_id=str(row["retrieval_id"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        promotion_target_fingerprint=str(row["promotion_target_fingerprint"]),
        memory_artifact_id=str(row["memory_artifact_id"]),
        memory_content=dict(json.loads(str(row["memory_content_json"]))),
        memory_artifact_fingerprint=str(row["memory_artifact_fingerprint"]),
        evidence_reference_ids=tuple(
            str(item) for item in json.loads(str(row["evidence_reference_ids_json"]))
        ),
        source_context_snapshot_id=str(row["source_context_snapshot_id"]),
        source_context_fingerprint=str(row["source_context_fingerprint"]),
        source_retrieval_target_fingerprint=(
            str(row["source_retrieval_target_fingerprint"])
            if row["source_retrieval_target_fingerprint"] is not None
            else None
        ),
        source_promotion_ids=tuple(
            str(item) for item in json.loads(str(row["source_promotion_ids_json"]))
        ),
        selected_memory_sources=tuple(
            dict(item) for item in json.loads(str(row["selected_memory_sources_json"]))
        ),
        report_artifact_id=str(row["report_artifact_id"]),
        report_artifact_fingerprint=str(row["report_artifact_fingerprint"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        review_target_fingerprint=str(row["review_target_fingerprint"]),
        review_event_hash=(
            str(row["review_event_hash"])
            if row["review_event_hash"] is not None
            else None
        ),
        quality_evidence_fingerprint=str(row["quality_evidence_fingerprint"]),
        cost_evidence_fingerprint=str(row["cost_evidence_fingerprint"]),
        created_at=str(row["created_at"]),
    )


def _revocation_from_row(
    row: sqlite3.Row,
) -> StoredExternalPromotedAnalysisMemoryRevocation:
    request_payload = json.loads(str(row["request_json"]))
    request = ExternalPromotedAnalysisMemoryRevocationRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        revoked_by=str(request_payload["revoked_by"]),
        reason=str(request_payload["reason"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalPromotedAnalysisMemoryRevocation(
        revocation_id=str(row["revocation_id"]),
        promotion_id=str(row["promotion_id"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        promotion_target_fingerprint=str(row["promotion_target_fingerprint"]),
        memory_artifact_fingerprint=str(row["memory_artifact_fingerprint"]),
        created_at=str(row["created_at"]),
    )
