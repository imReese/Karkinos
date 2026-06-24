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
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  cost_basis_method?: string | null;
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
  fee?: number | null;
  fee_is_manual?: boolean;
  note: string;
};

export type TradePreview = {
  symbol: string;
  direction: string;
  quantity: number;
  price: number;
  gross_amount: number;
  commission: number;
  total_fee: number;
  net_cash_impact: number;
  fee_breakdown: Record<string, number | string | null | undefined>;
  fee_rule_id: string;
  fee_rule_version: string;
  cost_basis_method: string;
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

function buildTradeRequestBody(payload: TradePayload) {
  const requestBody: Record<string, unknown> = {
    timestamp: payload.occurred_at,
    symbol: payload.symbol,
    direction: payload.direction,
    quantity: payload.quantity ?? null,
    price: payload.unit_price ?? null,
    amount: payload.amount ?? null,
    asset_class: payload.asset_class,
    note: payload.note,
  };
  if (
    payload.fee_is_manual &&
    typeof payload.fee === 'number' &&
    Number.isFinite(payload.fee)
  ) {
    requestBody.commission = payload.fee;
  }
  return requestBody;
}

export function useTradePreviewMutation() {
  return useMutation({
    mutationFn: (payload: TradePayload) =>
      postJson<TradePreview>(
        '/api/portfolio/trade/preview',
        buildTradeRequestBody(payload),
      ),
  });
}

export function useCreateTradeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: TradePayload) =>
      postJson('/api/portfolio/trade', buildTradeRequestBody(payload)),
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
