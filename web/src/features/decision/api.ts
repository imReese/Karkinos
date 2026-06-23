import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

const DECISION_REFETCH_MS = 15_000;

function liveRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return DECISION_REFETCH_MS;
}

export type DecisionAction =
  | 'buy'
  | 'sell'
  | 'hold'
  | 'rebalance'
  | 'no_action'
  | 'review_required';

export type DecisionLane = 'daily' | 'intraday';

export type DecisionWorkflowTask = {
  id: string;
  priority: number;
  status: string;
  title?: string;
  description?: string;
  required_actions: string[];
  blocking_reasons: string[];
  evidence?: Record<string, unknown>;
};

export type DecisionSummary = {
  candidate_count: number;
  risk_blocked_count: number;
  ready_for_manual_confirmation_count: number;
  excluded_daily_count?: number;
  workflow_tasks?: DecisionWorkflowTask[];
  portfolio?: {
    status: string;
    cash: number;
    position_count: number;
    symbols: string[];
    total_market_value: number;
    total_equity: number;
  };
  market_data?: {
    source_health: string;
    quote_count: number;
    live_quote_count: number;
    stale_quote_count: number;
    missing_symbols: string[];
    latest_quote_timestamp: string | null;
    has_persistent_cache: boolean;
  };
  action_tasks?: {
    total_count: number;
    pending_count: number;
    deferred_count: number;
    symbols: string[];
  };
  audit?: {
    signal_count: number;
    journal_entry_count: number;
    risk_checked_count: number;
    risk_blocked_count: number;
  };
  account_truth?: AccountTruthGateEvidence;
  strategy_attribution?: StrategyAttributionGateEvidence;
};

export type AccountTruthGateEvidence = {
  gate_status: string;
  score?: number | null;
  has_evidence?: boolean;
  unresolved_mismatch_count?: number;
  required_actions?: string[];
  blocking_reasons?: string[];
  limitations?: string[];
  components?: Record<string, { status?: string; reason?: string }>;
  data_freshness_status?: string;
};

export type StrategyAttributionGateEvidence = {
  gate_status: string;
  strategy_id?: string | null;
  assignment_status?: string;
  attribution_status?: string;
  contribution_status?: string;
  has_evidence?: boolean;
  signal_count?: number;
  order_count?: number;
  fill_count?: number;
  linked_fill_count?: number;
  net_contribution?: number | null;
  required_actions?: string[];
  blocking_reasons?: string[];
  limitations?: string[];
};

export type DecisionCandidate = {
  action_id: number | null;
  action: DecisionAction;
  symbol: string;
  asset_class: string | null;
  title: string | null;
  detail: string | null;
  urgency: string | null;
  target_weight: number | null;
  price: number | null;
  risk_gate_status: string;
  manual_confirmation_required: boolean;
  manual_confirmation_status: string;
  evidence: {
    strategy: { strategy_id: string | null };
    signal: {
      id: number | string | null;
      timestamp: string | null;
      strategy_id: string | null;
      symbol: string | null;
      target_weight: number | null;
    };
    risk_gate: {
      status: string;
      decision_id: string | number | null;
      passed: boolean | null;
      severity: string | null;
      reasons: string[];
    };
    after_cost_oos_validation: {
      status: string;
      strategy_id?: string | null;
      backtest_result_id?: number | null;
      has_after_cost_report?: boolean;
      has_out_of_sample_validation?: boolean;
      missing_requirements?: string[];
      after_cost?: Record<string, unknown>;
      oos_validation?: Record<string, unknown>;
      cost_summary?: Record<string, unknown>;
      limitations?: string[];
      reason?: string;
    };
    data_freshness: {
      status: string;
      quote_timestamp?: string | null;
      quote_source?: string | null;
      price?: number | null;
      stale_reason?: string | null;
      reason?: string;
    };
    paper_shadow?: {
      status: string;
      has_evidence?: boolean;
      execution_mode?: string | null;
      order_id?: string | number | null;
      required_actions?: string[];
      blocking_reasons?: string[];
      manual_confirmation_status?: string;
    };
    cost_impact?: {
      status: string;
      source?: string;
      total_commission?: number | null;
      total_slippage?: number | null;
      cost_summary?: Record<string, unknown>;
    };
    uncertainty?: {
      status: string;
      factors?: string[];
    };
    certainty?: {
      status: string;
      posture?: string;
      required_actions?: string[];
      uncertain_reasons?: string[];
    };
    manual_confirmation: {
      required: boolean;
      status: string;
      reason?: string | null;
    };
    journal: {
      has_journal_entry: boolean;
      latest_event_type: string | null;
      latest_event_source: string | null;
      latest_event_ref: string | number | null;
    };
    account_truth?: AccountTruthGateEvidence;
    strategy_attribution?: StrategyAttributionGateEvidence;
  };
};

export type DecisionResponse = {
  lane: DecisionLane;
  decision_date: string;
  generated_at: string;
  cadence?: string;
  decision: DecisionAction;
  requires_manual_confirmation: boolean;
  summary: DecisionSummary;
  candidates: DecisionCandidate[];
  excluded_daily_symbols?: string[];
  no_action_reasons: string[];
  limitations: string[];
};

export type SignalResponse = {
  id: number | null;
  timestamp: string;
  strategy_id: string;
  symbol: string;
  direction: string;
  target_weight: number;
  price: number | null;
  asset_class: string;
};

export type ActionCard = {
  id: number | null;
  source_signal_id: number | null;
  symbol: string;
  title: string;
  detail: string;
  direction: string;
  urgency: string;
  target_weight: number;
  price: number | null;
  strategy_id: string;
  timestamp: string;
  asset_class: string;
  status: string;
  risk_decision_id: string | null;
  risk_gate_passed: boolean | null;
  risk_gate_status: string;
  risk_gate_severity: string | null;
  risk_gate_reasons: string[];
  manual_confirmation_required: boolean;
  manual_confirmation_status: string;
  manual_confirmation_reason: string;
};

export type SignalJournalEntry = {
  signal: SignalResponse;
  action_task: ActionCard | null;
  risk_decision: {
    decision_id: string;
    passed: boolean;
    symbol: string;
    side: string;
    severity: string;
    timestamp: string;
    reasons: string[];
  } | null;
  review: {
    signal_id: number;
    reviewed_at: string;
    user_decision: string;
    outcome: string;
    review_notes: string;
    reviewer: string | null;
  } | null;
  latest_event: {
    event_type: string;
    timestamp: string;
    source: string;
    source_ref: string | null;
  } | null;
};

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

function decisionQuery(path: string, key: readonly string[]) {
  return useQuery({
    queryKey: key,
    queryFn: () => apiClient<DecisionResponse>(path),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useTodayDecisionQuery() {
  return decisionQuery('/api/decision/today', ['decision', 'today']);
}

export function useIntradayDecisionQuery() {
  return decisionQuery('/api/decision/intraday', ['decision', 'intraday']);
}

export function useSignalActionsQuery() {
  return useQuery({
    queryKey: ['signal-actions'],
    queryFn: () => apiClient<ActionCard[]>('/api/signals/actions'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useSignalJournalQuery() {
  return useQuery({
    queryKey: ['signal-journal'],
    queryFn: () => apiClient<SignalJournalEntry[]>('/api/signals/journal'),
    staleTime: 10_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useCreateManualOrderFromActionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      actionId: number;
      quantity: number;
      price?: number | null;
      order_type?: string;
      note?: string;
    }) =>
      postJson(`/api/trading/actions/${payload.actionId}/manual-order`, {
        quantity: payload.quantity,
        price: payload.price ?? null,
        order_type: payload.order_type ?? 'market',
        note: payload.note ?? 'Prepared from Decision action queue.',
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['signal-actions'] }),
        queryClient.invalidateQueries({ queryKey: ['signal-journal'] }),
        queryClient.invalidateQueries({ queryKey: ['trading-manual-orders'] }),
      ]);
    },
  });
}
