import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

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

export type LedgerEntry = {
  id: number;
  entry_type: string;
  timestamp: string;
  amount: number | null;
  symbol: string | null;
  display_name: string | null;
  direction: string | null;
  quantity: number | null;
  price: number | null;
  commission: number;
  asset_class: string;
  note: string;
  source: string;
  source_ref: string | null;
  created_at: string | null;
};

export type PendingFundOrder = {
  id: number;
  submitted_at: string;
  symbol: string;
  display_name: string;
  amount: number;
  commission: number;
  asset_class: string;
  target_trade_date: string;
  status: string;
  note: string;
  confirmed_nav: number | null;
  confirmed_quantity: number | null;
  confirmed_trade_date: string | null;
  trade_id: number | null;
  created_at: string;
  updated_at: string;
};

export type TradePayload = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  direction: string;
  quantity?: number | null;
  unit_price?: number | null;
  amount?: number | null;
  fee: number;
  note: string;
};

export type CashFlowPayload = {
  occurred_at: string;
  amount: number;
  flow_type: string;
  note: string;
};

export type DividendPayload = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  amount: number;
  note: string;
};

export type AdjustmentPayload = {
  occurred_at: string;
  symbol: string | null;
  asset_class: string;
  amount: number | null;
  quantity: number | null;
  price: number | null;
  note: string;
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
    let message = detail || `Request failed: ${response.status}`;
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown };
      if (typeof parsed.detail === 'string') {
        message = parsed.detail;
      }
    } catch {
      // Keep the raw response text when it is not JSON.
    }
    throw new Error(message);
  }

  return (await response.json()) as T;
}

export function useLedgerEntriesQuery(limit = 50) {
  return useQuery({
    queryKey: ['ledger-entries', limit],
    queryFn: () =>
      apiClient<LedgerEntry[]>(`/api/ledger/entries?limit=${limit}`),
    staleTime: 2_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function usePendingFundOrdersQuery() {
  return useQuery({
    queryKey: ['pending-fund-orders'],
    queryFn: () =>
      apiClient<PendingFundOrder[]>('/api/portfolio/pending-fund-orders'),
    staleTime: 15_000,
  });
}

function invalidatePortfolioQueries(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ['account-overview'] }),
    queryClient.invalidateQueries({ queryKey: ['account-state'] }),
    queryClient.invalidateQueries({ queryKey: ['account-equity-curve'] }),
    queryClient.invalidateQueries({
      queryKey: ['account-equity-curve-series'],
    }),
    queryClient.invalidateQueries({ queryKey: ['portfolio-risk-summary'] }),
    queryClient.invalidateQueries({ queryKey: ['portfolio-explainability'] }),
    queryClient.invalidateQueries({ queryKey: ['portfolio-positions'] }),
    queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
    queryClient.invalidateQueries({ queryKey: ['portfolio-snapshot'] }),
    queryClient.invalidateQueries({ queryKey: ['market-research-board'] }),
    queryClient.invalidateQueries({ queryKey: ['ledger-entries'] }),
    queryClient.invalidateQueries({ queryKey: ['pending-fund-orders'] }),
  ]);
}

export function useCreateTradeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: TradePayload) =>
      postJson('/api/portfolio/trade', {
        timestamp: payload.occurred_at,
        symbol: payload.symbol,
        direction: payload.direction,
        quantity: payload.quantity ?? null,
        price: payload.unit_price ?? null,
        amount: payload.amount ?? null,
        commission: payload.fee,
        asset_class: payload.asset_class,
        note: payload.note,
      }),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateCashFlowMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CashFlowPayload) =>
      postJson('/api/ledger/cash-flows', payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateDividendMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: DividendPayload) =>
      postJson('/api/ledger/dividends', payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateAdjustmentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: AdjustmentPayload) =>
      postJson('/api/ledger/adjustments', payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}
