import { useQuery } from '@tanstack/react-query';

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

export type DecisionSummary = {
  candidate_count: number;
  risk_blocked_count: number;
  ready_for_manual_confirmation_count: number;
  excluded_daily_count?: number;
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
