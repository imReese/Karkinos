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

export type ManualTicketOperatorForm = {
  schema_version: string;
  account_alias: string;
  field_labels?: Record<string, string>;
  fields?: Array<{
    key: string;
    label: string;
    value: string | number | boolean | null;
  }>;
  fee_tax_assumptions?: {
    source?: string | null;
    estimated_total_fee?: number | string | null;
    estimated_net_cash_impact?: number | string | null;
    fee_rule_id?: string | null;
    fee_rule_version?: string | null;
    fee_components?: Record<string, string | number | null | undefined>;
    notes?: string[];
  };
  cash_impact_preview?: {
    source?: string | null;
    estimated_gross_amount?: number | string | null;
    estimated_total_fee?: number | string | null;
    estimated_net_cash_impact?: number | string | null;
    available_cash_before?: number | string | null;
    available_cash_after?: number | string | null;
    cash_status?: string | null;
    cash_shortfall?: number | string | null;
  };
  position_cost_preview?: {
    source?: string | null;
    current_quantity?: number | string | null;
    current_avg_cost?: number | string | null;
    current_market_value?: number | string | null;
    estimated_quantity_after?: number | string | null;
    estimated_avg_cost_after?: number | string | null;
    cost_basis_method?: string | null;
  };
  trading_session_constraints?: {
    market?: string | null;
    timezone?: string | null;
    allowed_session?: string | null;
    asset_class?: string | null;
    notes?: string[];
  };
  safety?: Record<string, string | number | boolean | null | undefined>;
};

export type ManualTicketExportResponse = {
  schema_version: string;
  gateway_id: 'manual_ticket' | string;
  status: string;
  dry_run: boolean;
  submitted_to_broker: boolean;
  order_id: string;
  ticket: {
    symbol: string;
    side: string;
    asset_class?: string | null;
    quantity: number;
    order_type: string;
    limit_price?: number | null;
    copy_text: string;
    operator_form?: ManualTicketOperatorForm;
  };
  export: {
    schema_version: string;
    format: string;
    mime_type: string;
    file_name: string;
    copy_text: string;
    content?: {
      operator_form?: ManualTicketOperatorForm;
      [key: string]: unknown;
    };
    content_json: string;
  };
  limitations?: string[];
};

export type ManualExecutionPreviewRequest = {
  fill_price: string;
  quantity: string;
  fee?: string;
  tax?: string;
  transfer_fee?: string;
};

export type ControlledBridgeGateSummary = {
  schema_version?: string;
  status?: string;
  required_gates?: string[];
  gates?: Record<
    string,
    {
      status?: string | null;
      evidence_ref?: string | null;
      source?: string | null;
    }
  >;
  broker_submission_enabled?: boolean;
  submitted_to_broker?: boolean;
  does_not_authorize_execution?: boolean;
};

export type ManualExecutionValidation = {
  manual_confirmation_status?: string;
  gateway_evidence_status?: string;
  gateway_evidence?: Record<string, unknown>;
  controlled_bridge_policy?: Record<string, unknown>;
  broker_submission_enabled?: boolean;
  requires_human_broker_entry?: boolean;
  required_gate_summary?: ControlledBridgeGateSummary;
};

export type ManualExecutionPreviewResponse = {
  schema_version: string;
  gateway_id: 'manual_ticket' | string;
  status: string;
  dry_run: boolean;
  submitted_to_broker: boolean;
  does_not_mutate_production_ledger: boolean;
  order_id: string;
  actor?: string | null;
  preview_fingerprint?: string | null;
  fingerprint_scope?: string | null;
  execution_preview: {
    source?: string | null;
    symbol: string;
    side: string;
    asset_class?: string | null;
    quantity: string;
    fill_price: string;
    gross_amount: string;
    fee: string;
    tax: string;
    transfer_fee: string;
    total_cost: string;
    net_cash_impact: string;
    currency?: string | null;
    notes?: string[];
  };
  ledger_entry_draft: {
    schema_version: string;
    entry_type: string;
    symbol: string;
    side: string;
    asset_class?: string | null;
    quantity: string;
    price: string;
    gross_amount: string;
    fee: string;
    tax: string;
    transfer_fee: string;
    amount: string;
    source_order_id: string;
    source: string;
    requires_operator_save: boolean;
    does_not_mutate_production_ledger: boolean;
  };
  position_cost_preview?: ManualTicketOperatorForm['position_cost_preview'];
  validation?: ManualExecutionValidation;
  safety?: Record<string, string | number | boolean | null | undefined>;
  limitations?: string[];
};

export type ManualExecutionRecordRequest = ManualExecutionPreviewRequest & {
  preview_fingerprint: string;
  operator_note?: string;
};

export type ManualExecutionRecordResponse = ManualExecutionPreviewResponse & {
  status: 'manual_execution_recorded' | string;
  event_id: number | string;
  does_not_mutate_oms: boolean;
  requires_operator_ledger_save?: boolean;
  operator_note?: string | null;
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

export function useManualTicketExportMutation() {
  return useMutation({
    mutationFn: ({ orderId }: { orderId: string }) =>
      requestJson<ManualTicketExportResponse>(
        `/api/broker-gateway/orders/${encodeURIComponent(
          orderId,
        )}/manual-ticket/export`,
        {
          method: 'POST',
          body: { actor: 'web' },
        },
      ),
  });
}

export function useManualExecutionPreviewMutation() {
  return useMutation({
    mutationFn: ({
      orderId,
      fill_price,
      quantity,
      fee,
      tax,
      transfer_fee,
    }: { orderId: string } & ManualExecutionPreviewRequest) =>
      requestJson<ManualExecutionPreviewResponse>(
        `/api/broker-gateway/orders/${encodeURIComponent(
          orderId,
        )}/manual-execution/preview`,
        {
          method: 'POST',
          body: {
            actor: 'web',
            fill_price,
            quantity,
            fee,
            tax,
            transfer_fee,
          },
        },
      ),
  });
}

export function useManualExecutionRecordMutation() {
  return useMutation({
    mutationFn: ({
      orderId,
      fill_price,
      quantity,
      fee,
      tax,
      transfer_fee,
      preview_fingerprint,
      operator_note,
    }: { orderId: string } & ManualExecutionRecordRequest) =>
      requestJson<ManualExecutionRecordResponse>(
        `/api/broker-gateway/orders/${encodeURIComponent(
          orderId,
        )}/manual-execution`,
        {
          method: 'POST',
          body: {
            actor: 'web',
            fill_price,
            quantity,
            fee,
            tax,
            transfer_fee,
            preview_fingerprint,
            operator_note,
          },
        },
      ),
  });
}
