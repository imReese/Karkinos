import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

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
    run_id: string | null;
    order_intent_count: number;
    simulated_order_count: number;
    simulated_fill_count: number;
    divergence_reviewed_count: number;
    divergence_status: string;
    next_manual_review_step: string;
    last_run_at: string | null;
    orders: Array<{
      order_id: string | null;
      symbol: string | null;
      status: string | null;
      divergence_status: string | null;
    }>;
  };
  limitations: string[];
};

export function useOperationsTodayQuery() {
  return useQuery({
    queryKey: ['operations', 'today'],
    queryFn: () =>
      apiClient<OperationsTodayResponse>('/api/operations/today'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
