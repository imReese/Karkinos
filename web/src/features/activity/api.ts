import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';
import { visiblePersistedProjectionRefetchInterval } from '../../shared/api/query-policy';

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
  command_id?: string;
  operator_id?: string;
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
  operator_id?: string;
  request_id?: string;
  occurred_at: string;
  amount: number;
  flow_type: string;
  note: string;
};

export type DividendPayload = {
  operator_id?: string;
  request_id?: string;
  occurred_at: string;
  symbol: string;
  asset_class: string;
  amount: number;
  note: string;
};

export type AdjustmentPayload = {
  operator_id?: string;
  request_id?: string;
  occurred_at: string;
  symbol: string | null;
  asset_class: string;
  amount: number | null;
  quantity: number | null;
  price: number | null;
  note: string;
};

export function useLedgerEntriesQuery(limit = 50, enabled = true) {
  return useQuery({
    queryKey: ['ledger-entries', limit],
    queryFn: () =>
      apiClient<LedgerEntry[]>(`/api/ledger/entries?limit=${limit}`),
    staleTime: 2_000,
    enabled,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
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

function buildTradeRequestBody(payload: TradePayload, mutation = false) {
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
  if (mutation) {
    requestBody.command_id =
      payload.command_id ?? globalThis.crypto.randomUUID();
    requestBody.operator_id = payload.operator_id ?? 'local-owner';
  }
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
      postJson('/api/portfolio/trade', buildTradeRequestBody(payload, true)),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateCashFlowMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CashFlowPayload) =>
      postJson('/api/ledger/cash-flows', withLedgerMutationIdentity(payload)),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateDividendMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: DividendPayload) =>
      postJson('/api/ledger/dividends', withLedgerMutationIdentity(payload)),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateAdjustmentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: AdjustmentPayload) =>
      postJson('/api/ledger/adjustments', withLedgerMutationIdentity(payload)),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

function withLedgerMutationIdentity<T extends object>(payload: T) {
  const identified = payload as T & {
    operator_id?: string;
    request_id?: string;
  };
  return {
    ...payload,
    operator_id: identified.operator_id ?? 'local-owner',
    request_id: identified.request_id ?? globalThis.crypto.randomUUID(),
  };
}
