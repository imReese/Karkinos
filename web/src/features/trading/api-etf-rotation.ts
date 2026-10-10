import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';

export type EtfStrategyMetrics = {
  strategy_name: string;
  universe_summary: string;
  backtest_range: string;
  cumulative_return_pct: number;
  cagr_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  calmar_ratio: number;
  benchmark_name: string;
  benchmark_return_pct: number;
  excess_return_pct: number;
  core_advantage?: string;
  verification_status?:
    'bound_dataset_verified' | 'offline_reference_unbound' | string;
  disclaimer?: string;
  dataset_id?: string;
  source_result_id?: number;
  report_url?: string;
};

export type EtfPaperBookSummary = {
  book_id: string;
  observation_id: string;
  settled_sessions: number;
  equity: string;
  net_return: string;
  net_return_pct: number;
  max_drawdown: string;
  max_drawdown_pct: number;
  fees_paid: string;
  slippage_cost: string;
  health_status: string;
  through_session?: string | null;
  evaluation_start?: string | null;
};

export type EtfRebalanceOrder = {
  symbol: string;
  name: string;
  side: 'buy' | 'sell';
  side_display: string;
  quantity: number;
  price: number;
  amount: number;
  target_weight: number;
  current_weight: number;
  reason: string;
};

export type EtfRebalancePlanSummary = {
  status: string;
  plan_id?: string;
  evaluated_at: string;
  as_of_date: string;
  total_equity: number;
  capital_source?:
    | 'available_cash'
    | 'held_positions_rebalance'
    | 'custom'
    | 'custom_simulation'
    | 'fallback_demo'
    | string;
  is_demo?: boolean;
  is_custom_simulation?: boolean;
  account_available?: boolean;
  available_cash?: number;
  strategy_etf_value?: number;
  turnover_ratio: number;
  total_sell_amount: number;
  total_buy_amount: number;
  estimated_net_cash_flow: number;
  orders_count: number;
  orders: EtfRebalanceOrder[];
  markdown_table?: string;
  csv_content?: string;
  miniqmt_script?: string;
};

export type EtfExecutionReceipt = {
  status: string;
  plan_id?: string;
  is_simulated?: boolean;
  batch_id: string;
  executed_at: string;
  operator: string;
  note: string;
  broker_mode: string;
  orders_count: number;
  total_sell_amount: number;
  total_buy_amount: number;
  executed_orders: Array<{
    order_id: string;
    symbol: string;
    name: string;
    side: string;
    side_display: string;
    quantity: number;
    price: number;
    amount: number;
    status: string;
    is_simulated?: boolean;
    submitted_at: string;
    reason: string;
  }>;
  message: string;
};

export type EtfRotationDashboardResponse = {
  status: string;
  strategy: EtfStrategyMetrics;
  strategy_periods?: {
    '5y': EtfStrategyMetrics;
    from_2025: EtfStrategyMetrics;
  };
  paper_book?: EtfPaperBookSummary | null;
  rebalance: EtfRebalancePlanSummary | null;
  orders: EtfRebalanceOrder[];
  execution_status:
    | 'ready_to_trade'
    | 'portfolio_balanced'
    | 'already_executed_today'
    | 'unavailable';
  has_pending_orders: boolean;
  can_execute: boolean;
  is_demo?: boolean;
  is_custom_simulation?: boolean;
  capital_quarantined?: boolean;
  last_execution: EtfExecutionReceipt | null;
};

export type ExecuteOrdersPayload = {
  operator?: string;
  note?: string;
  broker_mode?: string;
};

export function useEtfRotationDashboardQuery(enabled?: boolean) {
  const isTest =
    typeof import.meta !== 'undefined' && import.meta.env?.MODE === 'test';
  const shouldEnable = isTest ? false : (enabled ?? true);
  return useQuery({
    queryKey: ['trading', 'etf-rotation-dashboard'],
    queryFn: () =>
      apiClient<EtfRotationDashboardResponse>(
        '/api/trading/etf-rebalance/dashboard',
      ),
    staleTime: 5_000,
    enabled: shouldEnable,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });
}

export function useExecuteEtfRotationOrdersMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: ExecuteOrdersPayload = {}) =>
      postJson<EtfExecutionReceipt>(
        '/api/trading/etf-rebalance/execute',
        payload,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['trading', 'etf-rotation-dashboard'],
      });
      await queryClient.invalidateQueries({
        queryKey: ['account'],
      });
    },
  });
}
