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
  metrics_json?: Partial<BacktestMetrics>;
  cost_summary_json?: CostSummary;
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

export function useBacktestResultQuery(resultId: number | null) {
  return useQuery({
    queryKey: ['backtest-result', resultId],
    queryFn: () =>
      apiClient<BacktestReport>(`/api/backtest/results/${resultId}`),
    enabled: resultId !== null,
    staleTime: 10_000,
  });
}
