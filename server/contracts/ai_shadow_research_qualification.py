"""Stable contracts for provider-free account qualification of AI research."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from server.contracts.content_identity import canonical_json, content_fingerprint

SHADOW_RESEARCH_QUALIFICATION_SCHEMA = (
    "karkinos.ai.shadow_research_account_qualification.v1"
)
SHADOW_RESEARCH_QUALIFICATION_APPROVAL_SCHEMA = (
    "karkinos.ai.shadow_research_account_qualification_approval.v1"
)
SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION = (
    "approve_exact_account_qualified_candidate_for_paper_shadow_only_without_"
    "order_trade_or_capital_authority"
)
SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE = "paper_shadow"
SHADOW_RESEARCH_QUALIFICATION_RUNNING_STATUS = "running"
SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES = frozenset(
    {"blocked", "completed", "failed"}
)
SHADOW_RESEARCH_QUALIFICATION_RUN_STATUSES = frozenset(
    {
        SHADOW_RESEARCH_QUALIFICATION_RUNNING_STATUS,
        *SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES,
    }
)
SHADOW_RESEARCH_QUALIFICATION_CANDIDATE_STATUSES = frozenset(
    {"qualified", "blocked", "failed"}
)
SHADOW_RESEARCH_QUALIFICATION_FORMULA_SEMANTIC_SCHEMA = (
    "karkinos.ai.shadow_research_formula_semantic.v1"
)
SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_SCHEMA = (
    "karkinos.ai.shadow_research_account_qualification_attempt.v1"
)
SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE = (
    "ai_shadow_research_account_qualification_attempt"
)


class ShadowResearchQualificationRejected(ValueError):
    """Fail-closed account-qualification evidence rejection."""


def qualification_formula_semantic_fingerprint(
    strategy: Mapping[str, Any],
) -> str:
    """Bind formula meaning and frozen research inputs, excluding cash/cost.

    Qualification is allowed to rebind only the reviewed fee schedule and the
    reconciled account-sized initial cash.  The formula, universe, dataset,
    window, frequency, anti-lookahead assumptions, and parameters must remain
    byte-for-byte equivalent under canonical JSON.
    """

    formula_ast = strategy.get("formula_ast")
    universe = strategy.get("selected_universe")
    test_window = strategy.get("test_window")
    assumptions = strategy.get("anti_lookahead_assumptions")
    parameter_values = strategy.get("parameter_values")
    parameter_ranges = strategy.get("parameter_ranges")
    if not isinstance(formula_ast, Mapping):
        raise ShadowResearchQualificationRejected("qualification_formula_ast_invalid")
    if (
        not isinstance(universe, Sequence)
        or isinstance(universe, (str, bytes))
        or not universe
        or any(not str(item).strip() for item in universe)
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_formula_universe_invalid"
        )
    if not isinstance(test_window, Mapping) or set(test_window) != {
        "start_date",
        "end_date",
    }:
        raise ShadowResearchQualificationRejected(
            "qualification_formula_window_invalid"
        )
    if (
        not isinstance(assumptions, Sequence)
        or isinstance(assumptions, (str, bytes))
        or not isinstance(parameter_values, Mapping)
        or not isinstance(parameter_ranges, Mapping)
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_formula_semantic_payload_invalid"
        )
    payload = {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_FORMULA_SEMANTIC_SCHEMA,
        "formula_ast": dict(formula_ast),
        "selected_universe": [str(item) for item in universe],
        "dataset_snapshot_id": _required_text(
            strategy.get("dataset_snapshot_id"), "dataset_snapshot_id"
        ),
        "test_window": {
            "start_date": _required_text(test_window.get("start_date"), "start_date"),
            "end_date": _required_text(test_window.get("end_date"), "end_date"),
        },
        "frequency": _required_text(strategy.get("frequency"), "frequency"),
        "anti_lookahead_assumptions": [str(item) for item in assumptions],
        "parameter_values": dict(parameter_values),
        "parameter_ranges": dict(parameter_ranges),
    }
    return "sha256:" + content_fingerprint(payload)


def qualification_run_identity(
    *,
    source_run_id: str,
    market_date: str,
    source_selection_id: str,
    source_selection_fingerprint: str,
    source_backup_fingerprint: str,
    valuation_snapshot_id: str,
    valuation_snapshot_fingerprint: str,
    ledger_cutoff_id: int,
    ledger_fingerprint: str,
    account_evidence_reference: str,
    account_evidence_fingerprint: str,
    account_truth_source_fingerprint: str,
    account_truth_scope_fingerprint: str,
    reviewed_cost_model_reference: str,
    reviewed_fee_schedule_fingerprint: str,
    initial_cash_text: str,
    baseline_result_id: int,
) -> dict[str, Any]:
    """Validate and return the complete immutable qualification input binding."""

    values = {
        "source_run_id": source_run_id,
        "market_date": market_date,
        "source_selection_id": source_selection_id,
        "source_selection_fingerprint": source_selection_fingerprint,
        "source_backup_fingerprint": source_backup_fingerprint,
        "valuation_snapshot_id": valuation_snapshot_id,
        "valuation_snapshot_fingerprint": valuation_snapshot_fingerprint,
        "ledger_fingerprint": ledger_fingerprint,
        "account_evidence_reference": account_evidence_reference,
        "account_evidence_fingerprint": account_evidence_fingerprint,
        "account_truth_source_fingerprint": account_truth_source_fingerprint,
        "account_truth_scope_fingerprint": account_truth_scope_fingerprint,
        "reviewed_cost_model_reference": reviewed_cost_model_reference,
        "reviewed_fee_schedule_fingerprint": reviewed_fee_schedule_fingerprint,
    }
    normalized = {key: _required_text(value, key) for key, value in values.items()}
    normalized_ledger_cutoff = _positive_int(
        ledger_cutoff_id,
        field="ledger_cutoff",
    )
    normalized_baseline_result = _positive_int(
        baseline_result_id,
        field="baseline_result",
    )
    normalized_initial_cash = _private_positive_money_text(initial_cash_text)
    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        **normalized,
        "ledger_cutoff_id": normalized_ledger_cutoff,
        "initial_cash_text": normalized_initial_cash,
        "baseline_result_id": normalized_baseline_result,
    }


def qualification_run_input_fingerprint(identity: Mapping[str, Any]) -> str:
    """Fingerprint one already-validated immutable qualification binding."""

    return content_fingerprint(dict(identity))


def qualification_payload_fingerprint(
    payload: Mapping[str, Any],
    *,
    embedded_field: str,
) -> tuple[dict[str, Any], str]:
    """Canonicalize a result payload and reject a conflicting embedded hash."""

    normalized = dict(payload)
    embedded = normalized.pop(embedded_field, None)
    fingerprint = content_fingerprint(normalized)
    if embedded not in (None, "", fingerprint):
        raise ShadowResearchQualificationRejected(
            f"qualification_{embedded_field}_conflict"
        )
    return normalized, fingerprint


def normalize_qualification_blockers(blockers: Sequence[str] | None) -> list[str]:
    """Return a deterministic non-empty-string blocker set."""

    if blockers is None:
        return []
    if isinstance(blockers, (str, bytes)):
        raise ShadowResearchQualificationRejected("qualification_blockers_invalid")
    normalized = sorted({_required_text(item, "blocker") for item in blockers})
    return normalized


def build_qualification_candidate_values(
    *,
    qualification_run_id: str,
    source_candidate_id: str,
    source_draft_id: str,
    source_formula_fingerprint: str,
    qualified_formula_fingerprint: str,
    source_formula_semantic_fingerprint: str,
    qualified_formula_semantic_fingerprint: str,
    candidate_result_id: int | None,
    comparison: Mapping[str, Any],
    comparison_fingerprint: str | None,
    status: str,
    recommendation: str,
    rank: int,
    now: str,
) -> dict[str, Any]:
    """Validate one immutable account-qualified candidate record."""

    if status not in SHADOW_RESEARCH_QUALIFICATION_CANDIDATE_STATUSES:
        raise ShadowResearchQualificationRejected(
            "qualification_candidate_status_invalid"
        )
    normalized_recommendation = _required_text(recommendation, "recommendation")
    if (status == "qualified") != (normalized_recommendation == "paper_shadow_review"):
        raise ShadowResearchQualificationRejected(
            "qualification_candidate_recommendation_invalid"
        )
    normalized_source_formula = _required_text(
        source_formula_fingerprint, "source_formula_fingerprint"
    )
    normalized_qualified_formula = _required_text(
        qualified_formula_fingerprint, "qualified_formula_fingerprint"
    )
    normalized_source_semantic = _required_text(
        source_formula_semantic_fingerprint,
        "source_formula_semantic_fingerprint",
    )
    normalized_qualified_semantic = _required_text(
        qualified_formula_semantic_fingerprint,
        "qualified_formula_semantic_fingerprint",
    )
    if normalized_source_semantic != normalized_qualified_semantic:
        raise ShadowResearchQualificationRejected(
            "qualification_formula_semantics_changed"
        )
    normalized_result_id = qualification_optional_positive_int(
        candidate_result_id,
        field="candidate_result_id",
    )
    if status == "qualified" and normalized_result_id is None:
        raise ShadowResearchQualificationRejected(
            "qualification_candidate_result_required"
        )
    normalized_rank = _positive_int(rank, field="candidate_rank")
    comparison_payload, expected_comparison_fingerprint = (
        qualification_payload_fingerprint(
            comparison,
            embedded_field="comparison_fingerprint",
        )
    )
    if comparison_fingerprint not in (
        None,
        "",
        expected_comparison_fingerprint,
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_comparison_fingerprint_conflict"
        )
    expected_qualification_status = "passed" if status == "qualified" else status
    if (
        comparison_payload.get("research_capital_mode") != "account_bound"
        or comparison_payload.get("account_qualification_status")
        != expected_qualification_status
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_comparison_contract_invalid"
        )
    return {
        "qualification_run_id": _required_text(
            qualification_run_id, "qualification_run_id"
        ),
        "source_candidate_id": _required_text(
            source_candidate_id, "source_candidate_id"
        ),
        "source_draft_id": _required_text(source_draft_id, "source_draft_id"),
        "source_formula_fingerprint": normalized_source_formula,
        "qualified_formula_fingerprint": normalized_qualified_formula,
        "source_formula_semantic_fingerprint": normalized_source_semantic,
        "qualified_formula_semantic_fingerprint": normalized_qualified_semantic,
        "candidate_result_id": normalized_result_id,
        "comparison_json": canonical_json(comparison_payload),
        "comparison_fingerprint": expected_comparison_fingerprint,
        "status": status,
        "recommendation": normalized_recommendation,
        "rank": normalized_rank,
        "created_at": _required_text(now, "now"),
    }


def require_qualification_terminal_payload(
    *,
    run: Mapping[str, Any],
    status: str,
    selection: Mapping[str, Any],
    blockers: Sequence[str],
    failure_code: str | None,
) -> str | None:
    """Validate a terminal selection and return its selected candidate id."""

    if (
        selection.get("schema_version") != SHADOW_RESEARCH_QUALIFICATION_SCHEMA
        or selection.get("qualification_run_id") != run["qualification_run_id"]
        or selection.get("source_run_id") != run["source_run_id"]
        or selection.get("market_date") != run["market_date"]
        or selection.get("provider_call_performed") is not False
        or selection.get("broker_order_created") is not False
        or selection.get("capital_authority_granted") is not False
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_selection_binding_invalid"
        )
    selection_status = selection.get("status")
    winner_id = selection.get("winner_qualification_candidate_id")
    if status == "completed":
        if (
            blockers
            or failure_code
            or selection_status != "winner_selected"
            or not str(winner_id or "").strip()
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_completed_result_invalid"
            )
        return str(winner_id)
    if status == "blocked":
        if (
            not blockers
            or failure_code is not None
            or selection_status != "no_selection"
            or winner_id is not None
        ):
            raise ShadowResearchQualificationRejected(
                "qualification_blocked_result_invalid"
            )
        return None
    if not failure_code or selection_status != "failed" or winner_id is not None:
        raise ShadowResearchQualificationRejected("qualification_failed_result_invalid")
    return None


def qualification_candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    """Bind the exact qualified candidate evidence approved by a human."""

    return content_fingerprint(
        {
            key: candidate.get(key)
            for key in (
                "qualification_candidate_id",
                "qualification_run_id",
                "source_candidate_id",
                "source_draft_id",
                "source_formula_fingerprint",
                "qualified_formula_fingerprint",
                "source_formula_semantic_fingerprint",
                "qualified_formula_semantic_fingerprint",
                "candidate_result_id",
                "comparison_fingerprint",
                "status",
                "recommendation",
                "rank",
            )
        }
    )


def verified_qualification_payload(
    value: Any,
    *,
    expected_fingerprint: Any,
    error_code: str,
) -> dict[str, Any]:
    """Load canonical persisted JSON only when its fingerprint still matches."""

    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ShadowResearchQualificationRejected(error_code) from exc
    if (
        not isinstance(payload, dict)
        or content_fingerprint(payload) != expected_fingerprint
        or canonical_json(payload) != value
    ):
        raise ShadowResearchQualificationRejected(error_code)
    return payload


def qualification_run_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Rehydrate and verify one private persisted qualification run."""

    result = dict(row)
    identity = qualification_run_identity(
        source_run_id=result["source_run_id"],
        market_date=result["market_date"],
        source_selection_id=result["source_selection_id"],
        source_selection_fingerprint=result["source_selection_fingerprint"],
        source_backup_fingerprint=result["source_backup_fingerprint"],
        valuation_snapshot_id=result["valuation_snapshot_id"],
        valuation_snapshot_fingerprint=result["valuation_snapshot_fingerprint"],
        ledger_cutoff_id=result["ledger_cutoff_id"],
        ledger_fingerprint=result["ledger_fingerprint"],
        account_evidence_reference=result["account_evidence_reference"],
        account_evidence_fingerprint=result["account_evidence_fingerprint"],
        account_truth_source_fingerprint=result["account_truth_source_fingerprint"],
        account_truth_scope_fingerprint=result["account_truth_scope_fingerprint"],
        reviewed_cost_model_reference=result["reviewed_cost_model_reference"],
        reviewed_fee_schedule_fingerprint=result["reviewed_fee_schedule_fingerprint"],
        initial_cash_text=result["initial_cash_text"],
        baseline_result_id=result["baseline_result_id"],
    )
    if qualification_run_input_fingerprint(identity) != result["input_fingerprint"]:
        raise ShadowResearchQualificationRejected(
            "qualification_persisted_input_fingerprint_invalid"
        )
    selection_json = result.pop("selection_json", None)
    selection_fingerprint = result.get("selection_fingerprint")
    result["selection"] = (
        verified_qualification_payload(
            selection_json,
            expected_fingerprint=selection_fingerprint,
            error_code="qualification_persisted_selection_invalid",
        )
        if selection_json is not None
        else None
    )
    blockers_json = result.pop("blockers_json", "[]")
    try:
        blockers = json.loads(str(blockers_json))
    except json.JSONDecodeError as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_persisted_blockers_invalid"
        ) from exc
    if (
        not isinstance(blockers, list)
        or normalize_qualification_blockers(blockers) != blockers
        or canonical_json(blockers) != blockers_json
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_persisted_blockers_invalid"
        )
    result["blockers"] = blockers
    return result


def qualification_candidate_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Rehydrate and verify one private persisted qualification candidate."""

    result = dict(row)
    if (
        result["source_formula_semantic_fingerprint"]
        != result["qualified_formula_semantic_fingerprint"]
    ):
        raise ShadowResearchQualificationRejected(
            "qualification_persisted_formula_semantics_invalid"
        )
    comparison_json = result.pop("comparison_json")
    result["comparison"] = verified_qualification_payload(
        comparison_json,
        expected_fingerprint=result["comparison_fingerprint"],
        error_code="qualification_persisted_comparison_invalid",
    )
    return result


def qualification_required_text(value: Any, field: str) -> str:
    """Public boundary helper shared by qualification persistence."""

    return _required_text(value, field)


def qualification_optional_positive_int(value: Any, *, field: str) -> int | None:
    """Normalize one optional positive integer without accepting booleans."""

    if value is None:
        return None
    return _positive_int(value, field=field)


def qualification_bounded_limit(limit: Any) -> int:
    """Bound public list reads to a small deterministic page."""

    normalized = _positive_int(limit, field="limit")
    if normalized > 200:
        raise ShadowResearchQualificationRejected("qualification_limit_invalid")
    return normalized


def public_qualification_run_projection(
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a run without private capital or account-reference values."""

    selection = run.get("selection")
    if not isinstance(selection, Mapping):
        selection = {}
    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_run_id": run.get("qualification_run_id"),
        "source_run_id": run.get("source_run_id"),
        "market_date": run.get("market_date"),
        "source_selection_id": run.get("source_selection_id"),
        "source_selection_fingerprint": run.get("source_selection_fingerprint"),
        "source_backup_fingerprint": run.get("source_backup_fingerprint"),
        "valuation_snapshot_id": run.get("valuation_snapshot_id"),
        "valuation_snapshot_fingerprint": run.get("valuation_snapshot_fingerprint"),
        "ledger_cutoff_id": run.get("ledger_cutoff_id"),
        "ledger_fingerprint": run.get("ledger_fingerprint"),
        "account_evidence_fingerprint": run.get("account_evidence_fingerprint"),
        "account_truth_source_fingerprint": run.get("account_truth_source_fingerprint"),
        "account_truth_scope_fingerprint": run.get("account_truth_scope_fingerprint"),
        "reviewed_cost_model_reference": run.get("reviewed_cost_model_reference"),
        "reviewed_fee_schedule_fingerprint": run.get(
            "reviewed_fee_schedule_fingerprint"
        ),
        "baseline_result_id": run.get("baseline_result_id"),
        "input_fingerprint": run.get("input_fingerprint"),
        "status": run.get("status"),
        "selection_status": selection.get("status"),
        "winner_qualification_candidate_id": selection.get(
            "winner_qualification_candidate_id"
        ),
        "selection_fingerprint": run.get("selection_fingerprint"),
        "blockers": list(run.get("blockers") or []),
        "failure_code": run.get("failure_code"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "initial_cash_redacted": True,
        "private_account_values_redacted": True,
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "capital_authority_granted": False,
        "human_paper_shadow_approval_required": True,
    }


def public_qualification_candidate_projection(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a qualified candidate without its private comparison payload."""

    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_candidate_id": candidate.get("qualification_candidate_id"),
        "qualification_run_id": candidate.get("qualification_run_id"),
        "source_candidate_id": candidate.get("source_candidate_id"),
        "source_draft_id": candidate.get("source_draft_id"),
        "source_formula_fingerprint": candidate.get("source_formula_fingerprint"),
        "qualified_formula_fingerprint": candidate.get("qualified_formula_fingerprint"),
        "source_formula_semantic_fingerprint": candidate.get(
            "source_formula_semantic_fingerprint"
        ),
        "qualified_formula_semantic_fingerprint": candidate.get(
            "qualified_formula_semantic_fingerprint"
        ),
        "candidate_result_id": candidate.get("candidate_result_id"),
        "comparison_fingerprint": candidate.get("comparison_fingerprint"),
        "status": candidate.get("status"),
        "recommendation": candidate.get("recommendation"),
        "rank": candidate.get("rank"),
        "created_at": candidate.get("created_at"),
        "private_account_values_redacted": True,
        "provider_call_performed": False,
        "automatic_strategy_replacement_enabled": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "capital_authority_granted": False,
        "human_paper_shadow_approval_required": True,
    }


def public_qualification_approval_projection(
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the human audit fact with explicit non-authority semantics."""

    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_APPROVAL_SCHEMA,
        **dict(approval),
        "manual_confirmation_recorded": True,
        "authority_effect": "paper_shadow_research_only",
        "production_strategy_replaced": False,
        "strategy_registry_mutated": False,
        "broker_order_created": False,
        "broker_submission_enabled": False,
        "capital_authority_granted": False,
    }


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ShadowResearchQualificationRejected(f"qualification_{field}_required")
    return normalized


def _private_positive_money_text(value: Any) -> str:
    normalized = _required_text(value, "initial_cash_text")
    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise ShadowResearchQualificationRejected(
            "qualification_initial_cash_invalid"
        ) from exc
    if not amount.is_finite() or amount <= 0:
        raise ShadowResearchQualificationRejected("qualification_initial_cash_invalid")
    return normalized


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ShadowResearchQualificationRejected(f"qualification_{field}_invalid")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ShadowResearchQualificationRejected(
            f"qualification_{field}_invalid"
        ) from exc
    if normalized <= 0:
        raise ShadowResearchQualificationRejected(f"qualification_{field}_invalid")
    return normalized


__all__ = [
    "SHADOW_RESEARCH_QUALIFICATION_APPROVAL_SCHEMA",
    "SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_RUN_TYPE",
    "SHADOW_RESEARCH_QUALIFICATION_ATTEMPT_SCHEMA",
    "SHADOW_RESEARCH_QUALIFICATION_CANDIDATE_STATUSES",
    "SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION",
    "SHADOW_RESEARCH_QUALIFICATION_FORMULA_SEMANTIC_SCHEMA",
    "SHADOW_RESEARCH_QUALIFICATION_RUNNING_STATUS",
    "SHADOW_RESEARCH_QUALIFICATION_RUN_STATUSES",
    "SHADOW_RESEARCH_QUALIFICATION_SCHEMA",
    "SHADOW_RESEARCH_QUALIFICATION_TARGET_STAGE",
    "SHADOW_RESEARCH_QUALIFICATION_TERMINAL_STATUSES",
    "ShadowResearchQualificationRejected",
    "build_qualification_candidate_values",
    "normalize_qualification_blockers",
    "public_qualification_approval_projection",
    "public_qualification_candidate_projection",
    "public_qualification_run_projection",
    "qualification_payload_fingerprint",
    "qualification_bounded_limit",
    "qualification_candidate_record",
    "qualification_candidate_fingerprint",
    "qualification_formula_semantic_fingerprint",
    "qualification_optional_positive_int",
    "qualification_required_text",
    "qualification_run_identity",
    "qualification_run_input_fingerprint",
    "qualification_run_record",
    "require_qualification_terminal_payload",
    "verified_qualification_payload",
]
