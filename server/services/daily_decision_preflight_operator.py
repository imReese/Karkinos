"""Operator-facing, non-authorizing daily preflight contracts."""

from __future__ import annotations

from typing import Any

from server.services.daily_decision_evidence_values import object_dict


def build_preflight_operator_checklist(
    *,
    gates: list[dict[str, Any]],
    runtime_blockers: list[str],
    schedule_status: str,
    manual_window_open: bool,
    next_safe_action: str,
) -> list[dict[str, Any]]:
    """Order blocked evidence work without performing or authorizing it."""

    action_specs = (
        (
            "automation_policy",
            "restore_paper_shadow_only_automation_policy",
            "human_review",
        ),
        (
            "account_truth",
            "complete_current_account_truth_evidence_review",
            "human_review",
        ),
        (
            "reviewed_fees",
            "review_account_specific_fee_schedule",
            "human_review",
        ),
        (
            "strategy",
            "promote_evidence_bound_strategy_for_paper_shadow",
            "human_review",
        ),
        (
            "execution_closure",
            "complete_plan_paper_actual_reconciliation",
            "human_review",
        ),
        (
            "market_data",
            "persist_current_market_quotes_for_reviewed_window",
            "persisted_evidence_refresh",
        ),
        (
            "decision_plan",
            "rebuild_decision_and_plan_in_reviewed_window",
            "canonical_runtime",
        ),
    )
    blockers_by_gate = {
        str(gate.get("gate") or ""): [
            str(blocker) for blocker in gate.get("blockers") or [] if str(blocker)
        ]
        for gate in gates
    }
    checklist: list[dict[str, Any]] = []
    for gate, action, completion_mode in action_specs:
        blockers = blockers_by_gate.get(gate, [])
        if not blockers:
            continue
        checklist.append(
            build_preflight_operator_step(
                step=len(checklist) + 1,
                gate=gate,
                action=action,
                blockers=blockers,
                completion_mode=completion_mode,
            )
        )

    schedule_reason = None
    schedule_action = "restore_daily_candidate_runtime_before_reviewed_window"
    if not manual_window_open:
        schedule_reason, schedule_action = {
            "waiting_for_decision_window": (
                "daily_candidate_decision_window_not_open",
                "keep_monitor_running_and_wait_for_reviewed_window",
            ),
            "missed_decision_window": (
                "daily_candidate_background_window_missed",
                "prepare_current_evidence_for_next_reviewed_window",
            ),
            "not_trading_day": (
                "market_calendar_not_trading_day",
                "wait_for_next_verified_trading_day",
            ),
            "already_attempted": (
                "daily_candidate_attempt_already_recorded",
                "review_persisted_daily_result",
            ),
            "already_recorded": (
                "daily_candidate_run_already_recorded",
                "review_persisted_daily_result",
            ),
        }.get(
            schedule_status,
            (
                "daily_candidate_decision_window_unavailable",
                "restore_daily_candidate_runtime_before_reviewed_window",
            ),
        )
    runtime_reasons = list(dict.fromkeys([*runtime_blockers, schedule_reason]))
    runtime_reasons = [reason for reason in runtime_reasons if reason]
    if runtime_reasons:
        checklist.append(
            build_preflight_operator_step(
                step=len(checklist) + 1,
                gate="runtime_window",
                action=schedule_action,
                blockers=runtime_reasons,
                completion_mode="canonical_runtime",
            )
        )

    if not checklist:
        checklist.append(
            build_preflight_operator_step(
                step=1,
                gate="ready",
                action=next_safe_action,
                blockers=[],
                completion_mode="canonical_runtime",
            )
        )
    return checklist


def build_preflight_operator_step(
    *,
    step: int,
    gate: str,
    action: str,
    blockers: list[str],
    completion_mode: str,
) -> dict[str, Any]:
    evidence_contract = build_preflight_operator_evidence_contract(gate)
    return {
        "step": step,
        "gate": gate,
        "action": action,
        "completion_mode": completion_mode,
        "blockers": list(dict.fromkeys(blockers)),
        **evidence_contract,
        "automatic_action_performed": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
    }


def build_preflight_operator_evidence_contract(gate: str) -> dict[str, Any]:
    """Describe exact, privacy-minimized evidence without accepting it."""

    contracts = {
        "automation_policy": {
            "required_evidence": [
                "persisted_paper_shadow_only_automation_policy",
                "manual_confirmation_and_kill_switch_controls",
            ],
            "completion_criteria": [
                "broker_submission_remains_disabled",
                "manual_confirmation_remains_required",
                "allowed_modes_exclude_live_like_execution",
            ],
        },
        "account_truth": {
            "required_evidence": [
                "current_cash_snapshot_with_aware_timestamp_and_cash_balance",
                "current_position_snapshots_with_symbol_asset_currency_quantity_and_cost_basis",
                "itemized_trade_rows_with_quantity_price_gross_fee_tax_transfer_fee_and_net_amount",
                "reviewed_source_hash_window_scope_and_completeness_attestations",
                "current_ledger_cutoff_and_reconciliation_evidence",
            ],
            "completion_criteria": [
                "cash_and_position_snapshots_share_current_shanghai_date",
                "snapshots_are_no_more_than_86400_seconds_old_and_not_before_latest_event",
                "account_truth_covers_latest_ledger_cutoff",
                "cash_position_fee_and_cost_basis_pass_with_zero_unresolved_mismatches",
                "private_xls_content_and_account_identifiers_remain_unstored",
            ],
        },
        "reviewed_fees": {
            "required_evidence": [
                "account_specific_commission_minimum_stamp_tax_transfer_fee_and_other_fee_terms",
                "historical_buy_and_sell_itemized_fee_components",
                "human_accepted_fee_effective_date_window",
            ],
            "completion_criteria": [
                "historical_buy_and_sell_fee_component_reconciliation_passes",
                "action_date_is_inside_accepted_fee_window",
                "fee_review_matches_current_account_truth_and_strategy_bindings",
                "fee_review_is_bounded_and_revocable",
            ],
        },
        "strategy": {
            "required_evidence": [
                "five_sequential_research_iterations",
                "deterministic_local_backtest_and_promotion_evidence",
                "content_addressed_daily_strategy_backup",
                "bounded_revocable_human_promotion_review",
            ],
            "completion_criteria": [
                "each_iteration_binds_previous_formula_metrics_blockers_and_critique",
                "research_policy_authorizes_exactly_five_iterations_and_ten_provider_calls",
                "winner_passes_every_deterministic_gate_or_incumbent_remains_unchanged",
                "promoted_strategy_replays_from_frozen_data_and_current_fee_review",
                "live_like_execution_remains_disabled",
            ],
        },
        "execution_closure": {
            "required_evidence": [
                "persisted_plan_paper_and_actual_execution_records",
                "per_order_terminal_and_ledger_reconciliation",
            ],
            "completion_criteria": [
                "every_prior_required_order_is_reconciled_or_explicitly_not_required",
                "unresolved_or_drifted_execution_evidence_count_is_zero",
            ],
        },
        "market_data": {
            "required_evidence": [
                "persisted_trusted_quote_with_source_price_and_aware_timestamp",
            ],
            "completion_criteria": [
                "quote_is_bound_to_plan_date_and_not_after_decision_time",
                "quote_age_at_decision_is_no_more_than_300_seconds",
            ],
        },
        "decision_plan": {
            "required_evidence": [
                "persisted_same_day_decision_and_trading_plan",
                "matching_account_market_strategy_fee_and_closure_bindings",
            ],
            "completion_criteria": [
                "decision_and_plan_are_rebuilt_inside_reviewed_window",
                "decision_plan_bindings_replay_without_drift",
            ],
        },
        "runtime_window": {
            "required_evidence": [
                "loaded_local_daily_candidate_service_and_live_monitor_task",
                "reviewed_exchange_calendar_and_current_decision_window",
            ],
            "completion_criteria": [
                "launch_agent_and_process_liveness_are_both_confirmed",
                "exactly_one_fail_closed_attempt_is_due_in_reviewed_window",
                "runtime_liveness_does_not_claim_financial_readiness",
            ],
        },
        "source_evidence": {
            "required_evidence": [
                "readable_persisted_decision_plan_fee_closure_and_runtime_sources",
            ],
            "completion_criteria": [
                "all_preflight_sources_are_readable_and_contract_valid",
                "source_restoration_does_not_mutate_financial_state",
            ],
        },
        "ready": {
            "required_evidence": ["persisted_current_preflight_facts"],
            "completion_criteria": [
                "start_only_one_canonical_risk_and_paper_shadow_attempt",
                "separate_post_shadow_gate_and_human_confirmation_remain_required",
            ],
        },
    }
    contract = contracts.get(
        gate,
        {
            "required_evidence": ["canonical_persisted_gate_evidence"],
            "completion_criteria": ["named_gate_blockers_are_resolved"],
        },
    )
    return {
        "evidence_contract_version": "karkinos.daily_candidate_operator_evidence.v1",
        "required_evidence": list(contract["required_evidence"]),
        "completion_criteria": list(contract["completion_criteria"]),
        "accepted_evidence_authority": "canonical_persisted_evidence_only",
        "owner_attestation_is_financial_fact": False,
        "private_xls_rows_required": False,
        "private_account_identifiers_required": False,
    }


def build_preflight_gate(name: str, blockers: list[str]) -> dict[str, Any]:
    normalized = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    return {
        "gate": name,
        "status": "blocked" if normalized else "pass",
        "blockers": normalized,
    }


def safe_preflight_blocker(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if not normalized:
        return ""
    if len(normalized) > 120 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_:-."
        for character in normalized
    ):
        return "unclassified_blocker"
    return normalized
