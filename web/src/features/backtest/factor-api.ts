import { useMutation, useQuery } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';

export type UniverseMember = {
  symbol: string;
  name: string;
  asset_class: string;
  instrument_type: string;
  benchmark: boolean;
  cash_proxy: boolean;
  description: string;
};

export type CuratedUniverse = {
  universe_id: string;
  display_name: string;
  description: string;
  benchmark_symbol: string | null;
  cash_proxy_symbol: string | null;
  symbols: string[];
  member_count: number;
  members: UniverseMember[];
};

export type FactorEvaluationRequest = {
  universe_id: string;
  factor_type: string;
  lookback_period?: number;
  forward_period?: number;
  n_quantiles?: number;
};

export type FactorEvaluationResponse = {
  universe_id: string;
  universe_name: string;
  factor_type: string;
  lookback_period: number;
  forward_period: number;
  sample_count: number;
  summary: {
    sample_count: number;
    mean_ic: number;
    std_ic: number;
    icir: number;
    annualized_icir: number;
    t_stat: number;
    p_value: number;
    positive_ratio: number;
  };
  spread_summary: {
    annualized_spread_return: number;
    annualized_spread_volatility: number;
    spread_sharpe: number;
    spread_max_drawdown: number;
    monotonicity_score: number;
  };
  ic_series: Array<{ date: string; ic: number }>;
  quantile_cumulative: Array<{
    date: string;
    q1?: number;
    q2?: number;
    q3?: number;
    q4?: number;
    q5?: number;
    long_short?: number;
  }>;
  latest_cross_section: Array<{
    symbol: string;
    name: string;
    factor_value: number;
    rank: number;
    percentile: number;
  }>;
};

export function useUniversesQuery() {
  return useQuery({
    queryKey: ['curated-universes'],
    queryFn: () => apiClient<CuratedUniverse[]>('/api/universes'),
    staleTime: 60_000,
  });
}

export function useFactorEvaluationMutation() {
  return useMutation({
    mutationFn: (request: FactorEvaluationRequest) =>
      postJson<FactorEvaluationResponse>(
        '/api/analytics/factor-evaluation',
        request,
      ),
  });
}
