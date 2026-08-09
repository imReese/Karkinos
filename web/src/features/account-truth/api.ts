import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

export type AccountTruthGateStatus = 'pass' | 'degraded' | 'blocked';
export type ReconciliationStatus = 'pass' | 'warning' | 'mismatch' | 'blocked';
export type ReviewStatus =
  | 'accepted'
  | 'ignored'
  | 'known_difference'
  | 'ledger_candidate'
  | 'needs_investigation';

export type AccountTruthScore = {
  schema_version: string;
  status: 'available' | 'missing';
  import_run_id: string | null;
  score: number | null;
  gate_status: AccountTruthGateStatus;
  cash_status: string;
  position_status: string;
  fee_status: string;
  cost_basis_status: string;
  data_freshness_status: string;
  unresolved_mismatch_count: number | null;
  resolved_review_count: number;
  required_actions: string[];
  blocking_reasons: string[];
  limitations: string[];
  source_type?: string;
  source_name?: string;
  created_at?: string;
  ledger_coverage?: {
    status: 'covered' | 'stale' | 'unknown';
    import_created_at: string;
    latest_ledger_created_at: string | null;
    latest_ledger_event_at?: string | null;
    broker_evidence_as_of?: string | null;
    reasons?: string[];
  };
};

export type AccountTruthEvidenceReadiness = {
  schema_version: 'karkinos.account_truth.evidence_readiness.v2';
  status: 'ready' | 'blocked';
  account_truth_gate_status: AccountTruthGateStatus;
  account_truth_import_run_id: string | null;
  score_status: 'available' | 'missing';
  ledger_coverage_status: string;
  evidence_scope: {
    schema_version: 'karkinos.account_truth.evidence_scope.v1';
    status: 'complete' | 'blocked';
    import_run_id: string | null;
    source_schema_version: string | null;
    observed_scope_fingerprint: string;
    account_binding: {
      status: 'bound' | 'missing';
      provider?: string;
      account_alias: string | null;
      account_reference_hash: string | null;
    };
    declared_coverage_window: {
      status: 'complete' | 'missing';
      start_date: string | null;
      end_date: string | null;
    };
    observed_event_window: {
      status: 'available' | 'missing' | 'blocked';
      occurred_start_date: string | null;
      occurred_end_date: string | null;
      settled_start_date: string | null;
      settled_end_date: string | null;
      event_count: number;
      unique_event_count: number;
      expected_event_count: number;
    };
    asset_scope: {
      status: 'complete' | 'unverified';
      observed_asset_classes: string[];
      observed_currencies: string[];
      observed_event_types: string[];
      reviewed_asset_classes?: string[];
    };
    snapshot_evidence: {
      cash_snapshot_count: number;
      position_snapshot_count: number;
      latest_cash_snapshot_date: string | null;
      latest_position_snapshot_date: string | null;
    };
    blockers: string[];
    required_actions: string[];
    evidence_fingerprint: string;
    review: {
      schema_version: string;
      review_id: string;
      decision: 'accepted' | 'revoked';
      provider: string;
      review_fingerprint: string;
      reviewed_at: string;
    } | null;
    limitations: string[];
    persisted_facts_only: true;
    provider_contacted: false;
    database_writes_performed: false;
    authorizes_execution: false;
    changes_capital_authority: false;
  };
  citic_source_follow_up: {
    status: string;
    pending_source_count: number;
    count_complete: boolean;
    evidence_fingerprint: string;
    query_window_batch_integrity_status: string;
    query_window_batch_assessment_fingerprint: string;
    query_window_gap_calendar_day_count: number;
    query_window_overlap_calendar_day_count: number;
    query_window_integrity_clear: boolean;
    source_scope_batch_integrity_status: string;
    source_scope_batch_assessment_fingerprint: string;
    source_scope_integrity_clear: boolean;
    source_scope_account_binding_consistent: boolean;
    source_scope_declared_scope_consistent: boolean;
    source_scope_complete_returned_results_attested: boolean;
    intake_scan_truncated: boolean;
  };
  items: Array<{
    requirement: string;
    status: string;
    evidence_reference: string | null;
    required_action: string | null;
  }>;
  blockers: string[];
  required_evidence: string[];
  required_actions: string[];
  known_incomplete_source_count: number;
  source_review_count_complete: boolean;
  evidence_fingerprint: string;
  next_manual_action: string;
  limitations: string[];
  persisted_facts_only: true;
  provider_contacted: false;
  database_writes_performed: false;
  eligible_for_reconciliation: false;
  authorizes_execution: false;
  changes_capital_authority: false;
};

export type EvidenceScopeReviewCommand = {
  schema_version: 'karkinos.account_truth.evidence_scope_review_command.v1';
  status: 'recorded' | 'revoked';
  review: {
    review_id: string;
    schema_version: string;
    import_run_id: string;
    observed_scope_fingerprint: string;
    decision: 'accepted' | 'revoked';
    review_fingerprint: string;
    created_at: string;
    reused: boolean;
  };
  readiness: AccountTruthEvidenceReadiness;
  scope_review_write_performed: boolean;
  writes_only_scope_review_store: true;
  does_not_mutate_broker_evidence: true;
  does_not_mutate_production_ledger: true;
  does_not_reconcile_account: true;
  provider_contacted: false;
  authorizes_execution: false;
  changes_capital_authority: false;
};

export type ImportRun = {
  import_run_id: string;
  schema_version: string;
  source_type: string;
  source_name: string;
  file_fingerprint: string;
  row_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  row_duplicate_count: number;
  file_duplicate_count: number;
  validation_status: string;
  limitations: string[];
  duplicate_of_import_run_id: string | null;
  created_at: string;
};

export type ReconciliationReportSummary = {
  import_run_id: string;
  schema_version: string;
  status: ReconciliationStatus;
  row_count: number;
  validation_status: string;
  source_type: string;
  source_name: string;
  created_at: string;
  unresolved_count: number;
  cash_difference: string;
  fee_difference: string;
  tax_difference: string;
  suggested_review_actions: string[];
  limitations: string[];
};

export type ReviewDecision = {
  id: number;
  import_run_id: string;
  item_key: string;
  category: string;
  symbol: string;
  review_status: ReviewStatus;
  note: string;
  reviewer: string;
  evidence_fingerprint?: string;
  is_current?: boolean;
  schema_version: string;
  created_at: string;
  updated_at: string;
  does_not_mutate_production_ledger: boolean;
};

export type ReconciliationItem = {
  item_key: string;
  category: string;
  status: ReconciliationStatus;
  severity: string;
  symbol: string;
  display_name?: string | null;
  broker_value: string;
  karkinos_value: string;
  difference: string;
  suggested_review_action: string;
  detail_code?: string;
  detail: string;
  detail_context?: Record<string, string>;
  evidence_references: string[];
  evidence_fingerprint?: string;
  manual_review_does_not_override_mismatch?: boolean;
  latest_review: ReviewDecision | null;
};

export type ReconciliationReportDetail = ReconciliationReportSummary & {
  items: ReconciliationItem[];
};

export type BrokerStatementPreviewEvent = {
  row_number: number;
  event_id: string;
  event_type: string;
  occurred_at: string;
  settled_at: string;
  symbol: string;
  instrument_name: string;
  asset_class: string;
  currency: string;
  quantity: string;
  price: string;
  gross_amount: string;
  fee: string;
  tax: string;
  net_amount: string;
  cash_balance: string | null;
  position_quantity: string | null;
  cost_basis: string | null;
  is_duplicate: boolean;
};

export type BrokerStatementPreview = {
  schema_version: string;
  source_type: string;
  source_name: string;
  generated_at: string;
  file_fingerprint: string;
  normalized_columns: string[];
  row_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  duplicate_row_count: number;
  validation_status: string;
  limitations: string[];
  errors: Array<{
    row_number: number | null;
    code: string;
    message: string;
  }>;
  events_preview: BrokerStatementPreviewEvent[];
  preview_event_count: number;
  total_event_count: number;
  does_not_mutate_production_ledger: boolean;
};

export type BrokerStatementImportResult = {
  import_run: ImportRun;
  preview: BrokerStatementPreview;
  report: ReconciliationReportSummary;
  does_not_mutate_production_ledger: boolean;
};

export type CiticBrokerSoakCandidate = {
  schema_version: 'karkinos.account_truth.citic_broker_soak_candidate.v1';
  status: 'blocked';
  assessment_fingerprint: string;
  source_contract_valid: boolean;
  recognized_event_count: number;
  blockers: string[];
  required_source_evidence: string[];
  operational_prerequisites: string[];
  eligible_for_broker_soak: false;
  connector_registered: false;
  provider_contacted: false;
  database_writes_performed: false;
  does_not_register_connector: true;
  does_not_record_soak_evidence: true;
  does_not_submit_broker_order: true;
  does_not_cancel_broker_order: true;
  authorizes_execution: false;
  changes_capital_authority: false;
};

export type CiticHistoryXlsPreview = {
  schema_version: string;
  source_type: 'citic_history_xls_preview';
  generated_at: string;
  file_fingerprint: string;
  row_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  recognized_non_financial_activity_count: number;
  duplicate_row_count: number;
  validation_status: 'blocked';
  limitations: string[];
  errors: Array<{
    row_number: number | null;
    code: string;
    message: string;
  }>;
  total_event_count: number;
  source_preview_fingerprint: string;
  recordable_for_follow_up: boolean;
  required_evidence: string[];
  broker_soak_candidate: CiticBrokerSoakCandidate;
  events_included: false;
  evidence_persisted: false;
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticSourceReviewStatus = 'follow_up_required' | 'rejected';

export type CiticSourceQueryWindowReview = {
  review_id: string;
  schema_version: 'karkinos.account_truth.citic_source_query_window_review.v1';
  intake_id: string;
  file_fingerprint: string;
  source_preview_fingerprint: string;
  query_start_date: string;
  query_end_date: string;
  query_window_attested: true;
  decision: 'accepted' | 'revoked';
  effective_status: 'active' | 'revoked' | 'source_closed';
  supersedes_review_id: string | null;
  reviewer: string;
  review_fingerprint: string;
  created_at: string;
  reused: boolean;
  review_persisted: true;
  events_included: false;
  transaction_details_included: false;
  source_name_included: false;
  source_path_included: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  does_not_mutate_broker_evidence: true;
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticSourceQueryWindowReviewCommand = {
  schema_version: 'karkinos.account_truth.citic_source_query_window_review_command.v1';
  status: 'recorded' | 'revoked';
  review: CiticSourceQueryWindowReview;
  query_window_review_write_performed: boolean;
  writes_only_query_window_review_store: true;
  events_persisted: false;
  does_not_mutate_source_intake: true;
  does_not_mutate_broker_evidence: true;
  does_not_mutate_production_ledger: true;
  does_not_reconcile_account: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticSourceScopeReview = {
  review_id: string;
  schema_version: 'karkinos.account_truth.citic_source_scope_review.v1';
  intake_id: string;
  file_fingerprint: string;
  source_preview_fingerprint: string;
  query_window_review_id: string;
  query_window_review_fingerprint: string;
  account_alias: string;
  account_reference_hash: string;
  account_type: string;
  market_scopes: string[];
  asset_classes: string[];
  business_types: string[];
  no_other_filters_attested: true;
  complete_returned_results_attested: true;
  source_scope_attested: true;
  decision: 'accepted' | 'revoked';
  effective_status:
    'active' | 'revoked' | 'source_closed' | 'query_window_superseded';
  supersedes_review_id: string | null;
  reviewer: string;
  review_fingerprint: string;
  created_at: string;
  reused: boolean;
  review_persisted: true;
  raw_account_identifier_included: false;
  events_included: false;
  transaction_details_included: false;
  source_name_included: false;
  source_path_included: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  does_not_mutate_broker_evidence: true;
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticSourceScopeReviewCommand = {
  schema_version: 'karkinos.account_truth.citic_source_scope_review_command.v1';
  status: 'recorded' | 'revoked';
  review: CiticSourceScopeReview;
  source_scope_review_write_performed: boolean;
  writes_only_source_scope_review_store: true;
  raw_account_identifier_persisted: false;
  events_persisted: false;
  does_not_mutate_source_intake: true;
  does_not_mutate_query_window_review: true;
  does_not_mutate_broker_evidence: true;
  does_not_mutate_production_ledger: true;
  does_not_reconcile_account: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticSourceIntake = {
  intake_id: string;
  schema_version: string;
  source_type: 'citic_history_xls_preview';
  file_fingerprint: string;
  source_preview_fingerprint: string;
  validation_status: 'blocked';
  row_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  duplicate_row_count: number;
  recognized_event_count: number;
  recognized_non_financial_activity_count: number;
  error_codes: string[];
  required_evidence: string[];
  limitations: string[];
  recordable_for_follow_up: boolean;
  review_id: string;
  review_status: CiticSourceReviewStatus;
  reviewer: string;
  created_at: string;
  reviewed_at: string;
  reused: boolean;
  query_window_review: CiticSourceQueryWindowReview | null;
  source_scope_review: CiticSourceScopeReview | null;
  source_intake_persisted: true;
  events_persisted: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticHistoryXlsDirectoryStatus = {
  schema_version: 'karkinos.account_truth.citic_history_xls_directory.v1';
  enabled: boolean;
  state: 'configured' | 'disabled';
  max_files: number;
  max_file_bytes: number;
  max_total_bytes: number;
  configured_path_included: false;
  source_names_included: false;
  scan_requires_explicit_command: true;
  scan_persisted: false;
  events_persisted: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type CiticHistoryEventTypeCount = {
  event_type: string;
  count: number;
};

export type CiticQueryWindowBatchAssessment = {
  schema_version: 'karkinos.account_truth.citic_query_window_batch_assessment.v1';
  status: 'blocked';
  integrity_status: 'not_available' | 'partial' | 'clear' | 'blocked';
  source_count: number;
  reviewed_source_count: number;
  unreviewed_source_count: number;
  invalid_review_count: number;
  all_current_sources_reviewed: boolean;
  declared_window_start_date: string | null;
  declared_window_end_date: string | null;
  covered_calendar_day_count: number;
  gap_calendar_day_count: number;
  overlap_calendar_day_count: number;
  declared_windows_contiguous: boolean;
  declared_windows_non_overlapping: boolean;
  blockers: string[];
  required_evidence: string[];
  complete_account_coverage_proven: false;
  account_scope_bound: false;
  settlement_components_complete: false;
  current_account_snapshots_present: false;
  reviewed_query_windows_included: boolean;
  events_included: false;
  transaction_details_included: false;
  private_fields_included: false;
  source_names_included: false;
  paths_included: false;
  assessment_persisted: false;
  database_writes_performed: false;
  provider_contacted: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  limitations: string[];
  assessment_fingerprint: string;
};

export type CiticSourceScopeBatchAssessment = {
  schema_version: 'karkinos.account_truth.citic_source_scope_batch_assessment.v1';
  status: 'blocked';
  integrity_status: 'not_available' | 'partial' | 'clear' | 'blocked';
  source_count: number;
  reviewed_source_count: number;
  unreviewed_source_count: number;
  invalid_query_window_review_count: number;
  invalid_scope_review_count: number;
  all_current_sources_reviewed: boolean;
  account_binding_consistent: boolean;
  declared_scope_consistent: boolean;
  account_scope_bound: boolean;
  declared_source_scope_complete: boolean;
  no_other_filters_attested: boolean;
  complete_returned_results_attested: boolean;
  declared_account_type: string | null;
  declared_market_scopes: string[];
  declared_asset_classes: string[];
  declared_business_types: string[];
  blockers: string[];
  required_evidence: string[];
  complete_account_coverage_proven: false;
  settlement_components_complete: false;
  current_account_snapshots_present: false;
  account_reference_hashes_included: false;
  source_names_included: false;
  paths_included: false;
  events_included: false;
  transaction_details_included: false;
  assessment_persisted: false;
  database_writes_performed: false;
  provider_contacted: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  limitations: string[];
  assessment_fingerprint: string;
};

export type CiticHistoryXlsDirectoryScan = {
  schema_version: 'karkinos.account_truth.citic_history_xls_directory.v1';
  enabled: boolean;
  state: 'disabled' | 'empty' | 'ready' | 'partial' | 'blocked';
  candidate_file_count: number;
  preview_count: number;
  duplicate_file_count: number;
  unreadable_file_count: number;
  recognized_event_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  scan_fingerprint: string;
  error_codes: string[];
  batch_assessment: {
    schema_version: 'karkinos.account_truth.citic_history_xls_batch_assessment.v1';
    status: 'blocked';
    integrity_status: 'not_available' | 'clear' | 'blocked';
    source_count: number;
    structurally_recordable_source_count: number;
    source_with_financial_events_count: number;
    source_without_financial_events_count: number;
    observed_event_count: number;
    unique_event_count: number;
    within_file_duplicate_row_count: number;
    cross_file_duplicate_event_count: number;
    conflicting_event_identity_count: number;
    invalid_row_count: number;
    invalid_event_time_count: number;
    recognized_non_financial_activity_count: number;
    observed_event_months: string[];
    observed_event_month_counts: Array<{
      month: string;
      event_count: number;
    }>;
    batch_fingerprint: string;
    blockers: string[];
    required_evidence: string[];
    limitations: string[];
    query_windows_reviewed: false;
    complete_coverage_proven: false;
    settlement_components_complete: false;
    current_account_snapshots_present: false;
    account_scope_bound: false;
    events_included: false;
    private_fields_included: false;
    source_names_included: false;
    paths_included: false;
    evidence_persisted: false;
    eligible_for_account_truth: false;
    eligible_for_reconciliation: false;
    does_not_mutate_production_ledger: true;
    does_not_contact_provider: true;
    does_not_enable_broker_submission: true;
    does_not_change_capital_authority: true;
  };
  canonical_lineage_assessment: {
    schema_version: 'karkinos.account_truth.citic_history_canonical_lineage_assessment.v1';
    status: 'blocked';
    event_lineage_status: 'not_available' | 'partial' | 'exact';
    match_contract_version: 'citic_history_financial_semantics.v1';
    source_batch_fingerprint: string;
    canonical_import_reference: string | null;
    canonical_import_file_fingerprint: string | null;
    source_supported_event_count: number;
    canonical_supported_event_count: number;
    semantically_matched_event_count: number;
    source_unmatched_event_count: number;
    canonical_unmatched_event_count: number;
    source_event_type_counts: CiticHistoryEventTypeCount[];
    canonical_event_type_counts: CiticHistoryEventTypeCount[];
    semantically_matched_event_type_counts: CiticHistoryEventTypeCount[];
    source_unmatched_event_type_counts: CiticHistoryEventTypeCount[];
    canonical_unmatched_event_type_counts: CiticHistoryEventTypeCount[];
    source_events_with_broker_order_identity_count: number;
    canonical_events_with_broker_order_identity_count: number;
    broker_order_identity_matched_event_count: number;
    exact_event_identity_matched_event_count: number;
    semantic_match_dimensions: string[];
    blockers: string[];
    required_evidence: string[];
    complete_account_coverage_proven: false;
    events_included: false;
    transaction_details_included: false;
    private_fields_included: false;
    source_names_included: false;
    paths_included: false;
    assessment_persisted: false;
    database_writes_performed: false;
    provider_contacted: false;
    eligible_for_account_truth: false;
    eligible_for_reconciliation: false;
    authorizes_execution: false;
    changes_capital_authority: false;
    limitations: string[];
    assessment_fingerprint: string;
  };
  query_window_review_summary: {
    reviewed_source_count: number;
    unreviewed_source_count: number;
    all_current_sources_reviewed: boolean;
    complete_coverage_proven: false;
    eligible_for_account_truth: false;
    eligible_for_reconciliation: false;
  };
  query_window_batch_assessment: CiticQueryWindowBatchAssessment;
  source_scope_review_summary: {
    reviewed_source_count: number;
    unreviewed_source_count: number;
    all_current_sources_reviewed: boolean;
    same_account_binding_proven: boolean;
    declared_scope_consistent: boolean;
    complete_account_coverage_proven: false;
    eligible_for_account_truth: false;
    eligible_for_reconciliation: false;
  };
  source_scope_batch_assessment: CiticSourceScopeBatchAssessment;
  items: Array<
    CiticHistoryXlsPreview & {
      local_name_month_hint: string | null;
      local_name_month_hint_is_evidence: false;
      query_window_inferred: false;
      source_intake: CiticSourceIntake | null;
    }
  >;
  max_files: number;
  max_file_bytes: number;
  max_total_bytes: number;
  configured_path_included: false;
  source_names_included: false;
  source_name_month_hints_included: boolean;
  source_name_month_hints_are_evidence: false;
  scan_persisted: false;
  events_persisted: false;
  eligible_for_account_truth: false;
  eligible_for_reconciliation: false;
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_enable_broker_submission: true;
  does_not_change_capital_authority: true;
};

export type BrokerStatementCollectorStatus = {
  schema_version: string;
  enabled: boolean;
  state:
    | 'disabled'
    | 'waiting_for_file'
    | 'pending_stability'
    | 'imported'
    | 'unchanged'
    | 'blocked'
    | 'error';
  configured_path: string;
  source_name: string;
  file_present: boolean;
  poll_interval_seconds: number;
  stability_delay_seconds: number;
  max_file_bytes: number;
  last_observed_at: string | null;
  last_processed_at: string | null;
  last_success_at: string | null;
  file_fingerprint: string | null;
  import_run_id: string | null;
  validation_status: string | null;
  row_count: number | null;
  valid_row_count: number | null;
  invalid_row_count: number | null;
  duplicate_row_count: number | null;
  error_code: string | null;
  message: string;
  source_kind: 'local_file_readonly';
  does_not_mutate_production_ledger: true;
  does_not_contact_provider: true;
  does_not_change_execution_authority: true;
};

export function useAccountTruthScoreQuery() {
  return useQuery({
    queryKey: ['account-truth-score'],
    queryFn: () => apiClient<AccountTruthScore>('/api/account-truth/score'),
    staleTime: 10_000,
  });
}

export function useAccountTruthEvidenceReadinessQuery() {
  return useQuery({
    queryKey: ['account-truth-evidence-readiness'],
    queryFn: () =>
      apiClient<AccountTruthEvidenceReadiness>(
        '/api/account-truth/evidence-readiness',
      ),
    staleTime: 10_000,
  });
}

export function useRecordEvidenceScopeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      importRunId: string;
      expectedObservedScopeFingerprint: string;
      provider: string;
      accountAlias: string;
      accountReferenceHash: string;
      coverageStartDate: string;
      coverageEndDate: string;
      assetClasses: string[];
      fullAccountScopeAttested: boolean;
    }) => {
      if (!payload.fullAccountScopeAttested) {
        throw new Error('Account Truth scope attestation is required.');
      }
      return postEvidenceScopeReview(
        '/api/account-truth/evidence-scope/reviews',
        {
          import_run_id: payload.importRunId,
          expected_observed_scope_fingerprint:
            payload.expectedObservedScopeFingerprint,
          provider: payload.provider.trim().toLowerCase(),
          account_alias: payload.accountAlias.trim(),
          account_reference_hash: payload.accountReferenceHash,
          coverage_start_date: payload.coverageStartDate,
          coverage_end_date: payload.coverageEndDate,
          asset_classes: payload.assetClasses,
          full_account_scope_attested: true,
          reviewer: 'local_owner',
        },
      );
    },
    onSuccess: async (response) => {
      queryClient.setQueryData(
        ['account-truth-evidence-readiness'],
        response.readiness,
      );
      await queryClient.invalidateQueries({
        queryKey: ['account-truth-evidence-readiness'],
      });
    },
  });
}

export function useRevokeEvidenceScopeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      importRunId: string;
      expectedObservedScopeFingerprint: string;
    }) =>
      postEvidenceScopeReview(
        '/api/account-truth/evidence-scope/reviews/revoke',
        {
          import_run_id: payload.importRunId,
          expected_observed_scope_fingerprint:
            payload.expectedObservedScopeFingerprint,
          reviewer: 'local_owner',
        },
      ),
    onSuccess: async (response) => {
      queryClient.setQueryData(
        ['account-truth-evidence-readiness'],
        response.readiness,
      );
      await queryClient.invalidateQueries({
        queryKey: ['account-truth-evidence-readiness'],
      });
    },
  });
}

export async function hashAccountTruthAccountReference(
  provider: string,
  accountIdentifier: string,
): Promise<string> {
  const normalizedProvider = provider.trim().toLowerCase();
  const normalizedIdentifier = accountIdentifier.trim();
  if (!normalizedProvider || !normalizedIdentifier) {
    throw new Error('Provider and local account identifier are required.');
  }
  const encoded = new TextEncoder().encode(
    JSON.stringify({
      schema_version: 'karkinos.account_truth.account_reference.v1',
      provider: normalizedProvider,
      account_identifier: normalizedIdentifier,
    }),
  );
  const digest = await globalThis.crypto.subtle.digest('SHA-256', encoded);
  const hex = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, '0'),
  ).join('');
  return `sha256:${hex}`;
}

async function postEvidenceScopeReview(
  path: string,
  payload: Record<string, unknown>,
): Promise<EvidenceScopeReviewCommand> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as EvidenceScopeReviewCommand;
}

export function useBrokerStatementCollectorStatusQuery() {
  return useQuery({
    queryKey: ['broker-statement-collector-status'],
    queryFn: () =>
      apiClient<BrokerStatementCollectorStatus>(
        '/api/account-truth/broker-statement/collector',
      ),
    staleTime: 1_000,
    refetchInterval: 5_000,
  });
}

export function useAccountTruthImportRunsQuery() {
  return useQuery({
    queryKey: ['account-truth-import-runs'],
    queryFn: () =>
      apiClient<ImportRun[]>('/api/account-truth/import-runs?limit=50'),
    staleTime: 10_000,
  });
}

export function useReconciliationReportsQuery(
  status: ReconciliationStatus | 'all',
  enabled = true,
) {
  const search = status === 'all' ? '' : `?status=${status}`;
  return useQuery({
    queryKey: ['account-truth-reports', status],
    queryFn: () =>
      apiClient<ReconciliationReportSummary[]>(
        `/api/account-truth/reconciliation-reports${search}`,
      ),
    enabled,
    staleTime: 10_000,
  });
}

export function useReconciliationReportDetailQuery(importRunId: string | null) {
  return useQuery({
    queryKey: ['account-truth-report-detail', importRunId],
    queryFn: () =>
      apiClient<ReconciliationReportDetail>(
        `/api/account-truth/reconciliation-reports/${encodeURIComponent(
          importRunId ?? '',
        )}`,
      ),
    enabled: Boolean(importRunId),
    staleTime: 5_000,
  });
}

export function useRecordReviewDecisionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      importRunId: string;
      itemKey: string;
      category: string;
      symbol: string;
      review_status: ReviewStatus;
    }) => {
      const response = await fetch(
        `/api/account-truth/reconciliation-reports/${encodeURIComponent(
          payload.importRunId,
        )}/items/${encodeURIComponent(payload.itemKey)}/review`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            category: payload.category,
            symbol: payload.symbol,
            review_status: payload.review_status,
            note: 'Reviewed from Account Truth center.',
            reviewer: 'local',
          }),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as ReviewDecision;
    },
    onSuccess: async (_decision, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['account-truth-score'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-report-detail', variables.importRunId],
        }),
      ]);
    },
  });
}

async function postBrokerStatement<T>(path: string, payload: object) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function useBrokerStatementPreviewMutation() {
  return useMutation({
    mutationFn: (payload: { content: string; source_name: string }) =>
      postBrokerStatement<BrokerStatementPreview>(
        '/api/account-truth/broker-statement/preview',
        payload,
      ),
  });
}

export function useCiticHistoryXlsPreviewMutation() {
  return useMutation({
    mutationFn: async (payload: { content_base64: string }) => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/preview',
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticHistoryXlsPreview;
    },
  });
}

export function useCiticHistoryXlsIntakesQuery() {
  return useQuery({
    queryKey: ['citic-history-xls-intakes'],
    queryFn: () =>
      apiClient<CiticSourceIntake[]>(
        '/api/account-truth/citic-history-xls/intakes?limit=50',
      ),
    staleTime: 10_000,
  });
}

export function useCiticHistoryXlsDirectoryStatusQuery() {
  return useQuery({
    queryKey: ['citic-history-xls-directory-status'],
    queryFn: () =>
      apiClient<CiticHistoryXlsDirectoryStatus>(
        '/api/account-truth/citic-history-xls/directory',
      ),
    staleTime: 60_000,
  });
}

export function useCiticHistoryXlsDirectoryScanMutation() {
  return useMutation({
    mutationFn: async () => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/directory/scan',
        {
          method: 'POST',
          headers: { Accept: 'application/json' },
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticHistoryXlsDirectoryScan;
    },
  });
}

export function useCiticHistoryXlsDirectoryIntakeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      expected_file_fingerprint: string;
      review_status: CiticSourceReviewStatus;
    }) => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/directory/intakes',
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticSourceIntake;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['citic-history-xls-intakes'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
      ]);
    },
  });
}

export function useCiticHistoryXlsIntakeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      content_base64: string;
      expected_file_fingerprint: string;
      review_status: CiticSourceReviewStatus;
    }) => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/intakes',
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticSourceIntake;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['citic-history-xls-intakes'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
      ]);
    },
  });
}

type CiticSourceQueryWindowReviewPayload = {
  expected_file_fingerprint: string;
  expected_source_preview_fingerprint: string;
  query_start_date: string;
  query_end_date: string;
  query_window_attested: true;
};

async function invalidateCiticSourceReviewQueries(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: ['citic-history-xls-intakes'],
    }),
    queryClient.invalidateQueries({
      queryKey: ['account-truth-evidence-readiness'],
    }),
    queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
  ]);
}

export function useCiticHistoryXlsQueryWindowReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      payload: CiticSourceQueryWindowReviewPayload & {
        content_base64: string;
      },
    ) =>
      postBrokerStatement<CiticSourceQueryWindowReviewCommand>(
        '/api/account-truth/citic-history-xls/query-window-reviews',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useCiticHistoryXlsDirectoryQueryWindowReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CiticSourceQueryWindowReviewPayload) =>
      postBrokerStatement<CiticSourceQueryWindowReviewCommand>(
        '/api/account-truth/citic-history-xls/directory/query-window-reviews',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useCiticHistoryXlsQueryWindowReviewRevokeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      intake_id: string;
      expected_active_review_id: string;
      expected_active_review_fingerprint: string;
    }) =>
      postBrokerStatement<CiticSourceQueryWindowReviewCommand>(
        '/api/account-truth/citic-history-xls/query-window-reviews/revoke',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

type CiticSourceScopeReviewPayload = {
  intake_id: string;
  expected_file_fingerprint: string;
  expected_source_preview_fingerprint: string;
  expected_query_window_review_id: string;
  expected_query_window_review_fingerprint: string;
  account_alias: string;
  account_reference_hash: string;
  account_type: string;
  market_scopes: string[];
  asset_classes: string[];
  business_types: string[];
  no_other_filters_attested: true;
  complete_returned_results_attested: true;
  source_scope_attested: true;
};

export function useCiticHistoryXlsSourceScopeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CiticSourceScopeReviewPayload) =>
      postBrokerStatement<CiticSourceScopeReviewCommand>(
        '/api/account-truth/citic-history-xls/source-scope-reviews',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useCiticHistoryXlsSourceScopeReviewRevokeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      intake_id: string;
      expected_active_review_id: string;
      expected_active_review_fingerprint: string;
    }) =>
      postBrokerStatement<CiticSourceScopeReviewCommand>(
        '/api/account-truth/citic-history-xls/source-scope-reviews/revoke',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useBrokerStatementImportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { content: string; source_name: string }) =>
      postBrokerStatement<BrokerStatementImportResult>(
        '/api/account-truth/broker-statement/import',
        payload,
      ),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['account-truth-score'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-import-runs'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({
          queryKey: [
            'account-truth-report-detail',
            result.import_run.import_run_id,
          ],
        }),
      ]);
    },
  });
}
