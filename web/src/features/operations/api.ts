import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';
import type { DailyOperationsSummary } from '../account/api';
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

export type BrokerAdapterReadinessRelease = {
  release_evidence_ref: string;
  manifest_fingerprint: string;
  manifest_status: string;
  provider: string;
  gateway_id: string;
  account_alias: string;
  collector_id: string;
  collection_modes: string[];
  review_status: string;
  review_id: string;
  reviewed_at?: string | null;
  conformance_status: string;
  conformance_run_id: string;
  conformance_report_fingerprint: string;
  collector_status: string;
  collector_run_id: string;
  collector_updated_at?: string | null;
  status: string;
  next_manual_action: string;
  blockers: string[];
  does_not_authorize_provider_activation: boolean;
};

export type BrokerAdapterReadiness = {
  schema_version: 'karkinos.broker_adapter_readiness.v1';
  status: string;
  subsystem_status: OperationsStatus;
  evidence_store_status: string;
  configured_release_count: number;
  accepted_release_count: number;
  blocked_release_count: number;
  next_manual_action: string;
  latest_release: BrokerAdapterReadinessRelease | null;
  releases: BrokerAdapterReadinessRelease[];
  blockers: string[];
  limitations: string[];
  persisted_facts_only: boolean;
  provider_contacted: boolean;
  adapter_registered: boolean;
  default_registered: boolean;
  broker_submission_enabled: boolean;
  does_not_submit_broker_order: boolean;
  does_not_cancel_broker_order: boolean;
  does_not_mutate_oms: boolean;
  does_not_mutate_production_ledger: boolean;
  does_not_mutate_risk_state: boolean;
  does_not_mutate_kill_switch: boolean;
  does_not_mutate_capital_authority: boolean;
  authorizes_execution: boolean;
};

export type BrokerConnectorSoakPromotionConnector = {
  connector_id: string;
  account_alias: string;
  review_status: string;
  promotion_ready: boolean;
  promotion_blockers: string[];
  owner_acceptance_recorded: boolean;
  account_truth_reconciliation_linked: boolean;
  operational_evidence: {
    status: string;
    selected_trading_day_count: number;
    target_trading_day_count: number;
    phase_coverage: Record<string, string[]>;
    drill_coverage: Record<string, boolean>;
    latest_soak_status: string;
    blockers: string[];
  };
  acceptance?: {
    status?: string;
    acceptance_id?: string | null;
    recorded_at?: string | null;
    operator_identity_verified?: boolean;
    authorizes_execution?: boolean;
  };
  runtime_execution_authority: string;
  broker_submission_enabled: boolean;
  authorizes_execution: boolean;
};

export type BrokerConnectorSoakPromotionStatus = {
  schema_version: 'karkinos.broker_connector_soak_promotion_status.v1';
  contract_status: string;
  connector_count: number;
  connectors: BrokerConnectorSoakPromotionConnector[];
  promotion_ready: boolean;
  promotion_blockers: string[];
  owner_acceptance_recorded: boolean;
  account_truth_reconciliation_linked: boolean;
  runtime_execution_authority: string;
  broker_submission_enabled: boolean;
  automatic_promotion_enabled: boolean;
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
  daily_operations: DailyOperationsSummary;
  broker_adapter_readiness?: BrokerAdapterReadiness;
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
  schema_version: 'karkinos.automation_cockpit.v2';
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

export type ControlledExecutionOperatorSession = {
  session_id: string;
  reservation_id: string;
  authorization_id: string;
  account_alias: string;
  strategy_id: string;
  status: string;
  persisted_status: string;
  is_current_window: boolean;
  effective_at: string;
  expires_at: string;
  authorized_capital: string | null;
  effective_capital_at_risk: string | null;
  remaining_budget: {
    capital_headroom: string | null;
    cash_headroom: string | null;
    turnover_headroom: string | null;
    remaining_order_slots: number;
    reserved_order_count: number;
    admitted_order_count: number;
  };
  allowed_symbols: string[];
  last_order: {
    order_id: string;
    admitted_at: string;
    admission_id: string;
    submission_status: string;
    submit_intent_id: string;
  };
  last_reconciliation: {
    run_id: string;
    run_status: string;
    item_status: string;
    suggested_action: string;
    updated_at: string;
  };
  latest_gate_snapshot: {
    snapshot_id: string;
    status: string;
    observed_at: string;
    blockers: string[];
  };
  pause: {
    status: string;
    pause_event_id: string;
    paused_at: string;
    reasons: string[];
    resume_available: false;
    replacement_review_required: boolean;
  };
  blockers: string[];
  runtime_authentication_evaluated: false;
  runtime_authority_granted: false;
  broker_submission_enabled: false;
};

export type ControlledOrderJourneyStage = {
  key:
    | 'controlled_submission'
    | 'controlled_submission_rejection_review'
    | 'execution_reconciliation'
    | 'terminal_reconciliation_clearance'
    | 'reconciled_ledger_posting'
    | 'append_only_ledger_correction'
    | 'post_ledger_account_truth';
  status: string;
  evidence_id: string;
  complete: boolean;
  required: boolean;
  terminal_status?: string;
  fill_count?: number;
  fill_quantity?: string;
  cancelled_quantity?: string;
  ledger_entry_count?: number;
  post_ledger_cutoff_id?: number;
  reason_code?: string;
  reviewer_id?: string;
  reviewed_at?: string;
  review_fingerprint?: string;
  account_truth_gate_status?: string;
  ledger_coverage_status?: string;
  source_fingerprint?: string;
  captured_at?: string;
  blockers?: string[];
};

export type ControlledOrderJourney = {
  submit_intent_id: string;
  order_id: string;
  broker_order_id: string;
  client_order_id: string;
  gateway_id: string;
  status: string;
  next_operator_action: string;
  attention_required: boolean;
  attention_severity: 'critical' | 'warning' | 'none';
  blocks_new_submissions: boolean;
  prepared_at: string;
  updated_at: string;
  last_recovery_at: string;
  stages: ControlledOrderJourneyStage[];
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_submission_performed: false;
  broker_cancel_performed: false;
  ledger_mutation_performed: false;
  authority_changed: false;
};

export type ControlledExecutionOperatorView = {
  schema_version:
    | 'karkinos.controlled_execution_operator_view.v3'
    | 'karkinos.controlled_execution_operator_view.v4';
  as_of: string;
  status: string;
  next_operator_action: string;
  session_count: number;
  visible_session_count: number;
  current_window_session_count: number;
  blocked_current_session_count: number;
  paused_session_count: number;
  sessions: ControlledExecutionOperatorSession[];
  latest_submission: Record<string, unknown> | null;
  latest_reconciliation: Record<string, unknown> | null;
  order_journey_count: number;
  visible_order_journey_count: number;
  latest_order_journey: ControlledOrderJourney | null;
  recent_order_journeys: ControlledOrderJourney[];
  attention_order_journey_count: number;
  visible_attention_order_journey_count: number;
  attention_queue_truncated: boolean;
  primary_attention_order_journey: ControlledOrderJourney | null;
  attention_order_journeys: ControlledOrderJourney[];
  source_blockers: string[];
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  runtime_connector_query_performed: false;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  authority_issue_enabled: false;
  authority_renew_enabled: false;
  authority_resume_enabled: false;
  automatic_scale_up_enabled: false;
  does_not_mutate_account_truth: true;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  limitations: string[];
};

export type TrustedOperatorIdentity = {
  operator_id: string;
  key_id: string;
  algorithm: 'ed25519';
  enabled: boolean;
  public_key_fingerprint: string;
};

export type OperatorApprovalStatus = {
  schema_version: string;
  contract_status: string;
  trusted_identity_count: number;
  enabled_identity_count: number;
  trusted_identities: TrustedOperatorIdentity[];
  private_key_storage_enabled: false;
  runtime_execution_authority: 'disabled';
  broker_submission_enabled: false;
};

export type ControlledBrokerRecoveryPreview = {
  schema_version: string;
  submit_intent_id: string;
  submit_fingerprint: string;
  recovery_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  gateway_id: string;
  client_order_id: string;
  operator_id: string;
  source_status: string;
  source_result_fingerprint: string;
  prepared_at: string;
  last_recovery_at: string;
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  recovery_wait_remaining_seconds: number;
  gateway_query_capability: boolean;
  required_operator_approval?: {
    action: 'query_unknown_controlled_broker_submission';
    artifact_type: 'controlled_broker_submission_recovery';
    artifact_fingerprint: string;
  };
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_query_performed: false;
  broker_submission_performed: false;
  broker_cancel_performed: false;
  production_ledger_mutated: false;
  authority_changed: false;
};

export type ControlledBrokerRecoveryResult = {
  submit_intent_id: string;
  recovery_fingerprint: string;
  recovery_operator_approval_id: string;
  recovery_claim_id: string;
  status: string;
  broker_order_id: string;
  broker_status: string;
  recovery_query_performed: boolean;
  external_call_performed: boolean;
  recovery_resubmission_enabled: false;
  production_ledger_mutated: false;
};

export type ManualBrokerCancellationSafety = {
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_submission_performed: false;
  broker_cancel_performed: false;
  cancellation_proven: false;
  oms_mutated: false;
  production_ledger_mutated: false;
  risk_state_mutated: false;
  kill_switch_mutated: false;
  capital_authority_changed: false;
  authorizes_submission: false;
  authorizes_cancellation: false;
  releases_submission_interlock: false;
};

export type ManualBrokerCancellationTicketPreview = {
  schema_version: 'karkinos.manual_broker_cancellation_ticket.v1';
  submit_intent_id: string;
  submit_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  provider: string;
  identity: {
    gateway_id: string;
    account_alias: string;
    broker_order_id: string;
    client_order_id: string;
  };
  order: {
    symbol: string;
    side: string;
    asset_class: string;
    order_type: string;
    limit_price: string | null;
    order_quantity: string;
    lifecycle_status: string;
    filled_quantity: string;
    cancelled_quantity: string;
    remaining_quantity: string;
  };
  lifecycle_evidence: {
    observation_id: string;
    evidence_fingerprint: string;
    source_sequence: number;
    captured_at: string;
    source_name: string;
    collector_run_id: string;
    collector_status: string;
  };
  ticket_fingerprint: string;
  generated_at: string;
  status: string;
  ready: boolean;
  blockers: string[];
  required_acknowledgement: 'prepare_manual_broker_cancellation_ticket_without_broker_contact';
  human_steps: string[];
  assumptions: string[];
  risk_impact: string;
  safety: ManualBrokerCancellationSafety;
  limitations: string[];
};

export type ManualBrokerCancellationTicketExport = {
  schema_version: 'karkinos.manual_broker_cancellation_ticket_export.v1';
  status: 'export_ready';
  ticket_fingerprint: string;
  export_fingerprint: string;
  filename: string;
  content_type: 'application/json';
  content: string;
  artifact: Record<string, unknown>;
  export_performed: true;
  safety: ManualBrokerCancellationSafety;
};

export type ControlledBrokerRejectionSafety = {
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_query_performed: false;
  broker_submission_performed: false;
  broker_retry_performed: false;
  broker_cancel_performed: false;
  oms_mutated: false;
  production_ledger_mutated: false;
  account_truth_mutated: false;
  risk_state_mutated: false;
  kill_switch_mutated: false;
  capital_authority_changed: false;
  authorizes_submission: false;
  authorizes_retry: false;
  authorizes_cancellation: false;
  releases_submission_interlock: false;
};

export type ControlledBrokerRejectionEvidencePreview = {
  schema_version: 'karkinos.controlled_broker_rejection_evidence.v1';
  submit_intent_id: string;
  submit_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  identity: {
    gateway_id: string;
    account_alias: string;
    client_order_id: string;
    operator_id: string;
  };
  order: {
    symbol: string;
    side: string;
    asset_class: string;
    quantity: string;
    order_type: string;
    limit_price: string | null;
  };
  rejection_evidence: {
    classification: string;
    intent_status: string;
    broker_status: string;
    result_status: string;
    submitted: boolean | null;
    definitive: boolean;
    error_type: string;
    reason_codes: string[];
    result_fingerprint: string;
    prepared_at: string;
    evidence_as_of: string;
  };
  retry_policy: {
    same_intent_retry_allowed: false;
    same_client_order_id_retry_allowed: false;
    automatic_retry_allowed: false;
    new_order_requires_new_decision_and_all_gates: true;
  };
  review_fingerprint: string;
  generated_at: string;
  status: string;
  ready: boolean;
  blockers: string[];
  required_acknowledgement: 'export_exact_rejection_evidence_without_retry_or_authority_change';
  human_steps: string[];
  assumptions: string[];
  risk_impact: string;
  safety: ControlledBrokerRejectionSafety;
  limitations: string[];
};

export type ControlledBrokerRejectionEvidenceExport = {
  schema_version: 'karkinos.controlled_broker_rejection_evidence_export.v1';
  status: 'export_ready';
  review_fingerprint: string;
  export_fingerprint: string;
  filename: string;
  content_type: 'application/json';
  content: string;
  artifact: Record<string, unknown>;
  export_performed: true;
  safety: ControlledBrokerRejectionSafety;
};

export type ControlledBrokerRejectionReview = {
  schema_version: 'karkinos.controlled_broker_rejection_review.v1';
  review_id: string;
  review_fingerprint: string;
  submit_intent_id: string;
  submit_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  result_fingerprint: string;
  identity: {
    gateway_id: string;
    account_alias: string;
    client_order_id: string;
    operator_id: string;
  };
  reviewer_id: string;
  disposition: 'acknowledged_no_retry';
  rejection_classification: string;
  evidence_as_of: string;
  recorded_at: string;
  operator_acknowledgement: 'record_exact_rejection_review_without_retry_or_authority_change';
  retry_policy: {
    same_intent_retry_allowed: false;
    same_client_order_id_retry_allowed: false;
    automatic_retry_allowed: false;
    new_order_requires_new_decision_and_all_gates: true;
  };
  status: 'recorded' | 'already_recorded';
  reused: boolean;
  review_recorded: true;
  record_performed: boolean;
  safety: ControlledBrokerRejectionSafety;
  limitations: string[];
};

export type ControlledSubmissionClearanceFill = {
  fill_id: string;
  broker_event_id: string;
  account_truth_import_run_id: string;
  timestamp: string;
  symbol: string;
  side: string;
  asset_class: string;
  fill_price: string;
  fill_quantity: string;
  fee: string;
  tax: string;
  transfer_fee: string;
  provider_name: string;
};

export type ControlledSubmissionClearancePreview = {
  schema_version: string;
  clearance_id: string;
  clearance_fingerprint: string;
  submit_intent_id: string;
  order_id: string;
  broker_order_id: string;
  client_order_id: string;
  review_reconciliation_run_id: string;
  broker_evidence_fingerprint: string;
  account_truth_import_run_id: string;
  terminal_status: string;
  terminal_evidence_source: string;
  lifecycle_observation_id: string;
  lifecycle_evidence_fingerprint: string;
  operator_id: string;
  fill_count: number;
  fill_quantity: string;
  cancelled_quantity: string;
  fills: ControlledSubmissionClearanceFill[];
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  required_operator_approval?: {
    action: 'clear_controlled_submission_reconciliation';
    artifact_type: 'controlled_submission_reconciliation_clearance';
    artifact_fingerprint: string;
  };
  interlock_released: false;
  oms_mutated: false;
  production_ledger_mutated: false;
};

export type ControlledSubmissionClearanceResult = {
  clearance_id: string;
  clearance_fingerprint: string;
  submit_intent_id: string;
  order_id: string;
  status: 'cleared';
  terminal_status: string;
  fill_count: number;
  fill_quantity: string;
  cancelled_quantity: string;
  cleared_at: string;
  persisted: true;
  reused: boolean;
  interlock_released: true;
  oms_terminal_status: string;
  real_fills_recorded: boolean;
  terminal_outcome_recorded: true;
  production_ledger_mutated: false;
  automatic_submission_enabled: false;
  strategy_direct_submission_enabled: false;
};

export type ControlledLedgerPostingEntry = {
  fill_id: string;
  broker_event_id: string;
  entry_type: string;
  timestamp: string;
  settled_at: string;
  symbol: string;
  direction: string;
  quantity: string;
  price: string;
  amount: string;
  commission: string;
  gross_amount: string;
  net_cash_impact: string;
  fee_breakdown: {
    commission: string;
    stamp_tax: string;
    transfer_fee: string;
    other_fees: string;
    total_fee: string;
    confirmation_source: string;
  };
  asset_class: string;
  source: string;
  source_ref: string;
  settlement_status: string;
  settlement_source: string;
  account_truth_import_run_id: string;
};

export type ControlledLedgerPostingPreview = {
  schema_version: string;
  posting_id: string;
  posting_fingerprint: string;
  clearance_id: string;
  submit_intent_id: string;
  order_id: string;
  broker_order_id: string;
  terminal_status: string;
  operator_id: string;
  ledger_entry_count: number;
  ledger_entries: ControlledLedgerPostingEntry[];
  pre_valuation_snapshot_id: string;
  pre_ledger_cutoff_id: number;
  account_truth_import_run_id: string;
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  required_operator_approval?: {
    action: 'post_controlled_submission_ledger';
    artifact_type: 'controlled_submission_ledger_posting';
    artifact_fingerprint: string;
  };
  production_ledger_mutated: false;
};

export type CurrentPerOrderDossierCandidate = {
  order_id: string;
  symbol: string;
  side: string;
  asset_class: string;
  quantity: string;
  order_type: string;
  limit_price: string | null;
  oms_status: 'manually_confirmed' | string;
  updated_at: string;
  order_fingerprint: string;
  dossier_fingerprint: string;
  review_status: string;
  review_ready: boolean;
  review_blockers: string[];
  evidence_resolution_status: string;
  confirmation_status: string;
  authorizes_execution: false;
};

export type CurrentPerOrderDossierCandidates = {
  schema_version: string;
  candidate_count: number;
  candidates: CurrentPerOrderDossierCandidate[];
  truncated: boolean;
  selection_contract: 'canonical_manually_confirmed_oms_orders_only';
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

export type CurrentPerOrderDossierPreview = {
  schema_version: string;
  underlying_dossier_schema_version: string;
  order: {
    order_id: string;
    intent_key: string;
    symbol: string;
    side: string;
    asset_class: string;
    quantity: string;
    order_type: string;
    limit_price: string | null;
    source: string;
    source_ref: string;
  };
  order_fingerprint: string;
  dossier_fingerprint: string;
  generated_at: string;
  evidence_resolution: {
    status: string;
    selected_capital_evaluation_event_id: number | null;
    selected_capital_evaluation_recorded_at: string;
    capital_evaluation_input_fingerprint: string;
    prior_batch_reconciliation_fingerprint: string;
    execution_gateway_verification_fingerprint: string;
    blockers: string[];
    scan_limit: number;
    scan_truncated: boolean;
  };
  capital_evaluation: {
    status: string;
    authorization_id: string;
    policy_version: string;
    effective_at: string;
    expires_at: string;
    scope: {
      account_alias: string;
      strategy_id: string;
      symbol: string;
      evidence_connector_id: string;
      execution_gateway_id: string;
    };
    effective_limits: Record<string, string | number>;
    remaining_budget: Record<string, string | number>;
  };
  prior_execution_reconciliation: {
    status: string;
    run_id?: string;
    run_date?: string;
    reconciliation_status?: string;
  };
  execution_gateway_verification: {
    status: string;
    verification_fingerprint: string;
    recorded_at: string;
  };
  kill_switch: {
    status: string;
    enabled: boolean | null;
    reason: string;
  };
  confirmation: {
    status: string;
    confirmation_id: string;
    recorded_at: string;
    operator_label: string;
  };
  review_status: string;
  review_ready: boolean;
  current_evidence_resolved: boolean;
  review_blockers: string[];
  hard_submission_blockers: string[];
  submission_status: 'blocked';
  required_operator_approval: {
    action: 'attest_per_order_dossier';
    artifact_type: 'per_order_dossier';
    artifact_fingerprint: string;
  } | null;
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

export type CurrentPerOrderConfirmation = {
  status: 'recorded_verified_identity' | string;
  confirmation_id: string;
  order_id: string;
  dossier_fingerprint: string;
  operator_label: string;
  operator_identity_verified: boolean;
  authorizes_execution: false;
  broker_submission_enabled: false;
  reused: boolean;
};

export type OperatorApprovalChallenge = {
  challenge_id: string;
  challenge_status: string;
  signing_payload_base64: string;
  operator_id: string;
  key_id: string;
  action: string;
  artifact_type: string;
  artifact_fingerprint: string;
  issued_at: string;
  expires_at: string;
  reused: boolean;
  operator_identity_verified: false;
  authorizes_execution: false;
};

export type VerifiedOperatorApproval = {
  approval_id: string;
  approval_status: 'verified';
  operator_id: string;
  key_id: string;
  action: string;
  artifact_type: string;
  artifact_fingerprint: string;
  expires_at: string;
  operator_identity_verified: true;
  authorizes_execution: false;
  reused: boolean;
};

export type ControlledLedgerPostingResult = {
  posting_id: string;
  posting_fingerprint: string;
  clearance_id: string;
  order_id: string;
  status: 'applied';
  ledger_entry_count: number;
  ledger_entry_ids: number[];
  pre_ledger_cutoff_id: number;
  post_ledger_cutoff_id: number;
  applied_at: string;
  persisted: true;
  reused: boolean;
  production_ledger_mutated: boolean;
  automatic_posting_enabled: false;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  capital_authority_changed: false;
};

export type ControlledLedgerCorrectionReason =
  | 'broker_evidence_superseded'
  | 'duplicate_controlled_posting'
  | 'operator_confirmed_mapping_error';

export type ControlledLedgerCorrectionPositionState = {
  quantity: string;
  available_qty: string;
  frozen_qty: string;
  avg_cost: string;
  realized_pnl: string;
  commission_paid: string;
  broker_displayed_cost_basis: string;
  broker_displayed_unit_cost: string;
  broker_cost_basis_difference: string;
  broker_cost_basis_method: string;
  broker_cost_basis_status: string;
};

export type ControlledLedgerCorrectionPlan = {
  schema_version: string;
  posting_id: string;
  original_ledger_entry_ids: number[];
  effective_at: string;
  symbol: string;
  asset_class: string;
  cash_delta: string;
  total_deposits_delta: '0';
  position_before: ControlledLedgerCorrectionPositionState;
  position_after: ControlledLedgerCorrectionPositionState;
  derivation: 'canonical_replay_excluding_exact_original_posting_entries';
  arbitrary_financial_input_used: false;
};

export type ControlledLedgerCorrectionPreview = {
  schema_version: string;
  action: 'reverse_controlled_submission_ledger_posting';
  posting_id: string;
  posting_fingerprint: string;
  original_ledger_entry_ids: number[];
  original_ledger_entry_fingerprint: string;
  reason_code: ControlledLedgerCorrectionReason;
  operator_id: string;
  account_truth_import_run_id: string;
  pre_valuation_snapshot_id: string;
  pre_valuation_as_of: string;
  pre_valuation_status: string;
  pre_ledger_cutoff_id: number;
  pre_ledger_fingerprint: string;
  plan_fingerprint: string;
  correction_plan: ControlledLedgerCorrectionPlan;
  correction_id: string;
  correction_fingerprint: string;
  generated_at: string;
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  required_operator_approval?: {
    action: 'reverse_controlled_submission_ledger_posting';
    artifact_type: 'controlled_submission_ledger_correction';
    artifact_fingerprint: string;
  };
  production_ledger_mutated: false;
};

export type ControlledLedgerCorrectionResult = {
  correction_id: string;
  correction_fingerprint: string;
  posting_id: string;
  status: 'applied';
  reason_code: ControlledLedgerCorrectionReason;
  original_ledger_entry_ids: number[];
  correction_ledger_entry_id: number;
  pre_ledger_cutoff_id: number;
  post_ledger_cutoff_id: number;
  applied_at: string;
  post_apply_status: 'account_truth_recheck_required';
  persisted: true;
  reused: boolean;
  production_ledger_mutated: true;
  original_ledger_entries_deleted: false;
  automatic_correction_enabled: false;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  capital_authority_changed: false;
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

export function useBrokerConnectorSoakPromotionStatusQuery() {
  return useQuery({
    queryKey: ['broker-soak', 'promotion', 'status'],
    queryFn: () =>
      apiClient<BrokerConnectorSoakPromotionStatus>(
        '/api/automation/broker-soak/promotion/status',
      ),
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

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown };
      if (typeof parsed.detail === 'string') {
        detail = parsed.detail;
      } else if (parsed.detail !== undefined) {
        detail = JSON.stringify(parsed.detail);
      }
    } catch {
      // Preserve the server body when it is not JSON.
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function useOperatorApprovalStatusQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['automation', 'operator-approvals', 'status'],
    queryFn: () =>
      apiClient<OperatorApprovalStatus>(
        '/api/automation/capital-authority/operator-approvals/status',
      ),
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
}

export function useCurrentPerOrderDossierCandidatesQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['automation', 'controlled-bridge', 'current-dossiers'],
    queryFn: () =>
      apiClient<CurrentPerOrderDossierCandidates>(
        '/api/automation/controlled-bridge/dossiers/current?limit=20',
      ),
    enabled,
    staleTime: 2_000,
    refetchOnWindowFocus: true,
  });
}

export function useCurrentPerOrderDossierPreviewMutation() {
  return useMutation({
    mutationFn: ({ orderId }: { orderId: string }) =>
      postJson<CurrentPerOrderDossierPreview>(
        `/api/automation/controlled-bridge/orders/${encodeURIComponent(
          orderId,
        )}/dossier/current/preview`,
      ),
  });
}

export function useCurrentPerOrderDossierApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'attest_per_order_dossier';
      artifact_type: 'per_order_dossier';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useCurrentPerOrderConfirmationMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      orderId: string;
      dossier_fingerprint: string;
      operator_label: string;
      operator_approval_id: string;
      acknowledgement: 'confirm_exact_non_submitting_dossier_for_review';
    }) => {
      const { orderId, ...body } = request;
      return postJson<CurrentPerOrderConfirmation>(
        `/api/automation/controlled-bridge/orders/${encodeURIComponent(
          orderId,
        )}/dossier/current/confirmations`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['automation', 'controlled-bridge', 'current-dossiers'],
        }),
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}

export function useControlledLedgerPostingPreviewMutation() {
  return useMutation({
    mutationFn: ({ clearanceId }: { clearanceId: string }) =>
      postJson<ControlledLedgerPostingPreview>(
        `/api/automation/controlled-ledger-posting/clearances/${encodeURIComponent(
          clearanceId,
        )}/preview`,
      ),
  });
}

export function useControlledLedgerCorrectionPreviewMutation() {
  return useMutation({
    mutationFn: (request: {
      postingId: string;
      reason_code: ControlledLedgerCorrectionReason;
      operator_id: string;
    }) => {
      const { postingId, ...body } = request;
      return postJson<ControlledLedgerCorrectionPreview>(
        `/api/automation/controlled-ledger-corrections/postings/${encodeURIComponent(
          postingId,
        )}/preview`,
        body,
      );
    },
  });
}

export function useControlledSubmissionClearancePreviewMutation() {
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      reconciliation_run_id: string;
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledSubmissionClearancePreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/reconciliation-clearance/preview`,
        body,
      );
    },
  });
}

export function useControlledBrokerRecoveryPreviewMutation() {
  return useMutation({
    mutationFn: ({ submitIntentId }: { submitIntentId: string }) =>
      postJson<ControlledBrokerRecoveryPreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/recovery/preview`,
      ),
  });
}

export function useManualBrokerCancellationTicketPreviewMutation() {
  return useMutation({
    mutationFn: ({ submitIntentId }: { submitIntentId: string }) =>
      postJson<ManualBrokerCancellationTicketPreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/manual-cancellation-ticket/preview`,
      ),
  });
}

export function useManualBrokerCancellationTicketExportMutation() {
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      ticket_fingerprint: string;
      acknowledgement: 'prepare_manual_broker_cancellation_ticket_without_broker_contact';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ManualBrokerCancellationTicketExport>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/manual-cancellation-ticket/export`,
        body,
      );
    },
  });
}

export function useControlledBrokerRejectionEvidencePreviewMutation() {
  return useMutation({
    mutationFn: ({ submitIntentId }: { submitIntentId: string }) =>
      postJson<ControlledBrokerRejectionEvidencePreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/rejection-evidence/preview`,
      ),
  });
}

export function useControlledBrokerRejectionEvidenceExportMutation() {
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      review_fingerprint: string;
      acknowledgement: 'export_exact_rejection_evidence_without_retry_or_authority_change';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledBrokerRejectionEvidenceExport>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/rejection-evidence/export`,
        body,
      );
    },
  });
}

export function useControlledBrokerRejectionReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      review_fingerprint: string;
      reviewer_id: string;
      disposition: 'acknowledged_no_retry';
      acknowledgement: 'record_exact_rejection_review_without_retry_or_authority_change';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledBrokerRejectionReview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/rejection-reviews`,
        body,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['automation', 'cockpit'],
      });
    },
  });
}

export function useControlledBrokerRecoveryApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'query_unknown_controlled_broker_submission';
      artifact_type: 'controlled_broker_submission_recovery';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledBrokerRecoveryApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      recovery_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'query_exact_unknown_submission_once_without_resubmit';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledBrokerRecoveryResult>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/recoveries`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({
          queryKey: ['execution-reconciliation', 'runs'],
        }),
      ]);
    },
  });
}

export function useControlledSubmissionClearanceApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'clear_controlled_submission_reconciliation';
      artifact_type: 'controlled_submission_reconciliation_clearance';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledSubmissionClearanceApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      reconciliation_run_id: string;
      clearance_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'clear_exact_terminal_outcome_without_automatic_ledger_mutation';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledSubmissionClearanceResult>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/reconciliation-clearances`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({
          queryKey: ['execution-reconciliation', 'runs'],
        }),
      ]);
    },
  });
}

export function useOperatorApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'post_controlled_submission_ledger';
      artifact_type: 'controlled_submission_ledger_posting';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledLedgerCorrectionApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'reverse_controlled_submission_ledger_posting';
      artifact_type: 'controlled_submission_ledger_correction';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useOperatorApprovalVerificationMutation() {
  return useMutation({
    mutationFn: (request: { challenge_id: string; signature_base64: string }) =>
      postJson<VerifiedOperatorApproval>(
        '/api/automation/capital-authority/operator-approvals/verifications',
        request,
      ),
  });
}

export function useControlledLedgerPostingApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      clearanceId: string;
      posting_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'apply_exact_reconciled_ledger_posting_once';
    }) => {
      const { clearanceId, ...body } = request;
      return postJson<ControlledLedgerPostingResult>(
        `/api/automation/controlled-ledger-posting/clearances/${encodeURIComponent(
          clearanceId,
        )}/postings`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}

export function useControlledLedgerCorrectionApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      postingId: string;
      reason_code: ControlledLedgerCorrectionReason;
      operator_id: string;
      correction_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'apply_exact_compensating_ledger_correction_once';
    }) => {
      const { postingId, ...body } = request;
      return postJson<ControlledLedgerCorrectionResult>(
        `/api/automation/controlled-ledger-corrections/postings/${encodeURIComponent(
          postingId,
        )}/corrections`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({ queryKey: ['account-overview'] }),
        queryClient.invalidateQueries({ queryKey: ['account-state'] }),
        queryClient.invalidateQueries({ queryKey: ['account-equity-curve'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-equity-curve-series'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-score'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-import-runs'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-risk-summary'] }),
        queryClient.invalidateQueries({
          queryKey: ['portfolio-explainability'],
        }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-positions'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-snapshot'] }),
        queryClient.invalidateQueries({
          queryKey: ['portfolio-live-holdings'],
        }),
        queryClient.invalidateQueries({ queryKey: ['ledger-entries'] }),
      ]);
    },
  });
}
