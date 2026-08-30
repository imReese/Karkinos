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
    resolution: {
      schema_version: 'karkinos.account_truth.citic_source_resolution_stage.v1';
      status:
        | 'legacy_source_review_state_unavailable'
        | 'no_legacy_source_resolution_pending'
        | 'legacy_query_window_review_required'
        | 'legacy_source_scope_review_required'
        | 'legacy_attestations_complete_canonical_resolution_required';
      pending_source_count: number;
      source_count_complete: boolean;
      query_window_attestations_complete: boolean;
      source_scope_attestations_complete: boolean;
      legacy_source_attestations_complete: boolean;
      canonical_account_truth_established_by_legacy_sources: false;
      next_manual_action: string;
      satisfies_account_truth: false;
      satisfies_reconciliation: false;
      provider_contacted: false;
      database_writes_performed: false;
      authorizes_execution: false;
      changes_capital_authority: false;
      limitations: string[];
    };
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
  asset_class?: string | null;
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

export type AssetReconciliationLane = {
  status: ReconciliationStatus | 'not_evaluated';
  unresolved_count: number;
};

export type ReconciliationReportDetail = ReconciliationReportSummary & {
  items: ReconciliationItem[];
  asset_reconciliation?: {
    stock: AssetReconciliationLane;
    fund: AssetReconciliationLane;
    cash: AssetReconciliationLane;
    account: AssetReconciliationLane;
  };
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
