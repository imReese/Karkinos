import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

const LIVE_REFETCH_MS = 5_000;

function liveRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return LIVE_REFETCH_MS;
}

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

export type LiveHoldingItem = {
  symbol: string;
  name: string;
  asset_class: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  latest_price: number | null;
  quote_timestamp: string | null;
  since_buy_pnl: number;
  since_buy_pnl_pct: number | null;
  today_change: number | null;
  today_change_pct: number | null;
  baseline_price: number | null;
  baseline_timestamp: string | null;
  baseline_source: string;
  quote_status: string;
};

export type LiveHoldingGroup = {
  asset_class: string;
  label: string;
  total_market_value: number;
  total_today_change: number;
  total_since_buy_pnl: number;
  items: LiveHoldingItem[];
};

export type LiveHoldingsResponse = {
  groups: LiveHoldingGroup[];
};

export function usePositionsQuery() {
  return useQuery({
    queryKey: ['portfolio-positions'],
    queryFn: () => apiClient<Position[]>('/api/portfolio/positions'),
    staleTime: 10_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useAllocationQuery() {
  return useQuery({
    queryKey: ['portfolio-allocation'],
    queryFn: () => apiClient<AllocationItem[]>('/api/portfolio/allocation'),
    staleTime: 15_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function usePortfolioSnapshotQuery() {
  return useQuery({
    queryKey: ['portfolio-snapshot'],
    queryFn: () => apiClient<PortfolioSnapshot>('/api/portfolio'),
    staleTime: 10_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useLiveHoldingsQuery() {
  return useQuery({
    queryKey: ['portfolio-live-holdings'],
    queryFn: () =>
      apiClient<LiveHoldingsResponse>('/api/portfolio/live-holdings'),
    staleTime: 10_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
