import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';
import type { DailyTradingPlanBlockerSummary } from '../decision/api';

const OPERATIONS_REFETCH_MS = 15_000;

function liveRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return OPERATIONS_REFETCH_MS;
}

export type OperationsStatus =
  | 'healthy'
  | 'pass'
  | 'manual_action_required'
  | 'blocked'
  | 'degraded'
  | 'skipped'
  | 'no_action';

export type OperationsSubsystem = {
  id: string;
  status: OperationsStatus;
  tone: 'success' | 'warning' | 'danger' | 'neutral';
  target: string;
  last_run_at: string | null;
  next_action: string;
  limitations: string[];
  detail_status: string;
};

export type PaperShadowCostSummary = {
  estimated_total_fee?: number | string | null;
  simulated_fee_tax_cost?: number | string | null;
  simulated_slippage_cost?: number | string | null;
  simulated_total_execution_cost?: number | string | null;
  fee_rule_ids?: string[];
  fill_count_with_cost_evidence?: number;
};

export type PaperShadowExpectedStrategyBehavior = {
  source_decision?: string | null;
  expected_order_count?: number | null;
  symbols?: string[];
  side_counts?: Record<string, number>;
  strategy_refs?: string[];
  risk_refs?: string[];
  signal_refs?: string[];
  risk_gate_status_counts?: Record<string, number>;
  manual_confirmation_status_counts?: Record<string, number>;
  submission_status_counts?: Record<string, number>;
};

export type PaperShadowExecutionComparison = {
  matched_order_count?: number | null;
  missing_order_intent_refs?: string[];
  diverged_order_refs?: string[];
  failed_order_refs?: string[];
  simulated_status_counts?: Record<string, number>;
  fill_count_by_order?: Record<string, number>;
  filled_quantity_by_order?: Record<string, number | string>;
  remaining_quantity_by_order?: Record<string, number | string>;
};

export type PaperShadowMarketSymbolContext = {
  symbol?: string | null;
  expected_price?: number | string | null;
  price_basis?: string | null;
  simulated_fill_prices?: Array<number | string>;
  simulated_slippage_cost?: number | string | null;
};

export type PaperShadowRealizedMarketContext = {
  symbol_count?: number | null;
  price_basis_counts?: Record<string, number>;
  symbols?: PaperShadowMarketSymbolContext[];
};

export type PaperShadowDivergenceSummary = {
  status?: string;
  expected_strategy_behavior?: PaperShadowExpectedStrategyBehavior;
  execution_comparison?: PaperShadowExecutionComparison;
  realized_market_context?: PaperShadowRealizedMarketContext;
  cost_summary?: PaperShadowCostSummary;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
  [key: string]: unknown;
};

export type PaperShadowReviewQueueItem = {
  review_id: string;
  order_intent_ref?: string | null;
  order_id?: string | null;
  symbol?: string | null;
  status: string;
  divergence_status: string;
  severity: 'info' | 'warning' | 'danger' | string;
  required_action: string;
  reason: string;
  filled_quantity?: string | number | null;
  remaining_quantity?: string | number | null;
  strategy_refs?: string[];
  risk_refs?: string[];
  signal_refs?: string[];
  evidence_refs?: string[];
  account_truth?: {
    gate_status?: string | null;
    has_evidence?: boolean;
    blocking_reasons?: string[];
  };
  risk_gate_status?: string | null;
  manual_confirmation_status?: string | null;
  submission_status?: string | null;
  cash_status?: string | null;
  constraint_status_counts?: Record<string, number>;
  cost_evidence?: {
    estimated_gross_amount?: string | number | null;
    estimated_total_fee?: string | number | null;
    simulated_fee_tax_cost?: string | number | null;
    simulated_slippage_cost?: string | number | null;
    fee_rule_id?: string | null;
  };
  market_context?: {
    price_basis?: string | null;
    expected_price?: string | number | null;
    simulated_fill_prices?: Array<string | number>;
  };
  terminal_status?: string | null;
  terminal_reason?: string | null;
  terminal_oms_transition_ref?: string | null;
  oms_status_path?: string[];
  oms_transition_refs?: string[];
  oms_transitions?: Array<{
    sequence?: string | number | null;
    from_status?: string | null;
    to_status?: string | null;
    source?: string | null;
    reason?: string | null;
    filled_quantity?: string | number | null;
    does_not_submit_broker_order?: boolean;
    does_not_mutate_production_ledger?: boolean;
  }>;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
};

export type PaperShadowManualHandoff = {
  ready: boolean;
  status: string;
  blockers?: string[];
  required_actions?: string[];
  review_queue_count?: number;
  highest_severity?: string | null;
  review_status?: string | null;
  reviewed_at?: string | null;
  reviewer?: string | null;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
};

export type OperationsSchedulerSummary = {
  status: string;
  run_id: string | null;
  run_type: string;
  run_date: string;
  execution_mode: string;
  last_run_at: string | null;
  input_fingerprint?: string | null;
  idempotency_key?: string | null;
  input_snapshot?: Record<string, unknown>;
  retry_state?: Record<string, unknown>;
  error?: Record<string, unknown>;
  suggested_action?: string;
  requires_manual_review?: boolean;
  retry_recommended?: boolean;
  broker_submission_enabled: boolean;
  does_not_submit_broker_order: boolean;
  does_not_mutate_production_ledger?: boolean;
  limitations?: string[];
};

export type OperationsExecutionReconciliationSummary = {
  status: string;
  open_item_count: number;
  manual_execution_review_count: number;
  next_review_step: string;
  last_open_item_at?: string | null;
  detail_status?: string;
  first_open_item?: {
    order_id?: string | null;
    item_status?: string | null;
    suggested_action?: string | null;
    detail?: string | null;
    manual_execution_evidence_summary?: {
      preview_fingerprint?: string | null;
      submitted_to_broker?: boolean | null;
      does_not_mutate_oms?: boolean | null;
      does_not_mutate_production_ledger?: boolean | null;
      [key: string]: unknown;
    };
  } | null;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_oms?: boolean;
  does_not_mutate_production_ledger?: boolean;
  limitations?: string[];
};

export type OperationsTodayResponse = {
  schema_version: 'karkinos.operations_today.v1';
  operations_date: string;
  generated_at: string;
  conclusion_status: OperationsStatus;
  primary_target: string;
  health: {
    total: number;
    pass: number;
    degraded: number;
    blocked: number;
    manual_action_required: number;
    skipped: number;
  };
  subsystems: OperationsSubsystem[];
  daily_plan: {
    candidate_pool_count: number;
    manual_ready_count: number;
    blocked_count: number;
    blocker_summary?: DailyTradingPlanBlockerSummary[];
    order_intent_count: number;
    conclusion_status: string;
  };
  paper_shadow: {
    status:
      | 'not_required'
      | 'not_run'
      | 'review_required'
      | 'within_expectations'
      | 'diverged'
      | string;
    effective_status?: string;
    run_id: string | null;
    input_fingerprint?: string | null;
    input_snapshot?: Record<string, unknown>;
    evidence_refs?: string[];
    order_intent_count: number;
    simulated_order_count: number;
    simulated_fill_count: number;
    divergence_reviewed_count: number;
    divergence_status: string;
    review_status?: string | null;
    reviewed_at?: string | null;
    reviewer?: string | null;
    next_manual_review_step: string;
    last_run_at: string | null;
    limitations?: string[];
    review_queue?: PaperShadowReviewQueueItem[];
    manual_handoff?: PaperShadowManualHandoff;
    divergence_summary?: PaperShadowDivergenceSummary;
    orders: Array<{
      order_id: string | null;
      symbol: string | null;
      status: string | null;
      divergence_status: string | null;
    }>;
  };
  scheduler?: OperationsSchedulerSummary;
  execution_reconciliation?: OperationsExecutionReconciliationSummary;
  limitations: string[];
};

export type PaperShadowRunResponse = {
  run_id: string;
  status: string;
  input_fingerprint?: string;
  input_snapshot?: Record<string, unknown>;
  order_intent_count: number;
  simulated_order_count: number;
  simulated_fill_count: number;
  divergence_status: string;
  next_manual_review_step: string;
  limitations: string[];
  review_queue?: PaperShadowReviewQueueItem[];
  does_not_submit_broker_order: boolean;
  does_not_mutate_production_ledger: boolean;
};

export type PaperShadowRunReviewResponse = {
  run_id: string;
  status: string;
  divergence_status: string;
  review_status?: string | null;
  reviewed_at?: string | null;
  reviewer?: string | null;
  next_manual_review_step: string;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
};

export type AutomationCockpitResponse = {
  schema_version: 'karkinos.automation_cockpit.v1';
  broker_submission_enabled: boolean;
  automation_status: {
    schema_version: 'karkinos.automation_status.v1';
    mode?: string;
    default_execution_mode?: string;
    broker_submission_enabled: boolean;
    manual_confirmation_required: boolean;
    kill_switch_enabled: boolean;
    next_action?: string;
    policies?: Record<string, unknown>;
    latest_runs?: unknown[];
    limitations?: string[];
  };
  gateways: Array<{
    gateway_id: string;
    status: string;
    mode: string;
    capabilities?: string[];
    limitations?: string[];
  }>;
  open_alert_count: number;
  open_alerts: Array<{
    id: number;
    alert_type: string;
    severity: string;
    status: string;
    title: string;
    detail: string;
    created_at: string;
    payload?: Record<string, unknown>;
  }>;
  recent_runs: Array<{
    run_id: string;
    run_type: string;
    mode: string;
    status: string;
    started_at: string;
    finished_at?: string | null;
    reason?: string | null;
  }>;
  promotion_states: Array<{
    strategy_id: string;
    stage: string;
    gate_status?: string;
    live_like_enabled?: boolean;
    missing_requirements?: string[];
    backtest_result_id?: number | null;
    status?: string;
    created_at?: string;
    updated_at: string;
    payload?: Record<string, unknown>;
    lifecycle?: {
      schema_version?: string;
      stage?: string;
      supported_stages?: string[];
      audit_only?: boolean;
      does_not_authorize_execution?: boolean;
      broker_submission_enabled?: boolean;
      manual_confirmation_required_for_live_like?: boolean;
      disabled_stages?: string[];
      terminal?: boolean;
      allowed_operator_actions?: string[];
    };
  }>;
  execution_reconciliation_open_items: Array<{
    item_id: number;
    order_id: string | null;
    status: string;
    recommended_action: string;
  }>;
  runtime_connector_snapshots?: BrokerRuntimeConnectorSnapshot[];
  limitations: string[];
};

export type BrokerRuntimeConnectorSnapshot = {
  schema_version?: string;
  gateway_id: 'read_only_connector' | string;
  status: string;
  query_scope: string;
  connector_id: string;
  account_alias?: string | null;
  captured_at?: string | null;
  connector_health?: {
    status?: string;
    raw_status?: string;
    message?: string | null;
    checked_at?: string | null;
  };
  cash_balance?: {
    currency?: string | null;
    balance?: string | number | null;
    available?: string | number | null;
  };
  position_count?: number;
  positions?: Array<Record<string, unknown>>;
  order_count?: number;
  orders?: Array<Record<string, unknown>>;
  fill_count?: number;
  fills?: Array<Record<string, unknown>>;
  capabilities?: BrokerConnectorCapabilities;
  submitted_to_broker?: boolean;
  can_submit_orders?: boolean;
  stores_credentials?: boolean;
  does_not_mutate_oms?: boolean;
  does_not_mutate_production_ledger?: boolean;
  limitations?: string[];
};

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
  kill_switch_enabled: boolean;
  kill_switch_reason?: string | null;
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

export type BrokerConnectorHealth = {
  schema_version: 'karkinos.broker_connector_health.v1';
  connector_id: string;
  connector_type: string;
  enabled: boolean;
  status: string;
  message?: string | null;
  account_alias?: string | null;
  capability_scope?: string | null;
  capabilities?: BrokerConnectorCapabilities;
  requires_credentials?: boolean;
  stores_credentials?: boolean;
  submitted_to_broker?: boolean;
  limitations?: string[];
};

export type BrokerConnectorHealthResponse = {
  schema_version: 'karkinos.broker_connector_health_list.v1';
  broker_submission_enabled: boolean;
  connectors: BrokerConnectorHealth[];
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
};

export type ExecutionReconciliationRun = {
  run_id: string;
  run_date?: string;
  status: string;
  item_count: number;
  open_item_count: number;
  created_at?: string;
  payload?: Record<string, unknown>;
  items?: ExecutionReconciliationItem[];
};

export function useOperationsTodayQuery() {
  return useQuery({
    queryKey: ['operations', 'today'],
    queryFn: () => apiClient<OperationsTodayResponse>('/api/operations/today'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useAutomationCockpitQuery() {
  return useQuery({
    queryKey: ['automation', 'cockpit'],
    queryFn: () =>
      apiClient<AutomationCockpitResponse>('/api/automation/cockpit'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerGatewayStatusQuery() {
  return useQuery({
    queryKey: ['broker-gateway', 'status'],
    queryFn: () =>
      apiClient<BrokerGatewayStatusResponse>('/api/broker-gateway/status'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerConnectorHealthQuery() {
  return useQuery({
    queryKey: ['broker-gateway', 'connectors', 'health'],
    queryFn: () =>
      apiClient<BrokerConnectorHealthResponse>(
        '/api/broker-gateway/connectors/health',
      ),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerGatewayAccountFactsQuery() {
  return useQuery({
    queryKey: ['broker-gateway', 'account-facts'],
    queryFn: () =>
      apiClient<BrokerGatewayAccountFactsResponse>(
        '/api/broker-gateway/account-facts',
      ),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBrokerGatewayFillsQuery() {
  return useQuery({
    queryKey: ['broker-gateway', 'fills'],
    queryFn: () =>
      apiClient<BrokerGatewayFillsQueryResponse>(
        '/api/broker-gateway/fills/query',
      ),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
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
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useExecutionReconciliationRunsQuery() {
  return useQuery({
    queryKey: ['execution-reconciliation', 'runs'],
    queryFn: () =>
      apiClient<ExecutionReconciliationRun[]>(
        '/api/execution-reconciliation/runs?limit=5',
      ),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
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
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useRunPaperShadowMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await fetch('/api/operations/paper-shadow/run', {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as PaperShadowRunResponse;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['operations', 'today'],
      });
    },
  });
}

export function useReviewPaperShadowRunMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ runId }: { runId: string }) => {
      const response = await fetch(
        `/api/operations/paper-shadow/runs/${encodeURIComponent(runId)}/review`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            reviewed_at: new Date().toISOString(),
            review_status: 'accepted_for_manual_confirmation',
            review_notes:
              'Operator accepted simulation evidence from the Trading review panel.',
            reviewer: 'web',
          }),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as PaperShadowRunReviewResponse;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({ queryKey: ['trading-order-facts'] }),
      ]);
    },
  });
}
