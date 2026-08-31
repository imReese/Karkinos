"""Deterministic values for revocable external reviewed memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .contracts import (
    ArtifactKind,
    JsonObject,
    StoredArtifact,
    content_fingerprint,
)


def external_reviewed_memory_content(
    *,
    review_id: str,
    analysis_id: str,
    report: StoredArtifact,
    source_context_snapshot_id: str,
    source_context_fingerprint: str,
    source_retrieval_id: str | None,
    source_retrieval_target_fingerprint: str | None,
    provider_id: str,
    model_id: str,
    prompt_version: str,
    review_note: str,
    reviewed_by: str,
    human_rubric: dict[str, int],
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
        "schema_version": "karkinos.ai.external_reviewed_memory_artifact.v1",
        "scope": f"external-analysis/{analysis_id}",
        "source_review_id": review_id,
        "source_analysis_id": analysis_id,
        "source_report_artifact_id": report.artifact_id,
        "source_report_artifact_fingerprint": report.fingerprint,
        "source_context_snapshot_id": source_context_snapshot_id,
        "source_context_fingerprint": source_context_fingerprint,
        "source_retrieval_id": source_retrieval_id,
        "source_retrieval_target_fingerprint": source_retrieval_target_fingerprint,
        "source_provider_id": provider_id,
        "source_model_id": model_id,
        "source_prompt_version": prompt_version,
        "reviewed_by": reviewed_by,
        "review_note": review_note,
        "human_quality_rubric": dict(human_rubric),
        "historical_report": normalized_report,
        "provider_provenance": safe_provenance,
        "validity_status": (
            "reviewed_historical_research_invalid_on_source_evidence_or_audit_"
            "drift_and_explicitly_revocable"
        ),
        "human_review_required_on_retrieval": True,
        "automatic_recall_allowed": False,
        "is_current_fact": False,
        "requires_current_evidence_rebinding": True,
        "decision_input_created": False,
        "trade_plan_created": False,
        "authority_effect": "none",
    }


def external_reviewed_memory_artifact_payload(
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


def external_reviewed_memory_optional_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def external_reviewed_memory_event_hash(
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
