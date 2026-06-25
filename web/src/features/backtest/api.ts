import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

export type BacktestMetrics = {
  initial_cash: number;
  final_equity: number;
  total_return: number;
  annual_return: number;
  sharpe: number;
  sortino: number;
  max_drawdown: number;
  calmar?: number | string;
  volatility?: number;
  win_rate: number;
  duration_days: number;
  total_commission?: number;
  total_slippage?: number;
  total_trades?: number;
  gross_turnover?: number;
};

export type CostSummary = {
  total_commission?: number;
  total_slippage?: number;
  total_trades?: number;
  gross_turnover?: number;
};

export type DatasetQualityIssue = {
  code: string;
  message?: string;
  count?: number;
  symbol?: string;
};

export type DatasetQuality = {
  status: string;
  issues: DatasetQualityIssue[];
};

export type DatasetSnapshotSymbol = {
  symbol: string;
  asset_class?: string | null;
  frequency?: string | null;
  row_count: number;
  first_timestamp?: string | null;
  last_timestamp?: string | null;
  provider_name?: string | null;
  data_source?: string | null;
  adjustment_mode?: string | null;
  source_dataset_id?: string | null;
  data_quality?: DatasetQuality;
};

export type DatasetSnapshot = {
  schema_version: string;
  snapshot_id: string;
  provider: {
    configured_source?: string | null;
    available_sources?: string[];
  };
  cache: {
    store_available: boolean;
    metadata_available: boolean;
  };
  date_range: {
    start: string;
    end: string;
  };
  row_count: number;
  adjustment_mode?: string | null;
  data_quality: DatasetQuality;
  symbol_universe: DatasetSnapshotSymbol[];
};

export type AfterCostEvidence = {
  net_pnl?: number;
  total_cost?: number;
  gross_pnl_before_costs?: number;
  net_return?: number;
  gross_return_before_costs?: number;
  cost_to_initial_cash?: number;
  fill_count?: number;
  gross_turnover?: number;
  cost_assumptions?: string[];
  slippage_assumptions?: string[];
  assumptions?: string[];
  limitations?: string[];
};

export type ValidationSegmentEvidence = {
  start_timestamp?: string;
  end_timestamp?: string;
  initial_equity?: number;
  final_equity?: number;
  net_pnl?: number;
  net_return?: number;
  total_cost?: number;
  gross_pnl_before_costs?: number;
  gross_return_before_costs?: number;
  fill_count?: number;
};

export type OutOfSampleValidation = {
  strategy_id?: string;
  benchmark_role?: string;
  split_timestamp?: string;
  in_sample?: ValidationSegmentEvidence;
  out_of_sample?: ValidationSegmentEvidence;
  benchmark_return?: number | null;
  excess_return?: number | null;
  passed_benchmark?: boolean | null;
  validation_status?: string;
  assumptions?: string[];
  limitations?: string[];
};

export type BacktestEquityPoint = {
  timestamp: string;
  equity: number;
};

export type BacktestFill = {
  fill_id?: string;
  order_id?: string;
  timestamp?: string;
  symbol: string;
  side: string;
  fill_price: number;
  fill_quantity: number;
  commission: number;
  slippage: number;
};

export type BacktestSummary = {
  id: number;
  created_at: string;
  strategy: string;
  total_return: number;
  sharpe: number;
  max_drawdown: number;
};

export type StrategyParameterSchema = {
  name: string;
  type: 'int' | 'float' | 'str' | 'bool' | 'dict' | string;
  default: number | string | boolean | Record<string, unknown> | null;
  required: boolean;
  min?: number | null;
  max?: number | null;
  allowed_values?: Array<string | number | boolean> | null;
  description: string;
};

export type BacktestStrategyInfo = {
  strategy_id: string;
  name: string;
  display_name: string;
  description: string;
  params: StrategyParameterSchema[];
  parameter_schema: StrategyParameterSchema[];
  asset_universe?: string[];
  supported_frequencies?: string[];
  benchmark_role?: string | null;
  benchmark_universe?: string[];
  requires_out_of_sample_validation?: boolean;
  requires_after_cost_report?: boolean;
  validation_notes?: string[];
};

export type StrategyMetadataSnapshot = {
  schema_version: string;
  strategy_id: string;
  name?: string;
  display_name?: string;
  description?: string;
  asset_universe?: string[];
  supported_frequencies?: string[];
  benchmark_role?: string | null;
  benchmark_universe?: string[];
  requires_out_of_sample_validation?: boolean;
  requires_after_cost_report?: boolean;
  validation_notes?: string[];
  parameter_schema?: StrategyParameterSchema[];
  params?: Record<string, number | string | boolean | null>;
};

export type BacktestRunRequest = {
  start_date: string;
  end_date: string;
  initial_cash: number;
  strategy: string;
  short_period?: number;
  long_period?: number;
  params?: Record<string, number | string | boolean | null>;
  assets?: Array<{ symbol: string; asset_class: string }>;
};

export type StrategySignalPreviewRequest = {
  strategy: string;
  symbol: string;
  asset_class?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  params?: Record<string, number | string | boolean | null>;
};

export type StrategySignalPreviewOutput = {
  output_id: string;
  output_type: string;
  record_kind: string;
  action: string;
  reason: string;
  symbol: string;
  target_weight?: string | null;
  quantity?: number | string | null;
  price?: string | null;
  evidence: {
    bar_count?: number;
    dataset_snapshot_id?: string | null;
    data_quality_status?: string | null;
    signal_timestamp?: string | null;
    reference_price?: string | null;
    research_only?: boolean;
    does_not_enable_execution?: boolean;
  };
  review_gates?: Array<{
    key: string;
    status: string;
    severity?: string | null;
    summary?: string | null;
    required_action?: string | null;
    evidence_ref?: string | null;
  }>;
  requires_risk_gate: boolean;
  requires_account_truth_gate: boolean;
  requires_paper_shadow_review: boolean;
  requires_manual_review: boolean;
  does_not_enable_execution: boolean;
};

export type StrategySignalPreviewResponse = {
  schema_version: string;
  strategy_id: string;
  symbol: string;
  params: Record<string, number | string | boolean | null>;
  run_id: string;
  dataset_snapshot_id?: string | null;
  record_count: number;
  outputs: StrategySignalPreviewOutput[];
  limitations: string[];
  does_not_enable_execution: boolean;
};

export type BacktestRiskPreviewRequest = {
  strategy: string;
  symbol: string;
  asset_class: string;
  action: string;
  quantity: number;
  reference_price: number;
  target_weight?: string | number | null;
  data_quality_status?: string | null;
};

export type BacktestRiskPreviewResponse = {
  schema_version: string;
  passed: boolean;
  status: string;
  severity: string;
  reasons: string[];
  manual_confirmation_required: boolean;
  does_not_create_order: boolean;
  does_not_persist_decision: boolean;
  metadata?: Record<string, unknown>;
};

export type BacktestPaperShadowPreviewRequest = {
  strategy: string;
  symbol: string;
  asset_class: string;
  action: string;
  quantity: number;
  reference_price: number;
  target_weight?: string | number | null;
  signal_id?: string | null;
  dataset_snapshot_id?: string | null;
  risk_preview_passed: boolean;
  risk_reasons: string[];
};

export type BacktestPaperShadowPreviewResponse = {
  schema_version: string;
  status: string;
  execution_mode: string;
  manual_confirmation_required: boolean;
  does_not_create_order: boolean;
  does_not_create_fill: boolean;
  does_not_mutate_ledger: boolean;
  risk_reasons: string[];
  order: Record<string, unknown> | null;
  fill: {
    fill_price?: string | null;
    fill_quantity?: string | null;
    commission?: string | null;
    fee_breakdown?: {
      gross_amount?: string | null;
      total_fee?: string | null;
      fee_rule_id?: string | null;
      limitations?: string[];
    } | null;
  } | null;
  shadow_review?: {
    candidate_count?: number;
    supported_match_count?: number;
    unsupported_real_movement_count?: number;
  } | null;
  limitations: string[];
};

export type BacktestAttributionPreviewRequest = {
  strategy: string;
  symbol: string;
  asset_class: string;
  signal_id?: string | null;
  dataset_snapshot_id?: string | null;
  risk_preview_passed: boolean;
  risk_reasons: string[];
  paper_shadow_status?: string | null;
  paper_shadow_order?: Record<string, unknown> | null;
  paper_shadow_fill?: Record<string, unknown> | null;
};

export type BacktestAttributionPreviewResponse = {
  schema_version: string;
  status: string;
  strategy_id: string;
  symbol: string;
  asset_class: string;
  attribution_status: string;
  can_attribute_pnl: boolean;
  does_not_create_order: boolean;
  does_not_create_fill: boolean;
  does_not_mutate_ledger: boolean;
  risk_reasons: string[];
  evidence_counts: {
    signal_preview: number;
    risk_preview: number;
    paper_shadow_order: number;
    paper_shadow_fill: number;
    production_order: number;
    production_fill: number;
  };
  evidence_refs: string[];
  required_next_actions: string[];
  review_linkage_candidate?: {
    candidate_id: string;
    strategy_id: string;
    symbol: string;
    asset_class: string;
    signal_ref: string | null;
    dataset_snapshot_ref: string | null;
    risk_preview_ref: string | null;
    paper_shadow_order_ref: string | null;
    paper_shadow_fill_ref: string | null;
    recommended_review_action: string;
    manual_confirmation_required: boolean;
    does_not_create_order: boolean;
    does_not_create_fill: boolean;
    does_not_mutate_ledger: boolean;
    can_link_to_strategy_pnl: boolean;
  } | null;
  limitations: string[];
};

export type BacktestSweepRequest = {
  start_date: string;
  end_date: string;
  initial_cash: number;
  strategy: string;
  params?: Record<string, number | string | boolean | null>;
  param_grid: Record<string, Array<number | string | boolean | null>>;
  assets?: Array<{ symbol: string; asset_class: string }>;
  rank_by?: string;
  max_combinations?: number;
};

export type BacktestSweepResult = {
  rank: number;
  result_id: number;
  strategy: string;
  params: Record<string, number | string | boolean | null>;
  metrics: BacktestMetrics;
  score: number;
};

export type BacktestSweepResponse = {
  strategy: string;
  rank_by: string;
  tested_count: number;
  results: BacktestSweepResult[];
  warnings: string[];
};

export type BacktestCompareRunRequest = {
  strategy: string;
  params?: Record<string, number | string | boolean | null>;
};

export type BacktestCompareRequest = {
  start_date: string;
  end_date: string;
  initial_cash: number;
  strategies?: string[];
  runs?: BacktestCompareRunRequest[];
  assets?: Array<{ symbol: string; asset_class: string }>;
};

export type BacktestCompareResult = {
  strategy: string;
  description: string;
  result_id?: number | null;
  params: Record<string, number | string | boolean | null>;
  dataset_snapshot_id?: string | null;
  dataset_snapshot?: Partial<DatasetSnapshot>;
  metrics: BacktestMetrics;
  equity_curve: BacktestEquityPoint[];
};

export type BacktestCompareResponse = {
  results: BacktestCompareResult[];
  compared_count: number;
  dataset_snapshot_id?: string | null;
  dataset_snapshot?: Partial<DatasetSnapshot>;
  warnings: string[];
};

export type BacktestReport = {
  id: number;
  created_at: string;
  config: {
    start_date: string;
    end_date: string;
    initial_cash: number;
    strategy: string;
    short_period?: number;
    long_period?: number;
    params?: Record<string, number | string | boolean | null>;
    assets?: Array<{ symbol: string; asset_class: string }> | null;
  };
  metrics: BacktestMetrics;
  metrics_json?: Partial<BacktestMetrics> & {
    dataset_snapshot?: DatasetSnapshot;
    evidence_bundle?: AfterCostEvidence;
    oos_validation?: OutOfSampleValidation;
    strategy_metadata?: StrategyMetadataSnapshot;
  };
  cost_summary_json?: CostSummary;
  evidence_json?: AfterCostEvidence;
  fills?: BacktestFill[];
  equity_curve: BacktestEquityPoint[];
};

export type StrategyValidationRow = {
  strategy_id: string;
  benchmark_role: string;
  requires_out_of_sample_validation: boolean;
  requires_after_cost_report: boolean;
  has_out_of_sample_validation: boolean;
  has_after_cost_report: boolean;
  validation_status: string | null;
  backtest_result_id: number | null;
  missing_requirements: string[];
  is_ready: boolean;
};

export type StrategyValidationMatrix = {
  required_strategy_count: number;
  ready_strategy_count: number;
  is_complete: boolean;
  rows: StrategyValidationRow[];
  limitations: string[];
};

export type StrategyPromotionReadinessRow = {
  strategy_id: string;
  benchmark_role: string;
  backtest_result_id: number | null;
  has_after_cost_and_oos_evidence: boolean;
  has_risk_block_evidence: boolean;
  has_paper_shadow_evidence: boolean;
  has_paper_shadow_divergence_review: boolean;
  has_account_truth_evidence: boolean;
  account_truth_gate_status: string;
  account_truth_score: number | null;
  has_strategy_attribution_evidence: boolean;
  strategy_attribution_status: string;
  missing_requirements: string[];
  promotion_status: string;
  is_promotable: boolean;
};

export type StrategyPromotionReadiness = {
  required_strategy_count: number;
  promotable_strategy_count: number;
  is_complete: boolean;
  rows: StrategyPromotionReadinessRow[];
  limitations: string[];
};

export type AccountStrategyAssignment = {
  strategy_id: string;
  strategy_name: string;
  status: string;
  scope: string;
  asset_class?: string | null;
  symbol?: string | null;
  effective_from?: string | null;
  auto_trade_enabled: boolean;
  attribution_status: string;
  attributed_pnl?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  total_fees?: number | null;
  notes?: string;
  updated_at?: string | null;
  limitations: string[];
};

export type AccountStrategyAttributionSummary = {
  strategy_id: string;
  attribution_status: string;
  signal_count: number;
  action_count: number;
  risk_decision_count: number;
  order_count: number;
  fill_count: number;
  unattributed_fill_count: number;
  total_fees: number;
  attributed_pnl?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  evidence_refs: string[];
  limitations: string[];
};

export type AccountStrategyContributionReport = {
  strategy_id: string;
  contribution_status: string;
  linked_fill_count: number;
  gross_realized_pnl: number;
  gross_unrealized_pnl: number;
  total_commission: number;
  total_slippage: number;
  total_tax: number;
  net_contribution: number;
  unattributed_account_pnl?: number | null;
  manual_unattributed_pnl?: number | null;
  cash_flow_pnl?: number | null;
  missing_valuation_symbols: string[];
  evidence_refs: string[];
  limitations: string[];
};

export type AccountStrategyAssignmentUpdate = {
  strategy_id: string;
  status?: string;
  scope?: string;
  asset_class?: string | null;
  symbol?: string | null;
  effective_from?: string | null;
  notes?: string;
};

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function useBacktestResultsQuery() {
  return useQuery({
    queryKey: ['backtest-results'],
    queryFn: () => apiClient<BacktestSummary[]>('/api/backtest/results'),
    staleTime: 10_000,
  });
}

export function useBacktestStrategiesQuery() {
  return useQuery({
    queryKey: ['backtest-strategies'],
    queryFn: () =>
      apiClient<BacktestStrategyInfo[]>('/api/backtest/strategies'),
    staleTime: 60_000,
  });
}

export function useAccountStrategyAssignmentQuery() {
  return useQuery({
    queryKey: ['account-strategy-assignment'],
    queryFn: () =>
      apiClient<AccountStrategyAssignment>('/api/account-strategy'),
    staleTime: 10_000,
  });
}

export function useAccountStrategyAttributionQuery() {
  return useQuery({
    queryKey: ['account-strategy-attribution'],
    queryFn: () =>
      apiClient<AccountStrategyAttributionSummary>(
        '/api/account-strategy/attribution',
      ),
    staleTime: 10_000,
  });
}

export function useAccountStrategyContributionQuery() {
  return useQuery({
    queryKey: ['account-strategy-contribution'],
    queryFn: () =>
      apiClient<AccountStrategyContributionReport>(
        '/api/account-strategy/contribution',
      ),
    staleTime: 10_000,
  });
}

export function useUpdateAccountStrategyAssignmentMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AccountStrategyAssignmentUpdate) =>
      putJson<AccountStrategyAssignment>('/api/account-strategy', payload),
    onSuccess: (assignment) => {
      queryClient.setQueryData(['account-strategy-assignment'], assignment);
      void queryClient.invalidateQueries({
        queryKey: ['account-strategy-attribution'],
      });
      void queryClient.invalidateQueries({
        queryKey: ['account-strategy-contribution'],
      });
    },
  });
}

export function useRunBacktestMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BacktestRunRequest) =>
      postJson<BacktestReport>('/api/backtest/run', payload),
    onSuccess: async (report) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['backtest-results'] }),
        queryClient.invalidateQueries({
          queryKey: ['backtest-result', report.id],
        }),
      ]);
    },
  });
}

export function useStrategySignalPreviewMutation() {
  return useMutation({
    mutationFn: (payload: StrategySignalPreviewRequest) =>
      postJson<StrategySignalPreviewResponse>(
        '/api/backtest/signal-preview',
        payload,
      ),
  });
}

export function useBacktestRiskPreviewMutation() {
  return useMutation({
    mutationFn: (payload: BacktestRiskPreviewRequest) =>
      postJson<BacktestRiskPreviewResponse>(
        '/api/backtest/risk-preview',
        payload,
      ),
  });
}

export function useBacktestPaperShadowPreviewMutation() {
  return useMutation({
    mutationFn: (payload: BacktestPaperShadowPreviewRequest) =>
      postJson<BacktestPaperShadowPreviewResponse>(
        '/api/backtest/paper-shadow-preview',
        payload,
      ),
  });
}

export function useBacktestAttributionPreviewMutation() {
  return useMutation({
    mutationFn: (payload: BacktestAttributionPreviewRequest) =>
      postJson<BacktestAttributionPreviewResponse>(
        '/api/backtest/attribution-preview',
        payload,
      ),
  });
}

export function useRunBacktestSweepMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BacktestSweepRequest) =>
      postJson<BacktestSweepResponse>('/api/backtest/sweep', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['backtest-results'] });
    },
  });
}

export function useRunBacktestCompareMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BacktestCompareRequest) =>
      postJson<BacktestCompareResponse>('/api/backtest/compare', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['backtest-results'] });
    },
  });
}

export function useBacktestResultQuery(resultId: number | null) {
  return useQuery({
    queryKey: ['backtest-result', resultId],
    queryFn: () =>
      apiClient<BacktestReport>(`/api/backtest/results/${resultId}`),
    enabled: resultId !== null,
    staleTime: 10_000,
  });
}

export function useStrategyValidationQuery() {
  return useQuery({
    queryKey: ['backtest-strategy-validation'],
    queryFn: () =>
      apiClient<StrategyValidationMatrix>('/api/backtest/strategy-validation'),
    staleTime: 10_000,
  });
}

export function useStrategyPromotionReadinessQuery() {
  return useQuery({
    queryKey: ['backtest-strategy-promotion-readiness'],
    queryFn: () =>
      apiClient<StrategyPromotionReadiness>(
        '/api/backtest/strategy-promotion-readiness',
      ),
    staleTime: 10_000,
  });
}
