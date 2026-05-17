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
