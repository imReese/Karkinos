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

export type AccountOverview = {
  total_equity: number;
  available_cash: number;
  total_deposits: number;
  positions_count: number;
  unrealized_pnl: number;
  realized_pnl: number;
  cash_ratio: number;
  today_pnl?: number | null;
  today_pnl_breakdown?: {
    stocks?: number | null;
    funds?: number | null;
    others?: number | null;
    total?: number | null;
  } | null;
  today_contributors?: Array<{
    symbol: string;
    name?: string | null;
    display_name?: string | null;
    asset_class: string;
    today_change: number;
    today_change_pct?: number | null;
    quote_status?: string;
  }>;
  current_drawdown?: number | null;
  current_drawdown_amount?: number | null;
  drawdown_peak_equity?: number | null;
  drawdown_latest_equity?: number | null;
  drawdown_peak_timestamp?: string | null;
  valuation_timestamp?: string | null;
  quote_status?: string;
  quote_age_seconds?: number | null;
  quote_source?: string | null;
  stale_reason?: string | null;
  refresh_policy?: string | null;
  using_persistent_cache?: boolean;
};

export type EquityPoint = {
  timestamp: string;
  equity: number;
};

export type EquitySeriesPoint = {
  timestamp: string;
  total: number | null;
  stocks: number | null;
  funds: number | null;
  others: number | null;
  cash: number;
  unrealized_pnl?: number | null;
  total_daily_change?: number | null;
  stocks_daily_change?: number | null;
  funds_daily_change?: number | null;
  others_daily_change?: number | null;
  quote_status?: string;
  quote_source?: string | null;
  quote_age_seconds?: number | null;
  stale_reason?: string | null;
  using_persistent_cache?: boolean;
  nav_date?: string | null;
};

export type EquityCurveRange = '1d' | '5d' | '1m' | '6m' | '1y' | 'all';

export type RiskSummaryItem = {
  kind: string;
  level: string;
  title: string;
  detail: string;
};

export type AccountStateResponse = {
  summary: AccountOverview;
  snapshot: {
    cash: number;
    total_equity: number;
    total_deposits: number;
    positions: Array<{
      symbol: string;
      name?: string | null;
      display_name?: string | null;
      asset_class?: string | null;
      quantity: number;
      available_qty: number;
      frozen_qty: number;
      avg_cost: number;
      market_value: number;
      unrealized_pnl: number;
      realized_pnl: number;
      commission_paid: number;
    }>;
    allocation: Array<{
      symbol: string;
      name: string;
      weight: number;
      value: number;
      asset_class: string;
    }>;
    allocation_grouped: Array<{
      asset_class: string;
      name: string;
      value: number;
      weight: number;
      items: Array<{
        symbol: string;
        name: string;
        weight: number;
        value: number;
        asset_class: string;
      }>;
    }>;
  };
  risks: RiskSummaryItem[];
  next_step: string;
};

export type ExplainabilityBridgeItem = {
  key: string;
  label: string;
  value: number;
  detail: string;
};

export type ExplainabilityDriver = {
  kind: string;
  title: string;
  detail: string;
  timestamp: string;
  symbol: string | null;
  amount: number | null;
  quantity?: number | null;
  price?: number | null;
  commission?: number | null;
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  asset_class?: string | null;
};

export type ExplainabilityPositionDriver = {
  symbol: string;
  asset_class: string;
  quantity: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  last_activity_at: string | null;
  last_activity_note: string | null;
};

export type ExplainabilityResponse = {
  equity_bridge: ExplainabilityBridgeItem[];
  recent_drivers: ExplainabilityDriver[];
  positions: ExplainabilityPositionDriver[];
  timeline: Array<{
    date: string;
    equity: number;
    delta: number;
    external_flow: number;
    market_pnl: number;
    market_breakdown?: Array<{
      key: string;
      label: string;
      value: number;
    }>;
    external_flow_breakdown?: Array<{
      key: string;
      label: string;
      value: number;
    }>;
    valuation_status?: string;
    missing_price_symbols?: string[];
    events: Array<{
      category: string;
      impact_source: string;
      kind: string;
      title: string;
      detail: string;
      timestamp: string;
      symbol: string | null;
      amount: number | null;
      quantity?: number | null;
      price?: number | null;
      commission?: number | null;
      gross_amount?: number | null;
      net_cash_impact?: number | null;
      fee_breakdown?: Record<string, number | string | null | undefined> | null;
      fee_rule_id?: string | null;
      fee_rule_version?: string | null;
      asset_class?: string | null;
    }>;
  }>;
};

export type RiskWorkspaceResponse = {
  metrics: Array<{
    key: string;
    label: string;
    value: number;
    display_value: string;
    level: string;
    detail: string;
  }>;
  drawdown: {
    current_drawdown: number;
    max_drawdown: number;
    latest_equity: number;
    peak_equity: number;
    peak_timestamp: string | null;
    trough_timestamp: string | null;
  };
  drawdown_series: Array<{
    timestamp: string;
    equity: number;
    peak_equity: number;
    drawdown: number;
  }>;
  exposure_buckets: Array<{
    bucket: string;
    label: string;
    value: number;
    weight: number;
    positions_count: number;
    symbols: string[];
  }>;
  concentration: Array<{
    symbol: string;
    asset_class: string;
    market_value: number;
    weight: number;
    unrealized_pnl: number;
    avg_cost: number;
    quantity: number;
  }>;
};

export function useAccountOverviewQuery() {
  return useQuery({
    queryKey: ['account-overview'],
    queryFn: () => apiClient<AccountOverview>('/api/portfolio/overview'),
    staleTime: 10_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useEquityCurveQuery() {
  return useQuery({
    queryKey: ['account-equity-curve'],
    queryFn: () => apiClient<EquityPoint[]>('/api/portfolio/equity-curve'),
    staleTime: 15_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useEquityCurveSeriesQuery(range: EquityCurveRange = 'all') {
  return useQuery({
    queryKey: ['account-equity-curve-series', range],
    queryFn: () =>
      apiClient<EquitySeriesPoint[]>(
        `/api/portfolio/equity-curve/series?range=${range}`,
      ),
    staleTime: 15_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useAccountStateQuery() {
  return useQuery({
    queryKey: ['account-state'],
    queryFn: () => apiClient<AccountStateResponse>('/api/portfolio/state'),
  });
}

export function useRiskSummaryQuery() {
  return useQuery({
    queryKey: ['portfolio-risk-summary'],
    queryFn: () => apiClient<RiskSummaryItem[]>('/api/portfolio/risk-summary'),
    staleTime: 15_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useExplainabilityQuery(filters?: {
  from_date?: string;
  to_date?: string;
  event_kind?: string;
}) {
  return useQuery({
    queryKey: ['portfolio-explainability', filters],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filters?.from_date) params.set('from_date', filters.from_date);
      if (filters?.to_date) params.set('to_date', filters.to_date);
      if (filters?.event_kind) params.set('event_kind', filters.event_kind);
      const suffix = params.size > 0 ? `?${params.toString()}` : '';
      return apiClient<ExplainabilityResponse>(
        `/api/portfolio/explainability${suffix}`,
      );
    },
    staleTime: 15_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useRiskWorkspaceQuery() {
  return useQuery({
    queryKey: ['portfolio-risk-workspace'],
    queryFn: () =>
      apiClient<RiskWorkspaceResponse>('/api/portfolio/risk-workspace'),
    staleTime: 15_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
