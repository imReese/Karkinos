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
  benchmark_role?: string | null;
  benchmark_universe?: string[];
  requires_out_of_sample_validation?: boolean;
  requires_after_cost_report?: boolean;
  validation_notes?: string[];
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
  };
  cost_summary_json?: CostSummary;
  evidence_json?: AfterCostEvidence;
  fills?: BacktestFill[];
  equity_curve: BacktestEquityPoint[];
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
