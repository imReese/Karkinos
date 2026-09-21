"""Read-only operational health projection for verified market-data source routing."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from server.services.verified_daily_market_data import (
    VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
)

VERIFIED_SOURCE_HEALTH_SCHEMA_VERSION = "karkinos.market_source_health.v1"
_SOURCE_RESOLUTION_SCHEMA_VERSION = "karkinos.market_daily_source_resolution.v1"
_OUTCOMES = ("matched", "conflict", "unavailable", "quality_blocked")


def build_verified_source_health_response(
    db: object | None,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Aggregate recent durable source-resolution events without contacting providers."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("verified_source_health_limit_invalid")

    rows: list[dict[str, Any]] = []
    if db is not None and hasattr(db, "list_events_sync"):
        rows = list(
            db.list_events_sync(
                event_type=VERIFIED_DAILY_SOURCE_RESOLUTION_EVENT,
                limit=limit,
            )
        )
    return summarize_verified_source_resolution_events(rows, window_limit=limit)


def summarize_verified_source_resolution_events(
    rows: list[dict[str, Any]],
    *,
    window_limit: int,
) -> dict[str, Any]:
    """Build deterministic counts from newest-first event-log rows."""
    outcome_counts: Counter[str] = Counter()
    attempted_pair_counts: Counter[tuple[str, str]] = Counter()
    selected_pair_counts: Counter[tuple[str, str]] = Counter()
    unavailable_provider_counts: Counter[str] = Counter()
    source_policy_ids: set[str] = set()
    failover_count = 0
    invalid_event_count = 0
    latest: dict[str, Any] | None = None
    sample_count = 0

    for row in rows:
        payload = _event_payload(row)
        if payload is None:
            invalid_event_count += 1
            continue
        try:
            normalized = _normalize_resolution(payload)
        except (TypeError, ValueError):
            invalid_event_count += 1
            continue

        sample_count += 1
        outcome_counts[normalized["outcome"]] += 1
        source_policy_ids.add(normalized["source_policy_id"])
        for pair in normalized["attempted_pairs"]:
            attempted_pair_counts[pair] += 1
        selected_pair = normalized["selected_pair"]
        if selected_pair is not None:
            selected_pair_counts[selected_pair] += 1
        for provider in normalized["unavailable_providers"]:
            unavailable_provider_counts[provider] += 1

        if (
            normalized["unavailable_providers"]
            or len(normalized["attempted_pairs"]) > 1
        ):
            failover_count += 1

        if latest is None:
            latest = {
                "timestamp": str(row.get("timestamp") or ""),
                "outcome": normalized["outcome"],
                "source_policy_id": normalized["source_policy_id"],
                "selected_pair": _pair_payload(selected_pair),
                "unavailable_providers": list(normalized["unavailable_providers"]),
                "result_ref": normalized["result_ref"],
                "error_type": normalized["error_type"],
            }

    return {
        "schema_version": VERIFIED_SOURCE_HEALTH_SCHEMA_VERSION,
        "status": "observed" if sample_count else "no_samples",
        "window_limit": window_limit,
        "sample_count": sample_count,
        "invalid_event_count": invalid_event_count,
        "outcome_counts": {outcome: outcome_counts[outcome] for outcome in _OUTCOMES},
        "failover_count": failover_count,
        "attempted_pair_counts": _pair_counts(attempted_pair_counts),
        "selected_pair_counts": _pair_counts(selected_pair_counts),
        "unavailable_provider_counts": [
            {"provider": provider, "count": count}
            for provider, count in sorted(
                unavailable_provider_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "source_policy_ids": sorted(source_policy_ids),
        "latest": latest,
    }


def _event_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    raw = row.get("payload_json")
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != _SOURCE_RESOLUTION_SCHEMA_VERSION:
        raise ValueError("verified_source_health_schema_unsupported")

    outcome = _text(payload.get("outcome"))
    if outcome not in _OUTCOMES:
        raise ValueError("verified_source_health_outcome_invalid")

    source_policy_id = _text(payload.get("source_policy_id"))

    raw_pairs = payload.get("attempted_pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("verified_source_health_attempted_pairs_invalid")
    attempted_pairs = tuple(_pair(item) for item in raw_pairs)

    raw_unavailable = payload.get("unavailable_providers")
    if not isinstance(raw_unavailable, list):
        raise ValueError("verified_source_health_unavailable_invalid")
    unavailable_providers = tuple(sorted({_text(item) for item in raw_unavailable}))

    raw_selected = payload.get("selected_pair")
    selected_pair = None if raw_selected is None else _pair(raw_selected)

    result_ref = payload.get("result_ref")
    if result_ref is not None:
        result_ref = _text(result_ref)
    error_type = payload.get("error_type")
    if error_type is not None:
        error_type = _text(error_type)

    return {
        "outcome": outcome,
        "source_policy_id": source_policy_id,
        "attempted_pairs": attempted_pairs,
        "unavailable_providers": unavailable_providers,
        "selected_pair": selected_pair,
        "result_ref": result_ref,
        "error_type": error_type,
    }


def _pair(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise TypeError("verified_source_health_pair_invalid")
    return (_text(value.get("primary")), _text(value.get("comparison")))


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("verified_source_health_text_invalid")
    return value.strip()


def _pair_payload(pair: tuple[str, str] | None) -> dict[str, str] | None:
    if pair is None:
        return None
    return {"primary": pair[0], "comparison": pair[1]}


def _pair_counts(
    counts: Counter[tuple[str, str]],
) -> list[dict[str, object]]:
    return [
        {"primary": primary, "comparison": comparison, "count": count}
        for (primary, comparison), count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )
    ]


__all__ = [
    "VERIFIED_SOURCE_HEALTH_SCHEMA_VERSION",
    "build_verified_source_health_response",
    "summarize_verified_source_resolution_events",
]
