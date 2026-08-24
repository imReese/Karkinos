"""Persisted-fact preparation checks for the reviewed decision window."""

from __future__ import annotations

from typing import Any

from server.services.automation_control import AutomationControlService
from server.services.daily_candidate_execution_closure import (
    build_daily_candidate_execution_closure,
)
from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION,
)
from server.services.daily_decision_evidence_identity import fingerprint_json
from server.services.daily_decision_evidence_values import (
    aware_datetime,
    count,
    is_sha256,
    object_dict,
    policy_allows_paper_shadow,
    shanghai_date,
)
from server.services.daily_decision_preflight_operator import build_preflight_gate


def build_daily_candidate_preparation_check(
    state: Any,
    *,
    run_date: str,
) -> dict[str, Any]:
    """Project durable pre-window gates from persisted facts only."""

    from server.account_truth_gate import (
        ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION,
        build_latest_account_truth_promotion_evidence,
    )
    from server.services.daily_candidate_execution_closure import (
        verify_daily_candidate_execution_closure,
    )
    from server.services.reviewed_fee_schedule import (
        build_reviewed_fee_schedule_review_status,
    )
    from server.services.strategy_promotion_pipeline import (
        StrategyPromotionPipeline,
        resolve_strategy_order_generation_gate,
    )

    automation_status = AutomationControlService(
        db=state.db,
        trading_controls=getattr(state, "trading_controls", None),
    ).get_status()
    account_truth = build_latest_account_truth_promotion_evidence(state)
    reviewed_fees = build_reviewed_fee_schedule_review_status(
        state,
        as_of_date=run_date,
    )
    execution_closure = build_daily_candidate_execution_closure(state.db)

    policy_blockers = []
    if not policy_allows_paper_shadow(automation_status):
        policy_blockers.append(
            "daily_candidate_kill_switch_enabled"
            if automation_status.get("kill_switch_enabled") is True
            else "daily_candidate_safe_automation_policy_blocked"
        )

    account_truth_blockers = [
        str(item) for item in account_truth.get("blockers") or [] if str(item)
    ]
    if account_truth.get("schema_version") != (
        ACCOUNT_TRUTH_PROMOTION_EVIDENCE_SCHEMA_VERSION
    ):
        account_truth_blockers.append("account_truth_promotion_contract_invalid")
    if account_truth.get("status") != "clear":
        account_truth_blockers.append("account_truth_promotion_not_clear")
    if account_truth.get("gate_status") != "pass":
        account_truth_blockers.append("account_truth_gate_not_pass")
    if account_truth.get("data_freshness_status") != "fresh":
        account_truth_blockers.append("account_truth_not_fresh")
    if account_truth.get("reconciliation_status") != "pass":
        account_truth_blockers.append("account_truth_reconciliation_not_pass")
    captured_at = aware_datetime(account_truth.get("captured_at"))
    if shanghai_date(captured_at) != run_date:
        account_truth_blockers.append("account_truth_not_captured_on_market_date")
    if not is_sha256(account_truth.get("source_fingerprint")):
        account_truth_blockers.append("account_truth_source_fingerprint_invalid")
    if account_truth.get("does_not_mutate_production_ledger") is not True:
        account_truth_blockers.append("account_truth_read_boundary_invalid")
    if account_truth.get("does_not_issue_execution_authority") is not True:
        account_truth_blockers.append("account_truth_authority_boundary_invalid")
    if account_truth.get("broker_submission_enabled") is not False:
        account_truth_blockers.append("account_truth_broker_boundary_invalid")

    fee_blockers = [
        str(item) for item in reviewed_fees.get("blockers") or [] if str(item)
    ]
    fee_review = object_dict(reviewed_fees.get("review"))
    fee_review_fingerprint = str(fee_review.get("review_fingerprint") or "")
    if reviewed_fees.get("status") != "active":
        fee_blockers.append("reviewed_fee_schedule_not_active")
    if not is_sha256(fee_review_fingerprint):
        fee_blockers.append("reviewed_fee_schedule_review_fingerprint_invalid")
    expected_fee_boundaries = {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    for field, expected in expected_fee_boundaries.items():
        if reviewed_fees.get(field) is not expected:
            fee_blockers.append(f"reviewed_fee_schedule_{field}_invalid")

    strategy_states = sorted(
        StrategyPromotionPipeline(db=state.db).list_states(),
        key=lambda item: str(item.get("strategy_id") or ""),
    )
    strategy_blockers: list[str] = []
    passing_strategy_count = 0
    if len(strategy_states) > 100:
        strategy_blockers.append("strategy_promotion_state_scan_truncated")
    for promotion_state in strategy_states[:100]:
        strategy_id = str(promotion_state.get("strategy_id") or "")
        if not strategy_id:
            strategy_blockers.append("strategy_promotion_identity_missing")
            continue
        try:
            gate, gate_blockers = resolve_strategy_order_generation_gate(
                state.db,
                strategy_id,
                as_of_date=run_date,
            )
        except Exception:  # noqa: BLE001 - projection failure remains fail-closed
            strategy_blockers.append("strategy_promotion_projection_failed_closed")
            continue
        boundaries_valid = bool(
            gate.get("persisted_facts_only") is True
            and gate.get("provider_contact_performed") is False
            and gate.get("does_not_create_order") is True
            and gate.get("does_not_authorize_execution") is True
            and gate.get("does_not_change_capital_authority") is True
            and gate.get("broker_submission_enabled") is False
        )
        if gate.get("status") == "pass" and not gate_blockers and boundaries_valid:
            passing_strategy_count += 1
            continue
        strategy_blockers.extend(str(item) for item in gate_blockers if str(item))
        if not boundaries_valid:
            strategy_blockers.append("strategy_order_generation_boundary_invalid")
    if not strategy_states:
        strategy_blockers.append("strategy_promotion_state_missing")
    if passing_strategy_count == 0:
        strategy_blockers.append("strategy_paper_shadow_promotion_not_ready")

    closure_blockers = [
        str(item) for item in execution_closure.get("blockers") or [] if str(item)
    ]
    if not verify_daily_candidate_execution_closure(execution_closure):
        closure_blockers.append("execution_closure_contract_invalid")
    if execution_closure.get("status") not in {"pass", "not_required"}:
        closure_blockers.append("prior_execution_not_reconciled")

    gates = [
        build_preflight_gate("automation_policy", policy_blockers),
        build_preflight_gate("account_truth", account_truth_blockers),
        build_preflight_gate("reviewed_fees", fee_blockers),
        build_preflight_gate("strategy", strategy_blockers),
        build_preflight_gate("execution_closure", closure_blockers),
    ]
    blockers = list(
        dict.fromkeys(
            str(blocker)
            for gate in gates
            for blocker in gate.get("blockers") or []
            if str(blocker)
        )
    )
    actions = {
        "automation_policy": "restore_paper_shadow_only_automation_policy",
        "account_truth": "complete_current_account_truth_evidence_review",
        "reviewed_fees": "review_account_specific_fee_schedule",
        "strategy": "promote_evidence_bound_strategy_for_paper_shadow",
        "execution_closure": "complete_plan_paper_actual_reconciliation",
    }
    first_blocked_gate = next(
        (gate for gate in gates if gate.get("status") != "pass"),
        None,
    )
    first_blocking_gate = (
        str(first_blocked_gate.get("gate") or "") or None
        if first_blocked_gate
        else None
    )
    status = "blocked" if blockers else "ready_for_window_time_evidence"
    core = {
        "schema_version": DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION,
        "status": status,
        "run_date": run_date,
        "gates": gates,
        "blockers": blockers[:100],
        "blocker_count": len(blockers),
        "blockers_truncated": len(blockers) > 100,
        "first_blocking_gate": first_blocking_gate,
        "first_safe_action": (
            actions.get(first_blocking_gate)
            if first_blocking_gate
            else "persist_current_market_quotes_and_build_reviewed_window_plan"
        ),
        "strategy_state_count": len(strategy_states),
        "passing_strategy_count": passing_strategy_count,
        "reviewed_fee_schedule_fingerprint": (
            fee_review_fingerprint if is_sha256(fee_review_fingerprint) else None
        ),
        "execution_closure_fingerprint": execution_closure.get("evidence_fingerprint"),
        "deferred_window_time_gates": [
            "market_data",
            "decision_plan",
            "runtime_window",
        ],
        "permits_risk_or_paper_shadow": False,
        "changes_attempt_eligibility": False,
        "permits_retry_or_backfill": False,
        "qualifies_forward_trial": False,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "profitability_claim": "not_established",
    }
    return {**core, "preparation_fingerprint": fingerprint_json(core)}


def verify_daily_candidate_preparation_check(
    value: Any,
    *,
    run_date: str,
) -> bool:
    """Verify the privacy-minimized preparation contract deterministically."""

    if not isinstance(value, dict):
        return False
    core = dict(value)
    fingerprint = str(core.pop("preparation_fingerprint", "") or "")
    gates = core.get("gates")
    blockers = core.get("blockers")
    expected_boundaries = {
        "permits_risk_or_paper_shadow": False,
        "changes_attempt_eligibility": False,
        "permits_retry_or_backfill": False,
        "qualifies_forward_trial": False,
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "manual_confirmation_required": True,
        "does_not_create_oms_order": True,
        "does_not_mutate_production_ledger": True,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }
    if (
        core.get("schema_version") != DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION
        or core.get("status") not in {"blocked", "ready_for_window_time_evidence"}
        or core.get("run_date") != run_date
        or not is_sha256(fingerprint)
        or fingerprint != fingerprint_json(core)
        or not isinstance(gates, list)
        or not isinstance(blockers, list)
        or core.get("profitability_claim") != "not_established"
        or any(
            core.get(field) is not expected
            for field, expected in expected_boundaries.items()
        )
    ):
        return False
    gate_names = [str(object_dict(gate).get("gate") or "") for gate in gates]
    if gate_names != [
        "automation_policy",
        "account_truth",
        "reviewed_fees",
        "strategy",
        "execution_closure",
    ]:
        return False
    blocked_gates = [
        gate
        for gate in gates
        if object_dict(gate).get("status") != "pass"
        or object_dict(gate).get("blockers")
    ]
    first_blocking_gate = (
        str(object_dict(blocked_gates[0]).get("gate") or "") or None
        if blocked_gates
        else None
    )
    blocker_count = count(core.get("blocker_count"))
    if (
        core.get("first_blocking_gate") != first_blocking_gate
        or (core.get("status") == "blocked") != bool(blocked_gates)
        or len(blockers) != min(blocker_count, 100)
        or core.get("blockers_truncated") is not (blocker_count > 100)
    ):
        return False
    return True
