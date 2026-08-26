"""Deterministic values and binding checks for memory-informed analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from server.contracts.memory_informed_analysis import (
    MEMORY_INFORMED_CLAIM_STAGE_ID,
    MEMORY_INFORMED_DEFINITION_ID,
    MemoryInformedAnalysisRecord,
    MemoryInformedAnalysisRejected,
)

from .contracts import (
    ArtifactKind,
    EvidenceBoundContextSnapshot,
    JsonObject,
    ResearchWorkflow,
    StoredArtifact,
    ToolCallStatus,
    WorkflowStatus,
    content_fingerprint,
)
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from .memory_retrieval import (
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalResult,
)
from .store import AiAuditStore


@dataclass(frozen=True)
class MemoryInformedInputs:
    retrieval: ReviewedMemoryRetrievalResult
    context: EvidenceBoundContextSnapshot
    records: tuple[CanonicalEvidenceRecord, ...]


def load_memory_informed_inputs_value(
    *,
    retrieval_service: HumanReviewedMemoryRetrievalService,
    ai_store: AiAuditStore,
    evidence_repository: CanonicalEvidenceRepository,
    retrieval_id: str,
) -> MemoryInformedInputs:
    """Resolve one eligible retrieval and its exact current canonical records."""
    retrieval = retrieval_service.get(retrieval_id)
    if not retrieval.retrieval_eligible:
        raise MemoryInformedAnalysisRejected(
            "memory-informed analysis requires a currently eligible "
            "reviewed-memory retrieval: " + "; ".join(retrieval.invalidation_reasons)
        )
    context = ai_store.get_context(retrieval.current_target.current_context_snapshot_id)
    if context.fingerprint != retrieval.current_target.current_context_fingerprint:
        raise EvidenceIdentityMismatch("retrieval current context drifted")
    records = load_memory_informed_current_records_value(
        evidence_repository=evidence_repository,
        context=context,
    )
    return MemoryInformedInputs(
        retrieval=retrieval,
        context=context,
        records=records,
    )


def load_memory_informed_current_binding_value(
    *,
    retrieval_service: HumanReviewedMemoryRetrievalService,
    ai_store: AiAuditStore,
    evidence_repository: CanonicalEvidenceRepository,
    retrieval_id: str,
    context_snapshot_id: str,
) -> tuple[
    ReviewedMemoryRetrievalResult | None,
    tuple[CanonicalEvidenceRecord, ...],
]:
    """Rebuild a stored analysis binding without refreshing any source."""
    try:
        retrieval = retrieval_service.get(retrieval_id)
        context = ai_store.get_context(context_snapshot_id)
        records = load_memory_informed_current_records_value(
            evidence_repository=evidence_repository,
            context=context,
        )
    except (LookupError, EvidenceIdentityMismatch, ValueError):
        return None, ()
    return retrieval, records


def load_memory_informed_current_records_value(
    *,
    evidence_repository: CanonicalEvidenceRepository,
    context: EvidenceBoundContextSnapshot,
) -> tuple[CanonicalEvidenceRecord, ...]:
    """Read and validate every record in an immutable evidence context."""
    expected_snapshot_id = f"ai-context-{context.fingerprint[:24]}"
    if context.snapshot_id != expected_snapshot_id:
        raise EvidenceIdentityMismatch("current context fingerprint drifted")
    records: list[CanonicalEvidenceRecord] = []
    for reference in context.evidence_references:
        record = evidence_repository.get(reference.reference_id)
        if record is None:
            raise EvidenceIdentityMismatch(
                f"current evidence missing:{reference.reference_id}"
            )
        if record.to_reference() != reference:
            raise EvidenceIdentityMismatch(
                f"current evidence reference drifted:{reference.reference_id}"
            )
        if (
            record.valuation_snapshot_id != context.valuation_snapshot_id
            or record.ledger_cutoff_id != context.ledger_cutoff_id
            or record.ledger_fingerprint != context.ledger_fingerprint
        ):
            raise EvidenceIdentityMismatch(
                "current evidence financial identity drifted:"
                f"{reference.reference_id}"
            )
        if not record.authoritative:
            raise EvidenceIdentityMismatch(
                f"current evidence is not complete:{reference.reference_id}:"
                f"{record.status}"
            )
        records.append(record)
    if not records:
        raise EvidenceIdentityMismatch("current context has no evidence")
    return tuple(sorted(records, key=lambda item: item.reference_id))


def memory_informed_binding_errors(
    *,
    record: MemoryInformedAnalysisRecord,
    workflow: ResearchWorkflow,
    retrieval: ReviewedMemoryRetrievalResult | None,
    records: tuple[CanonicalEvidenceRecord, ...],
    artifacts: tuple[StoredArtifact, ...],
    tool_calls: tuple[JsonObject, ...],
    audit_valid: bool,
) -> tuple[str, ...]:
    """Revalidate every persisted identity used by a finished workflow."""
    errors: list[str] = []
    if record.stored_retrieval_id != record.request.retrieval_id:
        errors.append("analysis_retrieval_binding_drift")
    if record.stored_idempotency_key != record.request.idempotency_key:
        errors.append("analysis_idempotency_binding_drift")
    if record.request_fingerprint != record.request.fingerprint:
        errors.append("analysis_request_fingerprint_drift")
    if workflow.definition.definition_id != MEMORY_INFORMED_DEFINITION_ID:
        errors.append("workflow_definition_drift")
    if workflow.context_snapshot_id != record.context_snapshot_id:
        errors.append("workflow_context_snapshot_drift")
    if workflow.context_fingerprint != record.context_fingerprint:
        errors.append("workflow_context_fingerprint_drift")
    if retrieval is None:
        errors.append("retrieval_or_current_evidence_invalid")
    else:
        if not retrieval.retrieval_eligible:
            errors.append("retrieval_no_longer_eligible")
        if retrieval.current_target.fingerprint != record.retrieval_target_fingerprint:
            errors.append("retrieval_target_fingerprint_drift")
        if (
            retrieval.current_target.current_context_snapshot_id
            != record.context_snapshot_id
        ):
            errors.append("retrieval_context_snapshot_drift")
        if (
            retrieval.current_target.current_context_fingerprint
            != record.context_fingerprint
        ):
            errors.append("retrieval_context_fingerprint_drift")
    if not audit_valid:
        errors.append("workflow_audit_invalid")

    expected_reads = {(item.tool_name, item.reference_id) for item in records}
    actual_reads = {
        (str(item.get("tool_name")), str(item.get("evidence_reference_id")))
        for item in tool_calls
        if item.get("status") == ToolCallStatus.COMPLETED.value
    }
    if actual_reads != expected_reads or len(tool_calls) != len(expected_reads):
        errors.append("current_evidence_tool_read_set_incomplete")
    if any(
        item.get("stage_id") != MEMORY_INFORMED_CLAIM_STAGE_ID
        or item.get("status") != ToolCallStatus.COMPLETED.value
        for item in tool_calls
    ):
        errors.append("current_evidence_tool_call_invalid")

    expected_reference_ids = tuple(item.reference_id for item in records)
    for artifact in artifacts:
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
        if tuple(artifact.evidence_reference_ids) != expected_reference_ids:
            errors.append(f"artifact_current_evidence_drift:{artifact.artifact_id}")
        if artifact.content.get("retrieval_id") != record.request.retrieval_id:
            errors.append(f"artifact_retrieval_binding_drift:{artifact.artifact_id}")
        if artifact.content.get("retrieval_target_fingerprint") != (
            record.retrieval_target_fingerprint
        ):
            errors.append(f"artifact_retrieval_target_drift:{artifact.artifact_id}")
        if artifact.content.get("memory_input_is_current_fact") is not False:
            errors.append(f"artifact_promotes_memory_to_fact:{artifact.artifact_id}")
        if artifact.content.get("authority_effect") != "none":
            errors.append(f"artifact_authority_effect_drift:{artifact.artifact_id}")
    if workflow.status == WorkflowStatus.COMPLETED and tuple(
        item.kind for item in artifacts
    ) != (ArtifactKind.CLAIM, ArtifactKind.DEBATE, ArtifactKind.REPORT):
        errors.append("analysis_artifact_lifecycle_incomplete")
    return tuple(dict.fromkeys(errors))


def memory_informed_artifact_payload(artifact: StoredArtifact) -> JsonObject:
    return {
        "artifact_id": artifact.artifact_id,
        "stage_id": artifact.stage_id,
        "role_id": artifact.role_id,
        "kind": artifact.kind.value,
        "content": dict(artifact.content),
        "evidence_reference_ids": list(artifact.evidence_reference_ids),
        "fingerprint": artifact.fingerprint,
        "created_at": artifact.created_at,
        "authority_effect": "none",
    }


def memory_informed_lease_expiry(claimed_at: str, seconds: int) -> str:
    instant = datetime.fromisoformat(claimed_at)
    if instant.tzinfo is None:
        raise ValueError("run claim timestamp must include timezone")
    return (instant + timedelta(seconds=seconds)).isoformat()
