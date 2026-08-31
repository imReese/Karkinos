"""Human disposition for deterministic fixture research artifacts.

This boundary can make an exact, reviewed memory artifact eligible for later
AI research recall.  It cannot make that artifact an account fact, Decision
input, risk decision, executable trade plan, capital authority, or broker
instruction.  Eligibility is derived again on every read and fails closed when
the bound analysis, evidence, artifact, or audit identity drifts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from server.persistence.analysis_reviews import AnalysisReviewPersistenceMixin

from .contracts import (
    ArtifactKind,
    JsonObject,
    WorkflowStatus,
    content_fingerprint,
)
from .evidence import EvidenceIdentityMismatch
from .store import IdempotencyConflict
from .task_analysis import (
    HumanResearchTaskFixtureAnalysisService,
    ResearchTaskAnalysisResult,
)

ANALYSIS_REVIEW_CONFIRMATION = (
    "record_fixture_analysis_review_without_decision_or_execution_authority"
)
ANALYSIS_REVIEW_CONTRACT_VERSION = "karkinos.ai.fixture_analysis_review.v1"


class AnalysisReviewDecision(StrEnum):
    ACCEPT_AS_REVIEWED_MEMORY = "accept_as_reviewed_memory"
    REQUEST_REVISION = "request_revision"
    REJECT = "reject"


class AnalysisReviewEffectiveStatus(StrEnum):
    REVIEWED_MEMORY = "reviewed_memory"
    REVISION_REQUESTED = "revision_requested"
    REJECTED = "rejected"
    INVALIDATED_BY_EVIDENCE_DRIFT = "invalidated_by_evidence_drift"


class AnalysisReviewRejected(ValueError):
    """Raised when a human analysis disposition cannot pass its gates."""


@dataclass(frozen=True)
class HumanAnalysisReviewRequest:
    idempotency_key: str
    reviewed_by: str
    decision: AnalysisReviewDecision
    note: str
    confirmation: str
    schema_version: str = "karkinos.ai.fixture_analysis_review_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != ANALYSIS_REVIEW_CONFIRMATION:
            raise ValueError(
                "explicit non-authoritative fixture analysis review "
                "confirmation is required"
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
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AnalysisReviewTarget:
    analysis_id: str
    task_id: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    memory_artifact_id: str | None
    fingerprint: str
    acceptance_errors: tuple[str, ...]

    @property
    def acceptance_eligible(self) -> bool:
        return not self.acceptance_errors and self.memory_artifact_id is not None


@dataclass(frozen=True)
class StoredAnalysisReview:
    review_id: str
    analysis_id: str
    task_id: str
    workflow_id: str
    idempotency_key: str
    request_fingerprint: str
    analysis_target_fingerprint: str
    memory_artifact_id: str | None
    reviewed_by: str
    decision: AnalysisReviewDecision
    note: str
    created_at: str


@dataclass(frozen=True)
class AnalysisReviewAuditReplay:
    review_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisReviewReplay:
    review_id: str
    analysis_id: str
    valid: bool
    review_event_chain_valid: bool
    analysis_target_binding_valid: bool
    memory_recall_eligible: bool
    effective_status: AnalysisReviewEffectiveStatus
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.fixture_analysis_review_replay.v1",
            "review_id": self.review_id,
            "analysis_id": self.analysis_id,
            "valid": self.valid,
            "review_event_chain_valid": self.review_event_chain_valid,
            "analysis_target_binding_valid": self.analysis_target_binding_valid,
            "memory_recall_eligible": self.memory_recall_eligible,
            "effective_status": self.effective_status.value,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "research_memory_only": True,
            "research_output_is_account_fact": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class AnalysisReviewResult:
    review: StoredAnalysisReview
    current_target: AnalysisReviewTarget
    audit_replay: AnalysisReviewAuditReplay
    reused: bool

    @property
    def target_binding_valid(self) -> bool:
        return (
            self.review.analysis_target_fingerprint == self.current_target.fingerprint
        )

    @property
    def memory_recall_eligible(self) -> bool:
        return (
            self.review.decision == AnalysisReviewDecision.ACCEPT_AS_REVIEWED_MEMORY
            and self.target_binding_valid
            and self.current_target.acceptance_eligible
            and self.audit_replay.valid
        )

    @property
    def effective_status(self) -> AnalysisReviewEffectiveStatus:
        if self.review.decision == AnalysisReviewDecision.ACCEPT_AS_REVIEWED_MEMORY:
            if self.memory_recall_eligible:
                return AnalysisReviewEffectiveStatus.REVIEWED_MEMORY
            return AnalysisReviewEffectiveStatus.INVALIDATED_BY_EVIDENCE_DRIFT
        if self.review.decision == AnalysisReviewDecision.REQUEST_REVISION:
            return AnalysisReviewEffectiveStatus.REVISION_REQUESTED
        return AnalysisReviewEffectiveStatus.REJECTED

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.target_binding_valid:
            reasons.append("analysis_target_fingerprint_drift")
        reasons.extend(self.current_target.acceptance_errors)
        reasons.extend(self.audit_replay.errors)
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> AnalysisReviewReplay:
        errors = self.invalidation_reasons
        return AnalysisReviewReplay(
            review_id=self.review.review_id,
            analysis_id=self.review.analysis_id,
            valid=(
                self.audit_replay.valid
                and self.target_binding_valid
                and (
                    self.review.decision
                    != AnalysisReviewDecision.ACCEPT_AS_REVIEWED_MEMORY
                    or self.current_target.acceptance_eligible
                )
            ),
            review_event_chain_valid=self.audit_replay.valid,
            analysis_target_binding_valid=self.target_binding_valid,
            memory_recall_eligible=self.memory_recall_eligible,
            effective_status=self.effective_status,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=errors,
        )

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": ANALYSIS_REVIEW_CONTRACT_VERSION,
            "review_id": self.review.review_id,
            "analysis_id": self.review.analysis_id,
            "task_id": self.review.task_id,
            "workflow_id": self.review.workflow_id,
            "decision": self.review.decision.value,
            "effective_status": self.effective_status.value,
            "note": self.review.note,
            "reviewed_by": self.review.reviewed_by,
            "created_at": self.review.created_at,
            "memory_artifact_id": self.review.memory_artifact_id,
            "stored_analysis_target_fingerprint": (
                self.review.analysis_target_fingerprint
            ),
            "current_analysis_target_fingerprint": self.current_target.fingerprint,
            "analysis_target_binding_valid": self.target_binding_valid,
            "analysis_acceptance_eligible": (self.current_target.acceptance_eligible),
            "memory_recall_eligible": self.memory_recall_eligible,
            "invalidation_reasons": list(self.invalidation_reasons),
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "reused": self.reused,
            "fixture_only": True,
            "research_memory_only": True,
            "persisted_facts_only": True,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "research_output_is_account_fact": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


class AnalysisReviewStore(AnalysisReviewPersistenceMixin):
    """Append-only human fixture-analysis reviews and event-chain evidence."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _review_from_row(row: Any) -> StoredAnalysisReview:
        return _review_from_row(row)

    @staticmethod
    def _review_event_hash(**kwargs: object) -> str:
        return _review_event_hash(**kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _review_rejected(message: str) -> Exception:
        return AnalysisReviewRejected(message)

    @staticmethod
    def _audit_replay(**kwargs: object) -> AnalysisReviewAuditReplay:
        return AnalysisReviewAuditReplay(**kwargs)  # type: ignore[arg-type]


class HumanAnalysisReviewService:
    """Record and revalidate human disposition of one fixture analysis."""

    def __init__(
        self,
        *,
        analysis_service: HumanResearchTaskFixtureAnalysisService,
        review_store: AnalysisReviewStore,
        now: Callable[[], str],
    ) -> None:
        self._analysis_service = analysis_service
        self._review_store = review_store
        self._now = now

    def review(
        self,
        analysis_id: str,
        request: HumanAnalysisReviewRequest,
    ) -> AnalysisReviewResult:
        existing = self._review_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.analysis_id != analysis_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "analysis review idempotency key was reused with different input"
                )
            return self._result(existing, reused=True)

        analysis = self._analysis_service.get(analysis_id)
        target = _analysis_review_target(analysis)
        if (
            request.decision == AnalysisReviewDecision.ACCEPT_AS_REVIEWED_MEMORY
            and not target.acceptance_eligible
        ):
            raise AnalysisReviewRejected(
                "fixture analysis cannot become reviewed memory: "
                + "; ".join(target.acceptance_errors)
            )
        review, reused = self._review_store.record(
            analysis_id=analysis.record.analysis_id,
            task_id=analysis.record.task_id,
            workflow_id=analysis.record.workflow_id,
            target=target,
            request=request,
            created_at=self._now(),
        )
        return self._result(review, reused=reused)

    def get(self, review_id: str) -> AnalysisReviewResult:
        return self._result(self._review_store.get(review_id), reused=True)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[AnalysisReviewResult, ...]:
        return tuple(
            self._result(review, reused=True)
            for review in self._review_store.list(
                analysis_id=analysis_id,
                limit=limit,
            )
        )

    def replay(self, review_id: str) -> AnalysisReviewReplay:
        return self.get(review_id).replay()

    def _result(
        self,
        review: StoredAnalysisReview,
        *,
        reused: bool,
    ) -> AnalysisReviewResult:
        analysis = self._analysis_service.get(review.analysis_id)
        target = _analysis_review_target(analysis)
        return AnalysisReviewResult(
            review=review,
            current_target=target,
            audit_replay=self._review_store.verify_replay(review.review_id),
            reused=reused,
        )


def _analysis_review_target(
    analysis: ResearchTaskAnalysisResult,
) -> AnalysisReviewTarget:
    errors = list(analysis.binding_errors)
    if analysis.workflow.status != WorkflowStatus.COMPLETED:
        errors.append(
            f"analysis_workflow_not_completed:{analysis.workflow.status.value}"
        )
    if analysis.workflow.partial_result:
        errors.append("analysis_workflow_is_partial")
    if not analysis.audit_replay.valid:
        errors.extend(
            f"analysis_audit_invalid:{item}" for item in analysis.audit_replay.errors
        )
        if not analysis.audit_replay.errors:
            errors.append("analysis_audit_invalid")
    if analysis.binding_validity != "valid":
        errors.append(f"analysis_binding_invalid:{analysis.binding_validity}")

    artifact_payloads: list[JsonObject] = []
    memory_artifacts = []
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
        artifact_payloads.append(
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind.value,
                "stored_fingerprint": artifact.fingerprint,
                "actual_fingerprint": actual_fingerprint,
                "evidence_reference_ids": list(artifact.evidence_reference_ids),
            }
        )
        if artifact.kind == ArtifactKind.MEMORY:
            memory_artifacts.append(artifact)

    artifact_kinds = {artifact.kind for artifact in analysis.artifacts}
    required_kinds = {
        ArtifactKind.CLAIM,
        ArtifactKind.DEBATE,
        ArtifactKind.REPORT,
        ArtifactKind.MEMORY,
    }
    if artifact_kinds != required_kinds:
        errors.append("analysis_artifact_lifecycle_incomplete")
    if len(memory_artifacts) != 1:
        errors.append("analysis_requires_exactly_one_memory_artifact")
    memory_artifact_id = (
        memory_artifacts[0].artifact_id if len(memory_artifacts) == 1 else None
    )
    if len(memory_artifacts) == 1:
        expected_sources = [
            artifact.artifact_id
            for artifact in analysis.artifacts
            if artifact.kind != ArtifactKind.MEMORY
        ]
        actual_sources = memory_artifacts[0].content.get("source_artifact_ids")
        if actual_sources != expected_sources:
            errors.append("memory_source_artifact_binding_drift")
    if analysis.memory_validity != "human_review_required_exact_context_only":
        errors.append(f"memory_not_reviewable:{analysis.memory_validity}")
    if any(item.get("status") != "completed" for item in analysis.tool_calls):
        errors.append("analysis_tool_call_not_completed")

    target_payload = {
        "analysis_id": analysis.record.analysis_id,
        "task_id": analysis.record.task_id,
        "workflow_id": analysis.record.workflow_id,
        "workflow_status": analysis.workflow.status.value,
        "workflow_failure_code": analysis.workflow.failure_code,
        "partial_result": analysis.workflow.partial_result,
        "context_snapshot_id": analysis.record.context_snapshot_id,
        "context_fingerprint": analysis.record.context_fingerprint,
        "binding_validity": analysis.binding_validity,
        "binding_errors": list(analysis.binding_errors),
        "memory_validity": analysis.memory_validity,
        "artifacts": artifact_payloads,
        "tool_calls": [
            {
                "call_id": item.get("call_id"),
                "tool_name": item.get("tool_name"),
                "status": item.get("status"),
                "evidence_reference_id": item.get("evidence_reference_id"),
            }
            for item in analysis.tool_calls
        ],
        "analysis_audit": {
            "valid": analysis.audit_replay.valid,
            "event_count": analysis.audit_replay.event_count,
            "last_event_hash": analysis.audit_replay.last_event_hash,
            "errors": list(analysis.audit_replay.errors),
        },
        "memory_artifact_id": memory_artifact_id,
    }
    return AnalysisReviewTarget(
        analysis_id=analysis.record.analysis_id,
        task_id=analysis.record.task_id,
        workflow_id=analysis.record.workflow_id,
        context_snapshot_id=analysis.record.context_snapshot_id,
        context_fingerprint=analysis.record.context_fingerprint,
        memory_artifact_id=memory_artifact_id,
        fingerprint=content_fingerprint(target_payload),
        acceptance_errors=tuple(dict.fromkeys(errors)),
    )


def _review_event_hash(
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


def _review_from_row(row: Any) -> StoredAnalysisReview:
    return StoredAnalysisReview(
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        task_id=str(row["task_id"]),
        workflow_id=str(row["workflow_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        analysis_target_fingerprint=str(row["analysis_target_fingerprint"]),
        memory_artifact_id=(
            str(row["memory_artifact_id"])
            if row["memory_artifact_id"] is not None
            else None
        ),
        reviewed_by=str(row["reviewed_by"]),
        decision=AnalysisReviewDecision(str(row["decision"])),
        note=str(row["note"]),
        created_at=str(row["created_at"]),
    )
