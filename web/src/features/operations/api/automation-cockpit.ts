import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../../shared/api/client';
import type { ControlledExecutionOperatorView } from './controlled-session';
import type {
  DailyCandidateFinancialPreflight,
  DailyCandidateRuntimeStatus,
  DailyCandidateTrial,
} from './daily-candidate';
import { liveOperationsRefetchInterval } from './refetch-policy';

export type AutomationCockpitResponse = {
  schema_version: 'karkinos.automation_cockpit.v4';
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
  daily_candidate_trial: DailyCandidateTrial;
  daily_candidate_runtime: DailyCandidateRuntimeStatus;
  daily_candidate_financial_preflight: DailyCandidateFinancialPreflight;
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
  connector_registrations?: Array<{
    connector_id: string;
    connector_type: string;
    registration_status: string;
    provider_contact_performed: boolean;
    explicit_ingestion_required: boolean;
    can_submit_orders: boolean;
    can_cancel_orders: boolean;
  }>;
  current_per_order_reviews: AutomationCurrentPerOrderReviews;
  controlled_execution?: ControlledExecutionOperatorView;
  limitations: string[];
};

export type AutomationCurrentPerOrderReviewCandidate = {
  order_id: string;
  symbol: string;
  side: string;
  quantity: string;
  review_status: string;
  review_ready: boolean;
  review_blockers: string[];
  evidence_resolution_status?: string;
  confirmation_status?: string;
  authorizes_execution: false;
};

export type AutomationCurrentPerOrderReviews = {
  schema_version: 'karkinos.automation_current_per_order_reviews.v1';
  source_schema_version: string;
  status:
    | 'unavailable'
    | 'blocked_source'
    | 'review_ready'
    | 'blocked_review'
    | 'no_current_candidates';
  candidate_count: number;
  review_ready_count: number;
  blocked_review_count: number;
  source_truncated: boolean;
  next_operator_action: string;
  primary_candidate: AutomationCurrentPerOrderReviewCandidate | null;
  candidates: AutomationCurrentPerOrderReviewCandidate[];
  source_blockers: string[];
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  runtime_connector_query_performed: false;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  does_not_mutate_risk: true;
  does_not_mutate_kill_switch: true;
  does_not_change_capital_authority: true;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  authorizes_execution: false;
};

export function useAutomationCockpitQuery(enabled = true) {
  return useQuery({
    queryKey: ['automation', 'cockpit'],
    queryFn: () =>
      apiClient<AutomationCockpitResponse>('/api/automation/cockpit'),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
