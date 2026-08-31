import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../../shared/api/client';
import type {
  DailyOperationsSummary,
  DailyTradingPlanBlockerSummary,
} from '../../../shared/contracts/daily-operations';
import type {
  BrokerAdapterReadiness,
  ControlledPerOrderPilotReadiness,
} from './broker-release';
import type {
  PaperShadowDivergenceSummary,
  PaperShadowManualHandoff,
  PaperShadowReviewQueueItem,
} from './paper-shadow';
import { liveOperationsRefetchInterval } from './refetch-policy';
import type { OperationsStatus } from './status';

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

export type OperationsAttentionItem = {
  schema_version: 'karkinos.operations_attention_item.v1';
  subsystem_id: string;
  status: OperationsStatus;
  target: string;
  evidence: {
    status: string;
    observed_at: string | null;
  };
  next_action: string;
  resolution_condition: string;
  task_fingerprint: string;
  manual_acknowledgement_clears_status: false;
  read_only_projection: true;
  provider_contacted: false;
  database_writes_performed: false;
  authorizes_execution: false;
};

export type CiticSourceFollowUp = {
  schema_version: 'karkinos.account_truth.citic_source_follow_up.v1';
  status: string;
  subsystem_status: OperationsStatus;
  pending_source_count: number;
  scanned_source_count: number;
  intake_scan_truncated: boolean;
  count_complete: boolean;
  blockers: string[];
  required_evidence: string[];
  reviewed_query_window_source_count: number;
  unreviewed_query_window_source_count: number;
  query_window_reviews_complete: boolean;
  query_window_batch_integrity_status:
    'not_available' | 'partial' | 'clear' | 'blocked';
  query_window_batch_assessment_fingerprint: string;
  query_window_gap_calendar_day_count: number;
  query_window_overlap_calendar_day_count: number;
  query_window_integrity_clear: boolean;
  error_codes: string[];
  latest_reviewed_at: string | null;
  evidence_fingerprint: string;
  next_manual_action: string;
  limitations: string[];
  persisted_facts_only: true;
  source_paths_included: false;
  source_names_included: false;
  transaction_details_included: false;
  provider_contacted: false;
  database_writes_performed: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  authorizes_execution: false;
  changes_capital_authority: false;
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
  attention_items?: OperationsAttentionItem[];
  daily_operations: DailyOperationsSummary;
  broker_adapter_readiness?: BrokerAdapterReadiness;
  citic_source_follow_up?: CiticSourceFollowUp;
  controlled_per_order_pilot_readiness?: ControlledPerOrderPilotReadiness;
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

export function useOperationsTodayQuery(enabled = true) {
  return useQuery({
    queryKey: ['operations', 'today'],
    queryFn: () => apiClient<OperationsTodayResponse>('/api/operations/today'),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
