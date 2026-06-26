import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

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
  strategy_health_status: string;
  strategy_health_reasons: string[];
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

export type HoldingStrategyAttributionReport = {
  strategy_id: string;
  symbol: string;
  assignment_scope: string;
  assignment_applies_to_symbol: boolean;
  attribution_status: string;
  signal_count: number;
  action_count: number;
  risk_decision_count: number;
  order_count: number;
  fill_count: number;
  evidence_refs: string[];
  limitations: string[];
};

export function useAccountStrategyAssignmentQuery() {
  return useQuery({
    queryKey: ['account-strategy-assignment'],
    queryFn: () =>
      apiClient<AccountStrategyAssignment>('/api/account-strategy'),
    staleTime: 10_000,
  });
}

export function useHoldingStrategyAttributionQuery(symbol: string) {
  const normalizedSymbol = symbol.trim();
  return useQuery({
    queryKey: ['holding-strategy-attribution', normalizedSymbol],
    queryFn: () =>
      apiClient<HoldingStrategyAttributionReport>(
        `/api/account-strategy/holdings/${encodeURIComponent(
          normalizedSymbol,
        )}/attribution`,
      ),
    enabled: normalizedSymbol.length > 0,
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
