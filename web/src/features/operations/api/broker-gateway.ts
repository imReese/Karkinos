import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../../shared/api/client';
import { liveOperationsRefetchInterval } from './refetch-policy';

export type BrokerGatewayCapability = {
  gateway_id: string;
  display_name?: string | null;
  status: string;
  can_preview_orders?: boolean;
  can_export_tickets?: boolean;
  can_dry_run_orders?: boolean;
  can_submit_orders?: boolean;
  can_cancel_orders?: boolean;
  can_query_orders?: boolean;
  can_query_fills?: boolean;
  can_query_positions?: boolean;
  can_query_cash?: boolean;
  blockers?: string[];
  blocked_reason?: string | null;
  limitations?: string[];
};

export type BrokerGatewayStatusResponse = {
  schema_version: 'karkinos.broker_gateway_status.v1';
  broker_submission_enabled: boolean;
  kill_switch_status?: 'pass' | 'blocked' | 'unavailable';
  kill_switch_enabled: boolean | null;
  kill_switch_reason?: string | null;
  kill_switch_updated_at?: string | null;
  kill_switch_evidence_available?: boolean;
  kill_switch_blockers?: string[];
  controlled_bridge_policy?: {
    schema_version: 'karkinos.controlled_broker_bridge_policy.v1';
    policy_id: string;
    status: string;
    enabled: boolean;
    broker_submission_enabled: boolean;
    live_submission_available: boolean;
    automation_allowed: boolean;
    per_order_confirmation_required: boolean;
    allowed_connector_ids?: string[];
    allowed_account_aliases?: string[];
    allowed_strategy_ids?: string[];
    allowed_symbols?: string[];
    required_gates?: string[];
    blockers?: string[];
    limitations?: string[];
  };
  gateways: BrokerGatewayCapability[];
};

export type BrokerConnectorCapabilities = {
  can_read_health?: boolean;
  can_query_lifecycle_evidence?: boolean;
  can_read_account?: boolean;
  can_read_cash?: boolean;
  can_read_positions?: boolean;
  can_read_orders?: boolean;
  can_read_fills?: boolean;
  can_preview_orders?: boolean;
  can_export_tickets?: boolean;
  can_dry_run_orders?: boolean;
  can_submit_orders?: boolean;
  can_cancel_orders?: boolean;
};

export type BrokerLifecycleEvidenceHealth = {
  schema_version: 'karkinos.broker_lifecycle_evidence_health.v1';
  connector_id: string;
  connector_type: string;
  gateway_id: string;
  provider?: string | null;
  providers?: string[];
  registered: boolean;
  registration_status: string;
  enabled: boolean;
  status: string;
  message?: string | null;
  blockers?: string[];
  account_aliases?: string[];
  capability_scope?: string | null;
  capabilities?: BrokerConnectorCapabilities;
  evidence_source?: string;
  evidence_store_status?: string;
  latest_collector_runs?: Array<Record<string, unknown>>;
  provider_contact_performed: boolean;
  reads_persisted_facts_only: boolean;
  explicit_ingestion_required: boolean;
  third_party_adapter_review_required?: boolean;
  default_registered?: boolean;
  can_submit_orders?: boolean;
  can_cancel_orders?: boolean;
  requires_credentials?: boolean;
  stores_credentials?: boolean;
  submitted_to_broker?: boolean;
  limitations?: string[];
};

export type BrokerConnectorHealthResponse = {
  schema_version: 'karkinos.broker_connector_health_list.v2';
  broker_submission_enabled: boolean;
  provider_contact_performed: boolean;
  reads_persisted_facts_only: boolean;
  connectors: BrokerLifecycleEvidenceHealth[];
};

export type BrokerGatewayAccountFactsResponse = {
  schema_version: 'karkinos.broker_gateway_status.v1';
  gateway_id: 'staged_broker_evidence' | string;
  status: string;
  query_scope: string;
  submitted_to_broker: boolean;
  can_submit_orders: boolean;
  source_import_run_ids?: string[];
  broker_event_count: number;
  cash_balances: Array<Record<string, unknown>>;
  positions: Array<Record<string, unknown>>;
  fills: Array<Record<string, unknown>>;
  limitations?: string[];
};

export type BrokerGatewayFillsQueryResponse = {
  schema_version: 'karkinos.broker_gateway.v1';
  gateway_id: 'staged_broker_evidence' | string;
  status: string;
  query_scope: string;
  submitted_to_broker: boolean;
  can_submit_orders: boolean;
  symbol?: string | null;
  source_import_run_ids?: string[];
  broker_event_count: number;
  fill_count: number;
  fills: Array<Record<string, unknown>>;
  limitations?: string[];
};

export type BrokerGatewayOrderQueryResponse = {
  schema_version: 'karkinos.broker_gateway.v1';
  gateway_id: 'manual_ticket' | string;
  status: string;
  query_scope: string;
  submitted_to_broker: boolean;
  can_submit_orders: boolean;
  oms_order: Record<string, unknown> | null;
  gateway_event_count: number;
  gateway_events: Array<Record<string, unknown>>;
  staged_broker_fill_count: number;
  staged_broker_fills: Array<Record<string, unknown>>;
  limitations?: string[];
};

export type ExecutionReconciliationItem = {
  item_id?: number;
  order_id: string | null;
  item_status?: string;
  status?: string;
  suggested_action?: string;
  recommended_action?: string;
  gateway_event_count?: number;
  broker_event_count?: number;
  detail?: string;
  payload?: Record<string, unknown>;
  payload_status?: 'valid' | 'missing' | 'invalid';
};

export type ExecutionReconciliationRun = {
  run_id: string;
  run_date?: string;
  status: string;
  item_count: number;
  open_item_count: number;
  created_at?: string;
  payload?: Record<string, unknown>;
  payload_status?: 'valid' | 'missing' | 'invalid';
  items?: ExecutionReconciliationItem[];
};

export function useBrokerGatewayStatusQuery(enabled = true) {
  return useQuery({
    queryKey: ['broker-gateway', 'status'],
    queryFn: () =>
      apiClient<BrokerGatewayStatusResponse>('/api/broker-gateway/status'),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerConnectorHealthQuery(enabled = true) {
  return useQuery({
    queryKey: ['broker-gateway', 'connectors', 'health'],
    queryFn: () =>
      apiClient<BrokerConnectorHealthResponse>(
        '/api/broker-gateway/connectors/health',
      ),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerGatewayAccountFactsQuery(enabled = true) {
  return useQuery({
    queryKey: ['broker-gateway', 'account-facts'],
    queryFn: () =>
      apiClient<BrokerGatewayAccountFactsResponse>(
        '/api/broker-gateway/account-facts',
      ),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerGatewayFillsQuery(enabled = true) {
  return useQuery({
    queryKey: ['broker-gateway', 'fills'],
    queryFn: () =>
      apiClient<BrokerGatewayFillsQueryResponse>(
        '/api/broker-gateway/fills/query',
      ),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerGatewayOrderQuery(orderId: string | null | undefined) {
  return useQuery({
    queryKey: ['broker-gateway', 'orders', orderId],
    queryFn: () =>
      apiClient<BrokerGatewayOrderQueryResponse>(
        `/api/broker-gateway/orders/${encodeURIComponent(String(orderId))}/query`,
      ),
    enabled: Boolean(orderId),
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useExecutionReconciliationRunsQuery(enabled = true) {
  return useQuery({
    queryKey: ['execution-reconciliation', 'runs'],
    queryFn: () =>
      apiClient<ExecutionReconciliationRun[]>(
        '/api/execution-reconciliation/runs?limit=5',
      ),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useExecutionReconciliationRunDetailQuery(
  runId: string | null | undefined,
) {
  return useQuery({
    queryKey: ['execution-reconciliation', 'runs', runId],
    queryFn: () =>
      apiClient<ExecutionReconciliationRun>(
        `/api/execution-reconciliation/runs/${encodeURIComponent(
          String(runId),
        )}`,
      ),
    enabled: Boolean(runId),
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
