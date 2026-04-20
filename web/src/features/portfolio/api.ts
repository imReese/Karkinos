import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../lib/api/client";

export type Position = {
  symbol: string;
  quantity: number;
  available_qty: number;
  frozen_qty: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  commission_paid: number;
};

export type AllocationItem = {
  symbol: string;
  name: string;
  weight: number;
  value: number;
  asset_class: string;
};

export type AllocationGroup = {
  asset_class: string;
  name: string;
  value: number;
  weight: number;
  items: AllocationItem[];
};

export type PortfolioSnapshot = {
  cash: number;
  total_equity: number;
  total_deposits: number;
  positions: Position[];
  allocation: AllocationItem[];
  allocation_grouped: AllocationGroup[];
};

export function usePositionsQuery() {
  return useQuery({
    queryKey: ["portfolio-positions"],
    queryFn: () => apiClient<Position[]>("/api/portfolio/positions"),
  });
}

export function useAllocationQuery() {
  return useQuery({
    queryKey: ["portfolio-allocation"],
    queryFn: () => apiClient<AllocationItem[]>("/api/portfolio/allocation"),
  });
}

export function usePortfolioSnapshotQuery() {
  return useQuery({
    queryKey: ["portfolio-snapshot"],
    queryFn: () => apiClient<PortfolioSnapshot>("/api/portfolio"),
  });
}
