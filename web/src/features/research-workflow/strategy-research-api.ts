/** Evidence-bound strategy research data access shared by research surfaces. */
import { useMutation } from '@tanstack/react-query';

import { postJson } from '../../shared/api/client';

export const CANONICAL_COST_MODEL_REFERENCE =
  'karkinos.backtest.multi_asset_commission.default.v1';
export const NORMALIZED_RESEARCH_NOTIONAL = 1_000_000;

export type StrategyFormulaAst = {
  schema_version: 'karkinos.ai.formula_ast.v1';
  entry: Record<string, unknown>;
  exit: Record<string, unknown>;
  position_size: Record<string, unknown>;
};

export type StrategyHypothesisDraft = {
  schema_version: 'karkinos.ai.strategy_hypothesis_draft.v1';
  draft_id: string;
  workflow_id: string;
  session_id: string;
  context_snapshot_id: string;
  context_fingerprint: string;
  evidence_reference_id: string;
  provider_id: string;
  model_id: string;
  prompt_version: string;
  provider_provenance?: Record<string, unknown>;
  research_question: string;
  economic_hypothesis: string;
  selected_universe: string[];
  universe_fingerprint: string;
  dataset_snapshot_id: string;
  test_window: { start_date: string; end_date: string };
  frequency: string;
  formula_ast: StrategyFormulaAst;
  formula_fingerprint: string | null;
  parameter_values: Record<string, unknown>;
  parameter_ranges: Record<string, unknown>;
  entry_conditions: string;
  exit_conditions: string;
  position_sizing_hypothesis: string;
  portfolio_constraints: Record<string, unknown>;
  cost_model_reference: string;
  required_evidence: string[];
  anti_lookahead_assumptions: string[];
  proposed_deterministic_tests: string[];
  sample_split_plan: string;
  failure_conditions: string[];
  limitations: string[];
  risk_impact: string;
  citations: string[];
  validation: { status: 'valid' | 'blocked'; errors: string[] };
  executable: false;
  requires_human_review: true;
  decision_input_created: false;
  trade_plan_created: false;
  authority_effect: 'none';
};

export type StrategyResearchSession = {
  schema_version: string;
  session_id: string;
  status:
    'pending' | 'running' | 'partial' | 'failed' | 'blocked' | 'completed';
  failure_code: string | null;
  research_question: string;
  selection: {
    saved_backtest_result_id: number;
    universe: string[];
    asset_classes: string[];
    dataset_snapshot_id: string;
    start_date: string;
    end_date: string;
    frequency: string;
    initial_cash: number;
    cost_model_reference: string;
    account_fact_binding: string;
  };
  selection_fingerprint: string;
  context_snapshot_id: string | null;
  context_fingerprint: string | null;
  evidence_reference_id: string | null;
  provider_id: string | null;
  model_id: string | null;
  prompt_version: string;
  binding_validity: 'not_established' | 'valid' | 'invalidated_by_drift';
  binding_errors: string[];
  drafts: StrategyHypothesisDraft[];
  reviews: Array<Record<string, unknown>>;
  reused: boolean;
  non_authoritative: true;
  non_executable: true;
  requires_human_review: true;
  trade_plan_created: false;
  authority_effect: 'none';
};

export type StrategyFormulaBacktest = {
  schema_version: string;
  backtest_run_id: string;
  status: 'running' | 'failed' | 'completed';
  failure_code: string | null;
  session_id: string;
  draft_id: string;
  formula_fingerprint: string;
  dataset_snapshot_id: string;
  cost_model_reference: string;
  canonical_backtest: null | {
    result_id: number;
    initial_cash: number;
    final_equity: number;
    total_return: number;
    sharpe: number;
    max_drawdown: number;
    duration_days: number;
    cost_summary: {
      total_commission?: number;
      total_slippage?: number;
      total_trades?: number;
      gross_turnover?: number;
    };
    oos_validation: Record<string, unknown>;
    research_evidence_bundle: Record<string, unknown>;
    dataset_snapshot: Record<string, unknown>;
    formula_binding: Record<string, unknown>;
  };
  reused: boolean;
  research_only: true;
  non_authoritative: true;
  non_executable: true;
  requires_human_review: true;
  authority_effect: 'none';
};

export type StrategyBacktestCritique = {
  schema_version: string;
  critique_id: string;
  session_id: string;
  draft_id: string;
  backtest_run_id: string;
  status:
    'pending' | 'running' | 'partial' | 'failed' | 'blocked' | 'completed';
  failure_code: string | null;
  provider_id: string | null;
  model_id: string | null;
  prompt_version: string;
  artifact: null | {
    schema_version: string;
    supported_claims: string[];
    contradicted_claims: string[];
    evidence_gaps: string[];
    cost_turnover_sensitivity: string;
    concentration_risk: string;
    sample_dependence: string;
    possible_overfitting: string;
    recommended_ablations: string[];
    recommended_walk_forward_stress_tests: string[];
    explicit_failure_conditions: string[];
    uncertainty: string;
    citations: string[];
    provider_provenance?: Record<string, unknown>;
    trade_plan_created: false;
    authority_effect: 'none';
  };
  reused: boolean;
  non_authoritative: true;
  non_executable: true;
  requires_human_review: true;
  trade_plan_created: false;
  authority_effect: 'none';
};

export type GenerateStrategyHypothesesInput = {
  idempotency_key: string;
  requested_by: string;
  account_alias: string;
  research_question: string;
  selection: {
    saved_backtest_result_id: number;
    universe: string[];
    asset_classes: string[];
    dataset_snapshot_id: string;
    start_date: string;
    end_date: string;
    frequency: '1d';
    initial_cash: number;
    cost_model_reference: string;
    valuation_snapshot_id: string | null;
    ledger_cutoff_id: number | null;
  };
};

export function useGenerateStrategyHypothesesMutation() {
  return useMutation({
    mutationFn: (input: GenerateStrategyHypothesesInput) =>
      postJson<StrategyResearchSession>(
        '/api/ai/strategy-research/hypotheses',
        {
          ...input,
          confirmation:
            'send_selected_sanitized_strategy_research_evidence_to_configured_external_model_without_trade_authority',
        },
      ),
  });
}

export function useRunStrategyFormulaBacktestMutation() {
  return useMutation({
    mutationFn: (input: {
      idempotency_key: string;
      requested_by: string;
      session_id: string;
      draft_id: string;
    }) =>
      postJson<StrategyFormulaBacktest>('/api/ai/strategy-research/backtests', {
        ...input,
        confirmation:
          'run_selected_validated_formula_with_canonical_backtest_without_trade_authority',
      }),
  });
}

export function useCritiqueStrategyBacktestMutation() {
  return useMutation({
    mutationFn: (input: {
      idempotency_key: string;
      requested_by: string;
      session_id: string;
      draft_id: string;
      backtest_run_id: string;
    }) =>
      postJson<StrategyBacktestCritique>(
        '/api/ai/strategy-research/critiques',
        {
          ...input,
          confirmation:
            'send_selected_formula_and_canonical_backtest_evidence_to_configured_external_model_without_trade_authority',
        },
      ),
  });
}

export function useReviewStrategyResearchMutation() {
  return useMutation({
    mutationFn: (input: {
      idempotency_key: string;
      session_id: string;
      critique_id: string;
      reviewer: string;
      disposition: 'accepted_for_more_research' | 'rejected' | 'needs_revision';
      notes: string;
    }) =>
      postJson<Record<string, unknown>>(
        `/api/ai/strategy-research/sessions/${encodeURIComponent(input.session_id)}/reviews`,
        {
          idempotency_key: input.idempotency_key,
          reviewer: input.reviewer,
          disposition: input.disposition,
          notes: input.notes,
          confirmation:
            'record_human_strategy_research_review_without_trade_authority',
        },
      ),
  });
}
