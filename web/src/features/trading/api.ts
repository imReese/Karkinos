import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

const CONTROL_REFETCH_MS = 5_000;

function liveRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return CONTROL_REFETCH_MS;
}

async function requestJson<T>(
  path: string,
  {
    method,
    body,
  }: {
    method: 'POST' | 'PUT';
    body?: unknown;
  },
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
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

export type KillSwitchSnapshot = {
  kill_switch_enabled: boolean;
  reason: string;
  updated_at: string | null;
};

export type ManualOrder = {
  id: number;
  order_id: string;
  timestamp: string;
  symbol: string;
  display_name?: string | null;
  name?: string | null;
  side: string;
  order_type: string;
  quantity: number;
  price: number | null;
  intent_id: string | null;
  risk_decision_id: string | null;
  execution_mode: string;
  status: string;
  payload_json: string;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type ManualOrderStatus =
  | 'all'
  | 'pending_confirm'
  | 'confirmed'
  | 'rejected'
  | 'canceled';

export type OrderFact = {
  id?: number;
  order_id: string;
  timestamp: string;
  symbol: string;
  display_name?: string | null;
  name?: string | null;
  side: string;
  order_type: string;
  quantity: number;
  price: number | null;
  asset_class?: string | null;
  execution_mode: string;
  status: string;
  source?: string | null;
  source_ref?: string | null;
  intent_id?: string | null;
  risk_decision_id?: string | null;
  note?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type FillFact = {
  id?: number;
  fill_id?: string | null;
  order_id: string;
  timestamp: string;
  symbol: string;
  display_name?: string | null;
  name?: string | null;
  side: string;
  fill_price: number;
  fill_quantity: number;
  commission: number;
  slippage: number;
  asset_class?: string | null;
  execution_mode?: string | null;
  provider_name?: string | null;
  source?: string | null;
  source_ref?: string | null;
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  metadata?: Record<string, unknown> | string | null;
  metadata_json?: string | null;
};

export type ShadowRunResponse = {
  run_id: string;
  run_date: string;
  data_quality?: {
    passed_count: number;
    blocked_count: number;
    issues: unknown[];
  };
  processed_count: number;
  reused_count: number;
  skipped_count: number;
  orders: OrderFact[];
  reused_orders: OrderFact[];
  skipped: unknown[];
};

export function useKillSwitchQuery() {
  return useQuery({
    queryKey: ['trading-kill-switch'],
    queryFn: () => apiClient<KillSwitchSnapshot>('/api/trading/kill-switch'),
    staleTime: 2_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useSetKillSwitchMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: { enabled: boolean; reason: string }) =>
      requestJson<KillSwitchSnapshot>('/api/trading/kill-switch', {
        method: 'PUT',
        body: payload,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['trading-kill-switch'],
      });
    },
  });
}

export function usePendingManualOrdersQuery() {
  return useManualOrdersQuery('pending_confirm');
}

export function useManualOrdersQuery(status: ManualOrderStatus = 'all') {
  const normalizedStatus = status || 'all';
  const suffix =
    normalizedStatus === 'all'
      ? ''
      : `?status=${encodeURIComponent(normalizedStatus)}`;
  return useQuery({
    queryKey: ['trading-manual-orders', normalizedStatus],
    queryFn: () => apiClient<ManualOrder[]>(`/api/trading/orders${suffix}`),
    staleTime: 2_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

function useManualOrderStatusMutation(action: 'confirm' | 'reject') {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ orderId, reason }: { orderId: string; reason?: string }) =>
      requestJson<ManualOrder>(
        `/api/trading/orders/${encodeURIComponent(orderId)}/${action}`,
        {
          method: 'POST',
          body: action === 'reject' ? { reason: reason ?? '' } : undefined,
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['trading-manual-orders'],
        }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-risk-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['account-state'] }),
      ]);
    },
  });
}

export function useConfirmManualOrderMutation() {
  return useManualOrderStatusMutation('confirm');
}

export function useRejectManualOrderMutation() {
  return useManualOrderStatusMutation('reject');
}

export function useOrderFactsQuery() {
  return useQuery({
    queryKey: ['trading-order-facts'],
    queryFn: () => apiClient<OrderFact[]>('/api/trading/order-facts?limit=20'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useFillFactsQuery() {
  return useQuery({
    queryKey: ['trading-fill-facts'],
    queryFn: () => apiClient<FillFact[]>('/api/trading/fills?limit=20'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useDailyShadowRunMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      requestJson<ShadowRunResponse>('/api/trading/shadow-runs/daily', {
        method: 'POST',
        body: {},
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['trading-order-facts'] }),
        queryClient.invalidateQueries({ queryKey: ['trading-manual-orders'] }),
      ]);
    },
  });
}
