import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../lib/api/client";

export type AccountOverview = {
  total_equity: number;
  available_cash: number;
  total_deposits: number;
  positions_count: number;
  unrealized_pnl: number;
  realized_pnl: number;
  cash_ratio: number;
};

export type EquityPoint = {
  timestamp: string;
  equity: number;
};

export function useAccountOverviewQuery() {
  return useQuery({
    queryKey: ["account-overview"],
    queryFn: () => apiClient<AccountOverview>("/api/portfolio/overview"),
  });
}

export function useEquityCurveQuery() {
  return useQuery({
    queryKey: ["account-equity-curve"],
    queryFn: () => apiClient<EquityPoint[]>("/api/portfolio/equity-curve"),
  });
}
