import { useMutation, useQueryClient } from '@tanstack/react-query';

import { postJson } from '../../../shared/api/client';

export type DailyCandidateTrialReview = {
  schema_version: 'karkinos.daily_candidate_trial_review.v2';
  review_id: string;
  trial_fingerprint: string;
  execution_evidence_fingerprint: string;
  decision: 'go_to_bounded_manual_trial' | 'continue_paper_shadow' | 'no_go';
  reviewed_by: string;
  note: string;
  status: 'recorded' | 'rejected';
  rejection_reasons: string[];
  recorded_at?: string | null;
  broker_submission_enabled: false;
  authorizes_execution: false;
  changes_capital_authority: false;
};

export type DailyCandidateExecutionEvidenceSummary = {
  schema_version: 'karkinos.daily_candidate_execution_evidence_summary.v1';
  status: 'blocked' | 'not_required' | 'pass';
  current_execution_closure_fingerprint: string | null;
  population_scope: 'all_current_non_paper_shadow_oms_orders';
  production_order_count: number;
  clear_order_count: number;
  reconciled_actual_order_count: number;
  reconciled_no_fill_order_count: number;
  comparison_coverage_complete: boolean;
  blockers: string[];
  actual_orders_attributed_to_trial: false;
  actual_orders_count_toward_simulated_trial_threshold: false;
  persisted_evidence_only: true;
  provider_contact_performed: false;
  manual_review_required: boolean;
  authorizes_execution: false;
  does_not_submit_broker_order: true;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  does_not_change_capital_authority: true;
  evidence_fingerprint: string;
};

export type DailyStrategyOperatingConstraints = {
  schema_version: 'karkinos.ai.strategy_operating_constraints.v1';
  candidate_id: string;
  strategy_artifact_fingerprint: string;
  source_backup_artifact_fingerprint: string;
  economic_hypothesis: string;
  risk_impact: string;
  failure_conditions: string[];
  limitations: string[];
  anti_lookahead_assumptions: string[];
  automatic_enforcement_enabled: false;
  human_review_required: true;
  authorizes_execution: false;
  changes_capital_authority: false;
  evidence_fingerprint: string;
};

export type DailyCandidateRunResult = {
  schema_version: 'karkinos.daily_decision_evidence_automation.v3';
  input_identity_schema_version: 'karkinos.daily_candidate_input_identity.v2';
  status: string;
  run_id: string;
  plan_date: string;
  input_fingerprint: string;
  production_record_fingerprint: string;
  decision_outcome: 'manual_order_ticket_candidate' | 'no_action';
  manual_ticket_candidate_count: number;
  manual_order_ticket_candidates: Array<{
    schema_version: 'karkinos.manual_order_ticket_candidate.v2';
    plan_date: string;
    intent_id: string | null;
    action_id: string | number | null;
    symbol: string;
    side: 'buy' | 'sell';
    asset_class: string;
    order_type: 'limit';
    quantity: number;
    limit_price: number;
    estimated_gross_amount: number;
    estimated_total_fee: number;
    estimated_net_cash_impact: number;
    fee_rule_id: string;
    market_quote: {
      price: number;
      timestamp: string;
      source: string;
      age_seconds_at_decision: number;
      max_age_seconds: number;
    };
    paper_shadow: {
      run_id: string;
      input_fingerprint: string;
      status: string;
      divergence_status: string;
    };
    strategy_gate_binding: {
      schema_version: 'karkinos.daily_candidate_strategy_gate_binding.v2';
      action_id: string | number;
      strategy_ref: string;
      strategy_advancement_ref: string;
      reviewed_fee_schedule_ref: string;
      comparison_fingerprint: string;
      human_approval_id: string;
      dataset_replay_fingerprint: string;
      baseline_snapshot_id: string;
      candidate_snapshot_id: string;
      daily_strategy_artifact_binding?: {
        schema_version: 'karkinos.ai.daily_strategy_promotion_binding.v2';
        run_id: string;
        market_date: string;
        winner_candidate_id: string;
        selection_id: string;
        selection_fingerprint: string;
        backup_id: string;
        backup_artifact_fingerprint: string;
        operating_constraints: DailyStrategyOperatingConstraints;
        contains_private_account_identifiers: false;
        contains_broker_export_rows: false;
        does_not_change_capital_authority: true;
        authority_effect: 'research_only';
      };
      strategy_operating_constraints: DailyStrategyOperatingConstraints;
      persisted_facts_only: true;
      provider_contact_performed: false;
      paper_shadow_evaluation_only: true;
      authorizes_execution: false;
      changes_capital_authority: false;
    };
    strategy_operating_constraints?: DailyStrategyOperatingConstraints;
    account_truth_binding: {
      schema_version: 'karkinos.daily_candidate_account_truth_binding.v2';
      account_truth_ref: string;
      source_fingerprint: string;
      captured_at: string;
      age_seconds_at_decision: number;
      max_age_seconds: number;
      valuation_snapshot_id: string;
      ledger_cutoff_id: number;
      reconciliation_status: string;
      ledger_coverage_status: 'covered';
      replay_evidence: {
        schema_version: 'karkinos.account_truth.replay_evidence.v1';
        status: 'pass';
        account_truth_ref: string;
        source_fingerprint: string;
        valuation_snapshot_id: string;
        ledger_cutoff_id: number;
        evidence_fingerprint: string;
        contains_broker_export_rows: false;
        contains_private_account_identifiers: false;
        persisted_facts_only: true;
        provider_contact_performed: false;
        authorizes_execution: false;
        changes_capital_authority: false;
        [key: string]: unknown;
      };
      persisted_facts_only: true;
      provider_contact_performed: false;
      authorizes_execution: false;
      changes_capital_authority: false;
    };
    prior_execution_closure_fingerprint: string;
    evidence_refs: string[];
    invalidation_conditions: string[];
    ticket_candidate_fingerprint: string;
    manual_confirmation_required: true;
    creates_oms_order: false;
    authorizes_execution: false;
    broker_submission_enabled: false;
    does_not_change_capital_authority: true;
  }>;
  no_action_reasons: string[];
  production_gate: {
    schema_version: 'karkinos.daily_candidate_production_gate.v1';
    status: 'pass' | 'blocked';
    blockers: string[];
    broker_submission_enabled: false;
    authorizes_execution: false;
    changes_capital_authority: false;
  };
  execution_closure: {
    schema_version: 'karkinos.daily_candidate_execution_closure.v1';
    status: 'pass' | 'not_required' | 'blocked';
    production_order_count: number;
    clear_order_count: number;
    blockers: string[];
    evidence_fingerprint: string;
    authorizes_execution: false;
    does_not_submit_broker_order: true;
    does_not_mutate_production_ledger: true;
    does_not_change_capital_authority: true;
  };
  profitability_claim: 'not_established_by_daily_run';
  manual_confirmation_required: true;
  broker_submission_enabled: false;
  does_not_submit_broker_order: true;
  does_not_mutate_production_ledger: true;
};

export type DailyCandidateTrial = {
  schema_version: 'karkinos.daily_candidate_trial.v2';
  status: string;
  trial_epoch_id: string | null;
  trial_epoch_start_date: string | null;
  target_qualifying_trading_days: number;
  target_simulated_orders: number;
  qualifying_trading_day_count: number;
  simulated_order_count: number;
  remaining_trading_days: number;
  remaining_simulated_orders: number;
  strategy_advancement_refs: string[];
  reviewed_fee_schedule_refs: string[];
  strategy_operating_constraint_refs: string[];
  superseded_qualifying_day_count: number;
  run_scan_truncated: boolean;
  latest_daily_run: {
    run_date: string;
    status: 'qualifying' | 'excluded';
    run_id: string | null;
    decision_outcome: 'manual_order_ticket_candidate' | 'no_action' | null;
    simulated_order_count: number;
    manual_order_ticket_candidates?: DailyCandidateRunResult['manual_order_ticket_candidates'];
    production_record_fingerprint?: string | null;
    blockers: string[];
  } | null;
  current_execution_evidence: DailyCandidateExecutionEvidenceSummary;
  blockers: string[];
  eligible_for_human_go_no_go_review: boolean;
  trial_fingerprint: string;
  latest_review: DailyCandidateTrialReview | null;
  background_schedule: {
    schema_version: 'karkinos.daily_candidate_background_schedule.v3';
    status: string;
    evaluated_at: string | null;
    timezone: 'Asia/Shanghai';
    run_date: string | null;
    decision_window_start: '09:35';
    decision_window_end: '09:45';
    preparation_window_start: '08:45';
    preparation_window_end: '09:35';
    due: boolean;
    existing_run_id: string | null;
    preparation_check_due: boolean;
    preparation_check_existing_run_id: string | null;
    blockers: string[];
    next_reviewed_window?: {
      schema_version: 'karkinos.daily_candidate_next_reviewed_window.v1';
      status: 'available' | 'unavailable';
      market_date: string | null;
      window_start: string | null;
      window_end: string | null;
      is_current_market_date: boolean;
      official_calendar_verified: boolean;
      blockers: string[];
      provider_contact_performed: false;
      database_writes_performed: false;
      permits_retry_or_backfill: false;
      changes_attempt_eligibility: false;
      broker_submission_enabled: false;
      authorizes_execution: false;
      changes_capital_authority: false;
    };
    background_attempt_writes_enabled: boolean;
    preparation_check_writes_enabled: boolean;
    background_writes_enabled: boolean;
    preparation_check_changes_attempt_eligibility: false;
    preparation_check_permits_retry_or_backfill: false;
    broker_submission_enabled: false;
    authorizes_execution: false;
    changes_capital_authority: false;
  };
  next_safe_action: string;
  profitability_claim: 'not_established';
  does_not_establish_future_profitability: true;
  manual_confirmation_required: true;
  broker_submission_enabled: false;
  automatic_order_submission_enabled: false;
  automatic_capital_scaling_enabled: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  limitations: string[];
};

export type DailyCandidateRuntimeStatus = {
  schema_version: 'karkinos.daily_candidate_runtime_status.v1';
  status:
    | 'monitor_disabled'
    | 'monitor_failed_closed'
    | 'monitor_running_schedule_blocked'
    | 'monitor_running_due'
    | 'monitor_running_waiting';
  background_monitor_configured: boolean;
  background_monitor_running: boolean;
  monitor_task_state: string;
  monitor_task_failure_type: string | null;
  run_date: string | null;
  schedule_status: string;
  background_attempt_due: boolean;
  background_attempt_writes_permitted: boolean;
  manual_run_window_open: boolean;
  operational_blockers: string[];
  next_safe_action: string;
  financial_readiness_claimed: false;
  provider_contact_performed: false;
  database_writes_performed: false;
  does_not_submit_broker_order: true;
  broker_submission_enabled: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  limitations: string[];
};

export type DailyCandidateFinancialPreflight = {
  schema_version: 'karkinos.daily_candidate_financial_preflight.v1';
  status:
    | 'ready_for_paper_shadow_attempt'
    | 'ready_for_manual_paper_shadow_attempt'
    | 'waiting_for_decision_window'
    | 'no_action_not_trading_day'
    | 'daily_attempt_closed'
    | 'no_action';
  run_date: string | null;
  financial_gate_status: 'pass' | 'blocked';
  operational_gate_status: 'pass' | 'blocked';
  eligible_candidate_count: number;
  eligible_to_start_manual_attempt: boolean;
  eligible_for_background_attempt: boolean;
  eligible_to_create_manual_ticket: false;
  gates: Array<{
    gate: string;
    status: 'pass' | 'blocked';
    blockers: string[];
  }>;
  financial_blockers: string[];
  operational_blockers: string[];
  no_action_reasons: string[];
  next_safe_action: string;
  operator_checklist: Array<{
    step: number;
    gate: string;
    action: string;
    completion_mode:
      'human_review' | 'persisted_evidence_refresh' | 'canonical_runtime';
    blockers: string[];
    evidence_contract_version: 'karkinos.daily_candidate_operator_evidence.v1';
    required_evidence: string[];
    completion_criteria: string[];
    accepted_evidence_authority: 'canonical_persisted_evidence_only';
    owner_attestation_is_financial_fact: false;
    private_xls_rows_required: false;
    private_account_identifiers_required: false;
    automatic_action_performed: false;
    authorizes_execution: false;
    changes_capital_authority: false;
  }>;
  preflight_fingerprint: string;
  financial_readiness_scope: 'risk_and_paper_shadow_attempt_only';
  risk_evaluation_performed: false;
  paper_shadow_run_performed: false;
  manual_ticket_created: false;
  persisted_facts_only: true;
  provider_contact_performed: false;
  database_writes_performed: false;
  manual_confirmation_required: true;
  does_not_submit_broker_order: true;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  broker_submission_enabled: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  profitability_claim: 'not_established';
  limitations: string[];
};

export function useDailyCandidateTrialReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      expected_trial_fingerprint: string;
      decision:
        'go_to_bounded_manual_trial' | 'continue_paper_shadow' | 'no_go';
      reviewed_by: string;
      note: string;
      confirmation: 'record_daily_candidate_trial_review_without_trade_or_capital_authority';
    }) =>
      postJson<DailyCandidateTrialReview>(
        '/api/automation/daily-candidate/trial/reviews',
        request,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}

export function useRunDailyCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postJson<DailyCandidateRunResult>(
        '/api/automation/run/daily-candidate',
        {},
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({ queryKey: ['decision', 'today'] }),
        queryClient.invalidateQueries({
          queryKey: ['decision', 'trading-plan'],
        }),
      ]);
    },
  });
}
