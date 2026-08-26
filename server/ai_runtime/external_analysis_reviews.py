"""Human review and provider-quality evidence for external AI research.

The review is an append-only disposition of one exact Phase 1.10 analysis. It
may mark that output as reviewed research, but it deliberately cannot create a
memory artifact, provider promotion, Decision input, financial fact, or any
trading/capital authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast

from server.persistence.external_analysis_review_projection import (
    ExternalAnalysisReviewProjectionMixin,
)
from server.persistence.external_analysis_review_repository import (
    ExternalAnalysisReviewRepositoryMixin,
)
from server.persistence.external_analysis_review_schema import (
    ExternalAnalysisReviewSchemaMixin,
)
from server.persistence.external_analysis_review_uow import (
    ExternalAnalysisReviewUnitOfWorkMixin,
)

from .contracts import ArtifactKind, JsonObject, content_fingerprint
from .external_analysis_review_target import (
    build_external_analysis_review_target,
)
from .external_analysis_review_values import (
    external_analysis_decimal_text,
    external_analysis_non_negative_decimal,
    external_analysis_review_cost_evidence,
    external_analysis_review_event_hash,
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


class ExternalAnalysisReviewStore(
    ExternalAnalysisReviewUnitOfWorkMixin,
    ExternalAnalysisReviewRepositoryMixin,
    ExternalAnalysisReviewSchemaMixin,
    ExternalAnalysisReviewProjectionMixin,
):
    """Append-only human reviews and their one-event audit chains."""

    _request_type = HumanExternalAnalysisReviewRequest
    _decision_type = ExternalAnalysisReviewDecision
    _rubric_type = ExternalAnalysisQualityRubric
    _pricing_type = ProviderPricingSnapshot
    _stored_review_type = StoredExternalAnalysisReview
    _audit_replay_type = ExternalAnalysisReviewAuditReplay
    _rejected_type = ExternalAnalysisReviewRejected

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        self._init_schema()

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalAnalysisReview | None:
        return cast(
            StoredExternalAnalysisReview | None,
            self._get_by_idempotency_key(idempotency_key),
        )

    def record(
        self,
        *,
        target: ExternalAnalysisReviewTarget,
        request: HumanExternalAnalysisReviewRequest,
        created_at: str,
    ) -> tuple[StoredExternalAnalysisReview, bool]:
        return cast(
            tuple[StoredExternalAnalysisReview, bool],
            self._record(target=target, request=request, created_at=created_at),
        )

    def get(self, review_id: str) -> StoredExternalAnalysisReview:
        return cast(StoredExternalAnalysisReview, self._get(review_id))

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalAnalysisReview, ...]:
        return cast(
            tuple[StoredExternalAnalysisReview, ...],
            self._list(analysis_id=analysis_id, limit=limit),
        )

    def verify_replay(
        self,
        review_id: str,
    ) -> ExternalAnalysisReviewAuditReplay:
        return cast(
            ExternalAnalysisReviewAuditReplay,
            self._verify_replay(review_id),
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
    return cast(
        ExternalAnalysisReviewTarget,
        build_external_analysis_review_target(
            analysis,
            target_type=ExternalAnalysisReviewTarget,
            expected_artifact_kinds=_EXPECTED_ARTIFACT_KINDS,
            expected_stage_count=_EXPECTED_STAGE_COUNT,
        ),
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
    return external_analysis_review_event_hash(
        review_id=review_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        previous_hash=previous_hash,
        created_at=created_at,
    )


def _review_from_row(row: object) -> StoredExternalAnalysisReview:
    store = object.__new__(ExternalAnalysisReviewStore)
    return cast(
        StoredExternalAnalysisReview,
        ExternalAnalysisReviewProjectionMixin._review_from_row(store, row),  # type: ignore[arg-type]
    )


def _cost_evidence(
    request: HumanExternalAnalysisReviewRequest,
    quality_evidence: Mapping[str, object],
) -> JsonObject:
    return external_analysis_review_cost_evidence(request, quality_evidence)


def _non_negative_decimal(value: object, field_name: str) -> Decimal:
    return external_analysis_non_negative_decimal(value, field_name)


def _decimal_text(value: Decimal) -> str:
    return external_analysis_decimal_text(value)


# Public review projections reused by the promoted-memory review contract.
review_target = _review_target
event_hash = _event_hash
cost_evidence = _cost_evidence
