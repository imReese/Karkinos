"""Record projections and persisted evidence validation for AI shadow research."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    ShadowResearchRejected,
    shadow_research_json_object,
)

SHADOW_RESEARCH_CAPITAL_MODE_LEGACY_UNKNOWN = "legacy_unknown"


def normalize_shadow_research_run_context(
    *,
    research_capital_mode: str,
    research_context_id: str | None,
    valuation_snapshot_id: str | None,
    ledger_cutoff_id: int | None,
) -> dict[str, Any]:
    """Validate one explicit run context without inferring it from legacy fields."""

    mode = str(research_capital_mode or "").strip()
    context_id = str(research_context_id or "").strip() or None
    valuation_id = str(valuation_snapshot_id or "").strip()
    if isinstance(ledger_cutoff_id, bool):
        raise ShadowResearchRejected("research_run_ledger_cutoff_invalid")
    try:
        ledger_id = int(ledger_cutoff_id or 0)
    except (TypeError, ValueError) as exc:
        raise ShadowResearchRejected("research_run_ledger_cutoff_invalid") from exc
    if ledger_id < 0:
        raise ShadowResearchRejected("research_run_ledger_cutoff_invalid")

    if mode == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL:
        if context_id is None or valuation_id or ledger_id != 0:
            raise ShadowResearchRejected(
                "normalized_research_run_context_binding_invalid"
            )
    elif mode == SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND:
        if (
            context_id is None
            or not valuation_id
            or ledger_id <= 0
            or context_id != valuation_id
        ):
            raise ShadowResearchRejected("account_bound_research_run_context_invalid")
    elif mode == SHADOW_RESEARCH_CAPITAL_MODE_LEGACY_UNKNOWN:
        if context_id is not None:
            raise ShadowResearchRejected("legacy_research_run_context_invalid")
    else:
        raise ShadowResearchRejected("research_run_capital_mode_invalid")

    return {
        "research_capital_mode": mode,
        "research_context_id": context_id,
        "valuation_snapshot_id": valuation_id,
        "ledger_cutoff_id": ledger_id,
    }


def shadow_research_run_context_matches(
    run: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    return (
        str(run.get("research_capital_mode") or "") == expected["research_capital_mode"]
        and (str(run.get("research_context_id") or "").strip() or None)
        == expected["research_context_id"]
        and str(run.get("valuation_snapshot_id") or "").strip()
        == expected["valuation_snapshot_id"]
        and int(run.get("ledger_cutoff_id") or 0) == expected["ledger_cutoff_id"]
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
