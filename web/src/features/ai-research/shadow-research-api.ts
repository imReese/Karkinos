import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson, putJson } from '../../shared/api/client';

export type ShadowResearchMetricView = {
  result_id: number;
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  total_cost: number;
  total_commission: number;
  total_slippage: number;
  total_trades: number;
  gross_turnover: number;
  oos_fold_count: number;
  mean_oos_return: number;
  worst_oos_return: number;
  oos_validation_status: string;
  evidence_gate_status: string;
  dataset_snapshot_id: string | null;
};

export type ShadowResearchCandidate = {
  candidate_id: string;
  run_id: string;
  session_id: string;
  draft_id: string;
  backtest_run_id: string | null;
  critique_id: string | null;
  baseline_result_id: number;
  candidate_result_id: number | null;
  status: 'awaiting_human_approval' | 'research_blocked' | 'failed_closed';
  recommendation: 'paper_shadow_review' | 'keep_researching' | 'reject';
  promotion_status:
    | 'awaiting_human_approval'
    | 'blocked_by_evidence'
    | 'paper_shadow_approval_recorded'
    | 'paper_shadow_approved';
  created_at: string;
  updated_at: string;
  comparison: {
    economic_hypothesis?: string;
    risk_impact?: string;
    failure_conditions?: string[];
    limitations?: string[];
    baseline?: ShadowResearchMetricView;
    candidate?: ShadowResearchMetricView;
    deltas?: Record<string, number>;
    deepseek_critique?: {
      supported_claims?: string[];
      contradicted_claims?: string[];
      evidence_gaps?: string[];
      uncertainty?: string;
    };
    iteration_lineage?: {
      iteration_number: number;
      total_iterations: number;
      formula_fingerprint: string;
      parent_candidate_id: string | null;
      parent_draft_id: string | null;
      parent_formula_fingerprint: string | null;
      iteration_context_fingerprint: string;
      sequential_feedback_bound: boolean;
    };
    recommendation?: string;
    promotion_gate: { status: string; blockers: string[] };
  };
  automatic_strategy_replacement_enabled: false;
  production_strategy_mutation_enabled: false;
  broker_submission_enabled: false;
  human_paper_shadow_approval_required: true;
};

export type StrategyPromotionState = {
  strategy_id: string;
  stage: string;
  gate_status: string;
  live_like_enabled: boolean;
};

export type ShadowResearchDailySelection = {
  schema_version: 'karkinos.ai.daily_strategy_selection.v1';
  selection_id: string;
  run_id: string;
  market_date: string;
  status: 'winner_selected' | 'no_selection';
  winner_candidate_id: string | null;
  expected_candidate_count: number;
  observed_candidate_count: number;
  eligible_candidate_count: number;
  blockers: string[];
  selection_scope: 'new_candidate_research_only';
  incumbent_strategy_policy: 'leave_current_human_approved_strategy_unchanged';
  incumbent_strategy_state_changed: false;
  daily_trading_decision_status: 'not_evaluated';
  implies_daily_trading_no_action: false;
  integrity_status: 'verified' | 'fingerprint_mismatch';
};

export type ShadowResearchDailyBackup = {
  schema_version: 'karkinos.ai.daily_strategy_backup_receipt.v1';
  backup_id: string;
  run_id: string;
  market_date: string;
  relative_path: string;
  artifact_fingerprint: string;
  byte_count: number;
  verification_status: string;
  contains_private_account_identifiers: false;
  contains_broker_export_rows: false;
};

export type ShadowResearchAutomationStatus = {
  schema_version: string;
  runtime_contract?: string;
  policy: {
    schema_version: 'karkinos.ai.shadow_research_policy.v3';
    policy_id: 'ai_shadow_research';
    enabled: boolean;
    after_close_time: string;
    timezone: 'Asia/Shanghai';
    provider_call_window_schema: 'karkinos.ai.provider_call_window.v1';
    provider_call_window_policy_id: string;
    provider_call_window_policy_fingerprint: string;
    max_provider_calls_per_market_date: number;
    daily_token_budget: number | null;
    token_budget_mode: 'unbounded_daily' | 'legacy_bounded_daily';
    max_candidates_per_run: number;
    baseline_backtest_result_id: number | null;
    require_complete_account_evidence: boolean;
    research_question: string;
    updated_by: string;
    authorization_recorded: boolean;
    automatic_strategy_replacement_enabled: false;
    broker_submission_enabled: false;
    production_strategy_mutation_enabled: false;
    human_paper_shadow_approval_required: true;
  };
  kill_switch: { enabled: boolean; reason: string };
  usage: {
    market_date: string | null;
    provider_calls: number;
    reserved_tokens: number;
    actual_tokens: number;
  };
  runs: Array<{
    run_id: string;
    market_date: string;
    status: string;
    candidate_count: number;
    failure_code: string | null;
  }>;
  candidates: ShadowResearchCandidate[];
  daily_selections: ShadowResearchDailySelection[];
  daily_backups: ShadowResearchDailyBackup[];
  daily_new_candidate_winner_id: string | null;
  /** Compatibility alias; this is a research winner, not a trading decision. */
  daily_winner_candidate_id: string | null;
  research_outcome: {
    status:
      | 'new_candidate_available_for_human_review'
      | 'no_new_candidate_current_strategy_unchanged';
    new_candidate_winner_id: string | null;
    incumbent_strategy_policy: 'leave_current_human_approved_strategy_unchanged';
    incumbent_strategy_state_changed: false;
    daily_trading_decision_status: 'not_evaluated';
    implies_daily_trading_no_action: false;
  };
  provider_call_window?: {
    schema_version: 'karkinos.ai.provider_call_window.v1';
    policy_id: string;
    policy_fingerprint: string;
    provider_id: string;
    timezone: 'Asia/Shanghai';
    status: 'eligible_off_peak' | 'deferred_for_provider_off_peak';
    pricing_period: 'peak' | 'off_peak';
    failure_code: string | null;
    evaluated_at: string;
    next_eligible_at: string | null;
    minimum_runway_seconds: number;
    provider_call_performed: false;
    authority_effect: 'none';
  };
  automatic_strategy_replacement_enabled: false;
  production_strategy_mutation_enabled: false;
  broker_submission_enabled: false;
  human_paper_shadow_approval_required: true;
  authority_effect: 'research_only';
};

export type ShadowResearchPolicyInput = {
  enabled: boolean;
  after_close_time: string;
  max_provider_calls_per_market_date: number;
  daily_token_budget: null;
  token_budget_mode: 'unbounded_daily';
  max_candidates_per_run: number;
  baseline_backtest_result_id: number | null;
  require_complete_account_evidence: boolean;
  research_question: string;
  updated_by: string;
};

export function useShadowResearchAutomationQuery() {
  return useQuery({
    queryKey: ['ai-shadow-research-automation'],
    queryFn: () =>
      apiClient<ShadowResearchAutomationStatus>(
        '/api/ai/strategy-research/shadow-automation',
      ),
    refetchOnWindowFocus: false,
    refetchInterval: 60_000,
    staleTime: 10_000,
  });
}

export function useStrategyPromotionStatesQuery() {
  return useQuery({
    queryKey: ['strategy-promotion-states'],
    queryFn: () =>
      apiClient<StrategyPromotionState[]>('/api/strategy-promotion/states'),
    refetchOnWindowFocus: false,
    staleTime: 10_000,
  });
}

export function useUpdateShadowResearchPolicyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ShadowResearchPolicyInput) =>
      putJson<ShadowResearchAutomationStatus['policy']>(
        '/api/ai/strategy-research/shadow-automation/policy',
        {
          ...input,
          confirmation: input.enabled
            ? 'authorize_five_sequential_after_close_deepseek_strategy_research_without_daily_token_budget_or_strategy_or_trade_authority'
            : 'pause_after_close_ai_strategy_research_without_changing_trading_authority',
        },
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['ai-shadow-research-automation'],
      }),
  });
}

export function useRunShadowResearchMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postJson<ShadowResearchAutomationStatus>(
        '/api/ai/strategy-research/shadow-automation/run',
        {},
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['ai-shadow-research-automation'],
      }),
  });
}

export function useApproveShadowResearchCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      candidate_id: string;
      approved_by: string;
      notes: string;
    }) =>
      postJson<Record<string, unknown>>(
        `/api/ai/strategy-research/shadow-candidates/${encodeURIComponent(input.candidate_id)}/paper-shadow-approvals`,
        {
          approved_by: input.approved_by,
          notes: input.notes,
          confirmation:
            'approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority',
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['ai-shadow-research-automation'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['strategy-promotion-states'],
        }),
      ]);
    },
  });
}

export function usePauseShadowResearchCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      candidate_id: string;
      actor: string;
      reason: string;
    }) =>
      postJson<StrategyPromotionState>(
        `/api/strategy-promotion/${encodeURIComponent(`ai_formula_shadow:${input.candidate_id}`)}/lifecycle`,
        {
          target_stage: 'paused',
          reason: input.reason,
          actor: input.actor,
          confirmation:
            'pause_or_retire_strategy_without_execution_or_capital_authority',
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['ai-shadow-research-automation'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['strategy-promotion-states'],
        }),
      ]);
    },
  });
}
