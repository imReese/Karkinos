export type AccountRecommendationAction = {
  action_id: string | number | null;
  symbol: string | null;
  symbol_name?: string | null;
  display_name?: string | null;
  name?: string | null;
  asset_class?: string | null;
  side: string | null;
  target_weight?: number | null;
  target_allocation?: number | null;
  target_quantity?: number | null;
  target_amount?: number | null;
  target_price?: number | null;
  estimated_quantity?: number | null;
  estimated_price?: number | null;
  estimated_execution_price?: number | null;
  limit_price?: number | null;
  current_quantity?: number | null;
  post_trade_quantity?: number | null;
  estimated_net_amount?: number | null;
  estimated_commission?: number | null;
  estimated_stamp_duty?: number | null;
  estimated_total_cost?: number | null;
  estimated_gross_amount?: number | null;
  estimated_net_cash_impact?: number | null;
  estimated_total_fee?: number | null;
  submission_status?: string | null;
  reason?: string | null;
  strategy_id?: string | null;
  frozen_market_date?: string | null;
};

export type AccountRecommendationStrategyContext = {
  strategy_id: string;
  strategy_stage?: string | null;
  strategy_artifact_fingerprint: string;
  saved_backtest_id: number | null;
  entry_conditions: string | null;
  exit_conditions: string | null;
  condition_basis: 'frozen_strategy_text' | 'formula_ast_summary';
  economic_hypothesis: string | null;
  risk_impact: string | null;
  failure_conditions: string[];
  forward: {
    status: 'not_started' | 'recorded' | 'unavailable';
    observation_count?: number;
    lifecycles?: string[];
    publication_count?: number;
    outcome_count?: number;
    qualification_assessed: false;
  };
  historical_comparison: {
    status: 'recorded_pair';
    dataset_id: string;
    start_date: string;
    end_date: string;
    instrument_count: number;
    bar_row_count: number;
    corporate_action_mode: string | null;
    point_in_time_verified: boolean | null;
    baseline: {
      result_id: number;
      total_return: number | null;
      annual_return: number | null;
      sharpe: number | null;
      max_drawdown: number | null;
    };
    candidate: {
      result_id: number;
      total_return: number | null;
      annual_return: number | null;
      sharpe: number | null;
      max_drawdown: number | null;
    };
    independent_final_evaluation: false;
    authority_effect: 'none';
  } | null;
  read_only: true;
  authorizes_execution: false;
};

export type HistoricalResearchComparison = NonNullable<
  AccountRecommendationStrategyContext['historical_comparison']
> & {
  source_result_id: number;
  anchor_result_id: number;
  forward: {
    baseline: AccountRecommendationStrategyContext['forward'] & {
      source_backtest_result_id: number;
    };
    candidate: AccountRecommendationStrategyContext['forward'] & {
      source_backtest_result_id: number;
    };
  };
  read_only: true;
  authorizes_execution: false;
};

export type AccountActionRecommendation = {
  schema_version: 'karkinos.decision.account_action_recommendation.v1';
  decision_date: string | null;
  status:
    | 'manual_review_required'
    | 'paper_shadow_required'
    | 'no_action'
    | 'blocked'
    | 'unavailable';
  reason_codes: string[];
  source_action_task_ids: string[];
  actions: AccountRecommendationAction[];
  strategy_context?: Record<string, AccountRecommendationStrategyContext>;
  presentation?: {
    level:
      | 'manual_review'
      | 'portfolio_preview'
      | 'signal'
      | 'no_action'
      | 'blocked'
      | 'unavailable';
    actions: AccountRecommendationAction[];
    signal_status?: 'ready' | 'no_signal' | 'account_blocked' | 'unavailable';
    portfolio_preview_status?: 'ready' | 'blocked';
    manual_review_status?: 'ready' | 'blocked';
    configuration_blockers?: string[];
    signal_blockers?: string[];
    portfolio_preview_blockers?: string[];
    manual_review_blockers?: string[];
    blockers?: string[];
    warnings?: string[];
    read_only?: true;
    authorizes_execution?: false;
  };
  promoted_scan: {
    run_id: string | null;
    status: string;
    input_fingerprint: string | null;
    output_fingerprint: string | null;
    selected_signal_count: number;
    raw_signal_count?: number;
    account_blocked_buys?: Array<{
      strategy_id: string;
      symbol: string;
      board: string;
      reason: string;
    }>;
  };
  account_evidence: {
    valuation_snapshot_id: string | null;
    ledger_cutoff_id: number | null;
    quote_set_fingerprint: string | null;
    valuation_status: string;
    account_truth_status: string;
    account_qualification_status: 'passed' | 'blocked';
    account_positions_evaluated: boolean;
  };
  read_only?: true;
  manual_confirmation_required?: true;
  creates_oms_order?: false;
  submits_broker_order?: false;
  authorizes_execution?: false;
  changes_capital_authority?: false;
  authority_effect?: 'none';
  evidence_fingerprint?: string;
  execution_blocked?: boolean;
  blockers?: string[];
  limitations?: string[];
};
