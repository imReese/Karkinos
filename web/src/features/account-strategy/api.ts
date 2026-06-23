import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

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
