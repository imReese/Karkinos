"""Row projection for persisted external-analysis human reviews."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping


class ExternalAnalysisReviewProjectionMixin:
    _request_type: Any
    _decision_type: Any
    _rubric_type: Any
    _pricing_type: Any
    _stored_review_type: Any

    def _review_from_row(self, row: sqlite3.Row) -> object:
        payload = json.loads(str(row["request_json"]))
        rubric_payload = payload["quality_rubric"]
        pricing_payload = payload.get("pricing_snapshot")
        request = self._request_type(
            idempotency_key=str(payload["idempotency_key"]),
            reviewed_by=str(payload["reviewed_by"]),
            decision=self._decision_type(str(payload["decision"])),
            note=str(payload["note"]),
            quality_rubric=self._rubric_type(
                evidence_grounding=int(rubric_payload["evidence_grounding"]),
                contradiction_handling=int(rubric_payload["contradiction_handling"]),
                uncertainty_calibration=int(rubric_payload["uncertainty_calibration"]),
                decision_usefulness=int(rubric_payload["decision_usefulness"]),
            ),
            factual_error_count=int(payload["factual_error_count"]),
            unsupported_claim_count=int(payload["unsupported_claim_count"]),
            pricing_snapshot=(
                self._pricing_type(
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
        return self._stored_review_type(
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
