"""Deterministic value functions for external-analysis human reviews."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from server.ai_runtime.contracts import JsonObject, content_fingerprint


def external_analysis_review_event_hash(
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


def external_analysis_review_cost_evidence(
    request: object,
    quality_evidence: Mapping[str, object],
) -> JsonObject:
    pricing = getattr(request, "pricing_snapshot")
    if pricing is None:
        return {
            "status": "unpriced",
            "currency": None,
            "estimated_cost": None,
            "pricing_source": None,
            "pricing_effective_at": None,
            "pricing_unavailable_reason": getattr(
                request,
                "pricing_unavailable_reason",
            ),
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
        "estimated_cost": external_analysis_decimal_text(prompt_cost + completion_cost),
        "prompt_cost": external_analysis_decimal_text(prompt_cost),
        "completion_cost": external_analysis_decimal_text(completion_cost),
        "pricing_source": pricing.source,
        "pricing_effective_at": pricing.effective_at,
        "pricing_unavailable_reason": None,
        "calculation": "reviewer_pricing_x_provider_reported_tokens",
        "provider_invoice": False,
    }


def external_analysis_non_negative_decimal(
    value: object,
    field_name: str,
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative finite decimal")
    return parsed


def external_analysis_decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
