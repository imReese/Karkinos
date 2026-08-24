"""Record projections and persisted evidence validation for AI shadow research."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_MAX_CANDIDATES,
    ShadowResearchRejected,
    shadow_research_json_object,
)


def require_verified_no_selection(
    row: sqlite3.Row | None,
    *,
    run_id: str,
    market_date: str,
) -> str:
    if row is None:
        raise ShadowResearchRejected(
            "corrected_panel_rearm_requires_verified_no_selection"
        )
    try:
        payload = json.loads(str(row["selection_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ShadowResearchRejected(
            "corrected_panel_rearm_selection_fingerprint_invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise ShadowResearchRejected(
            "corrected_panel_rearm_selection_fingerprint_invalid"
        )
    expected_fingerprint = payload.pop("selection_fingerprint", None)
    if (
        expected_fingerprint != row["selection_fingerprint"]
        or content_fingerprint(payload) != expected_fingerprint
        or payload.get("run_id") != run_id
        or payload.get("market_date") != market_date
        or payload.get("status") != "no_selection"
        or payload.get("winner_candidate_id") is not None
        or int(payload.get("expected_candidate_count") or 0)
        != SHADOW_RESEARCH_MAX_CANDIDATES
        or int(payload.get("observed_candidate_count") or 0)
        != SHADOW_RESEARCH_MAX_CANDIDATES
        or int(payload.get("eligible_candidate_count") or 0) != 0
        or payload.get("automatic_strategy_replacement_enabled") is not False
        or payload.get("broker_submission_enabled") is not False
    ):
        raise ShadowResearchRejected(
            "corrected_panel_rearm_selection_fingerprint_invalid"
        )
    return str(expected_fingerprint)


def shadow_research_candidate_row(
    row: sqlite3.Row | Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(row)
    result["comparison"] = shadow_research_json_object(
        result.pop("comparison_json", "{}")
    )
    result.update(
        {
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "human_paper_shadow_approval_required": True,
        }
    )
    return result
