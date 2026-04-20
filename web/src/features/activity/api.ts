import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../../lib/api/client";

export type LedgerEntry = {
  id: number;
  entry_type: string;
  timestamp: string;
  amount: number | null;
  symbol: string | null;
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

export type TradePayload = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  direction: string;
  quantity: number;
  unit_price: number;
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
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function useLedgerEntriesQuery() {
  return useQuery({
    queryKey: ["ledger-entries"],
    queryFn: () => apiClient<LedgerEntry[]>("/api/ledger/entries"),
  });
}

function invalidatePortfolioQueries(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["account-overview"] }),
    queryClient.invalidateQueries({ queryKey: ["account-equity-curve"] }),
    queryClient.invalidateQueries({ queryKey: ["portfolio-positions"] }),
    queryClient.invalidateQueries({ queryKey: ["portfolio-allocation"] }),
    queryClient.invalidateQueries({ queryKey: ["portfolio-snapshot"] }),
    queryClient.invalidateQueries({ queryKey: ["ledger-entries"] }),
  ]);
}

export function useCreateTradeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: TradePayload) =>
      postJson("/api/ledger/trades", payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateCashFlowMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CashFlowPayload) =>
      postJson("/api/ledger/cash-flows", payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateDividendMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: DividendPayload) =>
      postJson("/api/ledger/dividends", payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}

export function useCreateAdjustmentMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: AdjustmentPayload) =>
      postJson("/api/ledger/adjustments", payload),
    onSuccess: async () => {
      await invalidatePortfolioQueries(queryClient);
    },
  });
}
