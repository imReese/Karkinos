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
  name?: string | null;
  display_name?: string | null;
  asset_class?: string | null;
  quantity: number;
  available_qty: number;
  frozen_qty: number;
  avg_cost: number;
  broker_displayed_unit_cost?: number | null;
  broker_displayed_cost_basis?: number | null;
  broker_cost_basis_difference?: number | null;
  broker_cost_basis_method?: string | null;
  broker_cost_basis_status?: string | null;
  latest_price?: number | null;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  commission_paid: number;
  today_change?: number | null;
  today_change_pct?: number | null;
  baseline_price?: number | null;
  baseline_timestamp?: string | null;
  baseline_source?: string;
  quote_timestamp?: string | null;
  quote_status?: string;
  quote_source?: string | null;
  quote_age_seconds?: number | null;
  stale_reason?: string | null;
  refresh_policy?: string | null;
  using_persistent_cache?: boolean;
  nav_date?: string | null;
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

export type PortfolioActionTask = {
  id?: number | null;
  source_signal_id?: number | null;
  symbol: string;
  title: string;
  detail: string;
  direction: string;
  urgency: string;
  target_weight: number;
  price?: number | null;
  strategy_id: string;
  timestamp: string;
  asset_class: string;
  status: string;
  risk_decision_id?: string | null;
  risk_gate_passed?: boolean | null;
  risk_gate_status: string;
  risk_gate_severity?: string | null;
  risk_gate_reasons?: string[];
  manual_confirmation_required?: boolean;
  manual_confirmation_status?: string;
  manual_confirmation_reason?: string;
};

export type PortfolioCockpitPosition = {
  symbol: string;
  name: string;
  asset_class: string;
  market_value: number;
  actual_weight: number;
  target_weight: number;
  drift: number;
  action_task?: PortfolioActionTask | null;
};

export type PortfolioConstructionRecommendation = {
  symbol: string;
  name: string;
  asset_class: string;
  direction: string;
  status: string;
  actionable: boolean;
  actual_weight: number;
  target_weight: number;
  drift: number;
  account_truth_gate_status: string;
  risk_gate_status: string;
  required_actions: string[];
  rationale: string;
  source_action_task_id?: number | null;
};

export type PortfolioCockpit = {
  summary: unknown;
  positions: PortfolioCockpitPosition[];
  action_queue: PortfolioActionTask[];
  risk_alerts: unknown[];
  construction_recommendations: PortfolioConstructionRecommendation[];
};

export type PortfolioSnapshot = {
  cash: number;
  total_equity: number;
  total_deposits: number;
  positions: Position[];
  allocation: AllocationItem[];
  allocation_grouped: AllocationGroup[];
  valuation_snapshot_id?: string | null;
  valuation_as_of?: string | null;
  valuation_trade_date?: string | null;
  valuation_policy?: string | null;
  valuation_status?: string;
  ledger_cutoff_id?: number;
  ledger_fingerprint?: string | null;
  quote_set_fingerprint?: string | null;
};

export type LiveHoldingItem = {
  symbol: string;
  name: string;
  display_name?: string | null;
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
  quote_source?: string | null;
  quote_age_seconds?: number | null;
  stale_reason?: string | null;
  refresh_policy?: string | null;
  using_persistent_cache?: boolean;
  nav_date?: string | null;
};

export type LiveHoldingGroup = {
  asset_class: string;
  label: string;
  total_market_value: number;
  total_today_change: number | null;
  total_since_buy_pnl: number;
  items: LiveHoldingItem[];
};

export type LiveHoldingsResponse = {
  groups: LiveHoldingGroup[];
  valuation_snapshot_id?: string | null;
  valuation_as_of?: string | null;
  valuation_trade_date?: string | null;
  valuation_policy?: string | null;
  valuation_status?: string;
  ledger_cutoff_id?: number;
  ledger_fingerprint?: string | null;
  quote_set_fingerprint?: string | null;
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

export function usePortfolioCockpitQuery() {
  return useQuery({
    queryKey: ['portfolio-cockpit'],
    queryFn: () => apiClient<PortfolioCockpit>('/api/portfolio/cockpit'),
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
