"""Evidence projection for one external-analysis review target."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .contracts import (
    ArtifactKind,
    JsonObject,
    WorkflowStatus,
    content_fingerprint,
)
from .external_memory_informed_analysis import ExternalMemoryAnalysisResult

EXPECTED_ARTIFACT_KINDS = (
    ArtifactKind.CLAIM,
    ArtifactKind.DEBATE,
    ArtifactKind.REPORT,
)
EXPECTED_STAGE_COUNT = 3


def build_external_analysis_review_target(
    analysis: ExternalMemoryAnalysisResult,
    *,
    target_type: Callable[..., object],
    expected_artifact_kinds: tuple[ArtifactKind, ...] = EXPECTED_ARTIFACT_KINDS,
    expected_stage_count: int = EXPECTED_STAGE_COUNT,
) -> object:
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

    if tuple(item.kind for item in analysis.artifacts) != expected_artifact_kinds:
        errors.append("analysis_artifact_lifecycle_incomplete")
    if len(report_artifacts) != 1:
        errors.append("analysis_requires_exactly_one_report_artifact")
    report_artifact_id = (
        report_artifacts[0].artifact_id if len(report_artifacts) == 1 else None
    )

    model_call_evidence = [item.to_dict() for item in analysis.model_calls]
    if len(analysis.model_calls) != expected_stage_count:
        errors.append("analysis_model_call_lifecycle_incomplete")
    if any(item.status != "completed" for item in analysis.model_calls):
        errors.append("analysis_model_call_not_completed")
    prompt_values = [item.usage.get("prompt_tokens") for item in analysis.model_calls]
    completion_values = [
        item.usage.get("completion_tokens") for item in analysis.model_calls
    ]
    usage_complete = (
        len(prompt_values) == expected_stage_count
        and all(isinstance(item, int) and item >= 0 for item in prompt_values)
        and all(isinstance(item, int) and item >= 0 for item in completion_values)
    )
    prompt_tokens = _token_total(prompt_values, complete=usage_complete)
    completion_tokens = _token_total(completion_values, complete=usage_complete)
    total_tokens = (
        int(prompt_tokens) + int(completion_tokens)
        if prompt_tokens is not None and completion_tokens is not None
        else None
    )
    latency_complete = len(latencies) == len(analysis.artifacts) == expected_stage_count
    quality_evidence: JsonObject = {
        "status": (
            "complete"
            if usage_complete
            and latency_complete
            and cited_item_count == citation_item_count
            and len(analysis.artifacts) == expected_stage_count
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
    return target_type(
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


def _token_total(values: Sequence[object], *, complete: bool) -> int | None:
    if not complete:
        return None
    total = 0
    for value in values:
        if isinstance(value, int):
            total += value
    return total
