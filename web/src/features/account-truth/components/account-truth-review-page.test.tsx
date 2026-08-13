import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { AccountTruthReviewPage } from './account-truth-review-page';

type RenderOptions = {
  locale?: 'en' | 'zh';
};

const score = {
  schema_version: 'karkinos.account_truth.score.v1',
  status: 'available',
  import_run_id: 'import-run-1',
  score: 42,
  gate_status: 'blocked',
  cash_status: 'mismatch',
  position_status: 'mismatch',
  fee_status: 'pass',
  cost_basis_status: 'mismatch',
  data_freshness_status: 'fresh',
  unresolved_mismatch_count: 2,
  resolved_review_count: 1,
  required_actions: ['review_position_difference'],
  blocking_reasons: ['unresolved_position_difference'],
  limitations: ['Unresolved reconciliation items require review.'],
};

const evidenceReadiness = {
  schema_version: 'karkinos.account_truth.evidence_readiness.v2',
  status: 'blocked',
  account_truth_gate_status: 'blocked',
  account_truth_import_run_id: 'import-run-1',
  score_status: 'available',
  ledger_coverage_status: 'covered',
  evidence_scope: {
    schema_version: 'karkinos.account_truth.evidence_scope.v1',
    status: 'blocked',
    import_run_id: 'import-run-1',
    source_schema_version: 'karkinos.account_truth.broker_evidence.v2',
    observed_scope_fingerprint: 'sha256:' + 'd'.repeat(64),
    account_binding: {
      status: 'missing',
      account_alias: null,
      account_reference_hash: null,
    },
    declared_coverage_window: {
      status: 'missing',
      start_date: null,
      end_date: null,
    },
    observed_event_window: {
      status: 'available',
      occurred_start_date: '2026-01-05',
      occurred_end_date: '2026-01-15',
      settled_start_date: '2026-01-06',
      settled_end_date: '2026-01-15',
      event_count: 3,
      unique_event_count: 3,
      expected_event_count: 3,
    },
    asset_scope: {
      status: 'unverified',
      observed_asset_classes: ['stock'],
      observed_currencies: ['CNY'],
      observed_event_types: ['cash_snapshot', 'position_snapshot', 'trade_buy'],
    },
    snapshot_evidence: {
      cash_snapshot_count: 1,
      position_snapshot_count: 1,
      latest_cash_snapshot_date: '2026-01-15',
      latest_position_snapshot_date: '2026-01-15',
    },
    blockers: [
      'account_truth_account_scope_unbound',
      'account_truth_coverage_window_undeclared',
      'account_truth_asset_scope_completeness_unverified',
    ],
    required_actions: [
      'bind_account_truth_evidence_to_reviewed_account_scope',
      'record_reviewed_account_truth_coverage_window',
      'review_account_truth_asset_scope_completeness',
    ],
    evidence_fingerprint: 'sha256:' + 'c'.repeat(64),
    review: null,
    limitations: [],
    persisted_facts_only: true,
    provider_contacted: false,
    database_writes_performed: false,
    authorizes_execution: false,
    changes_capital_authority: false,
  },
  citic_source_follow_up: {
    status: 'follow_up_required',
    pending_source_count: 4,
    count_complete: true,
    evidence_fingerprint: 'sha256:' + 'd'.repeat(64),
    query_window_batch_integrity_status: 'blocked',
    query_window_batch_assessment_fingerprint: 'sha256:' + 'e'.repeat(64),
    query_window_gap_calendar_day_count: 1,
    query_window_overlap_calendar_day_count: 0,
    query_window_integrity_clear: false,
    source_scope_batch_integrity_status: 'blocked',
    source_scope_batch_assessment_fingerprint: 'sha256:' + '6'.repeat(64),
    source_scope_integrity_clear: false,
    source_scope_account_binding_consistent: false,
    source_scope_declared_scope_consistent: false,
    source_scope_complete_returned_results_attested: false,
    intake_scan_truncated: false,
  },
  items: [
    {
      requirement: 'canonical_broker_evidence',
      status: 'pass',
      evidence_reference: 'account_truth_import:import-run-1',
      required_action: null,
    },
    {
      requirement: 'reviewed_account_and_period_scope',
      status: 'blocked',
      evidence_reference: 'account_truth_evidence_scope:sha256-scope',
      required_action: 'bind_account_truth_evidence_to_reviewed_account_scope',
    },
    {
      requirement: 'current_position_snapshot',
      status: 'mismatch',
      evidence_reference: 'account_truth_score:position_status',
      required_action: 'provide_position_snapshot',
    },
    {
      requirement: 'known_incomplete_source_reviews',
      status: 'blocked',
      evidence_reference: 'sha256:' + 'a'.repeat(64),
      required_action: 'provide_citic_account_truth_evidence_or_reject_source',
    },
  ],
  blockers: [
    'unresolved_position_difference',
    'citic_source_follow_up_required',
    'account_truth_account_scope_unbound',
  ],
  required_evidence: [
    'itemized_settlement_or_cash_flow',
    'current_cash_and_position_snapshot',
  ],
  required_actions: [
    'review_position_difference',
    'provide_citic_account_truth_evidence_or_reject_source',
    'bind_account_truth_evidence_to_reviewed_account_scope',
  ],
  known_incomplete_source_count: 4,
  source_review_count_complete: true,
  evidence_fingerprint: 'sha256:' + 'b'.repeat(64),
  next_manual_action: 'review_position_difference',
  limitations: [],
  persisted_facts_only: true,
  provider_contacted: false,
  database_writes_performed: false,
  eligible_for_reconciliation: false,
  authorizes_execution: false,
  changes_capital_authority: false,
};

const evidenceScopeReviewCommand = {
  schema_version: 'karkinos.account_truth.evidence_scope_review_command.v1',
  status: 'recorded',
  review: {
    review_id: 'scope-review-1',
    schema_version: 'karkinos.account_truth.evidence_scope_review.v1',
    import_run_id: 'import-run-1',
    observed_scope_fingerprint:
      evidenceReadiness.evidence_scope.observed_scope_fingerprint,
    decision: 'accepted',
    review_fingerprint: 'sha256:' + 'e'.repeat(64),
    created_at: '2026-02-01T00:00:00Z',
    reused: false,
  },
  readiness: evidenceReadiness,
  scope_review_write_performed: true,
  writes_only_scope_review_store: true,
  does_not_mutate_broker_evidence: true,
  does_not_mutate_production_ledger: true,
  does_not_reconcile_account: true,
  provider_contacted: false,
  authorizes_execution: false,
  changes_capital_authority: false,
};

const importRuns = [
  {
    import_run_id: 'import-run-1',
    schema_version: 'karkinos.broker_evidence.import_run.v1',
    source_type: 'canonical_broker_statement_csv',
    source_name: 'synthetic-safe-example.csv',
    file_fingerprint: 'sha256-safe',
    row_count: 3,
    valid_row_count: 3,
    invalid_row_count: 0,
    row_duplicate_count: 0,
    file_duplicate_count: 0,
    validation_status: 'pass',
    limitations: ['safe synthetic fixture'],
    duplicate_of_import_run_id: null,
    created_at: '2026-06-18T10:10:00+08:00',
  },
];

const reportSummaries = [
  {
    import_run_id: 'import-run-1',
    schema_version: 'karkinos.account_truth.reconciliation.v1',
    status: 'mismatch',
    row_count: 3,
    validation_status: 'pass',
    source_type: 'canonical_broker_statement_csv',
    source_name: 'synthetic-safe-example.csv',
    created_at: '2026-06-18T10:10:00+08:00',
    unresolved_count: 2,
    cash_difference: '120.00',
    fee_difference: '0.00',
    tax_difference: '2.50',
    suggested_review_actions: ['review_position_difference'],
    limitations: ['safe synthetic fixture'],
  },
];

const reportDetail = {
  ...reportSummaries[0],
  items: [
    {
      item_key: 'position:SYN001',
      category: 'position',
      status: 'mismatch',
      severity: 'mismatch',
      symbol: 'SYN001',
      display_name: '合成样例股票A',
      broker_value: '100',
      karkinos_value: '0',
      difference: '100',
      suggested_review_action: 'review_position_difference',
      detail: 'Broker position does not match local ledger projection.',
      evidence_references: [
        'broker_event:import-run-1:SYN001:position_snapshot',
      ],
      latest_review: null,
    },
  ],
};

const brokerStatementCsv = [
  'event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note',
  'synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,8972.00,,,',
].join('\n');

const brokerStatementPreview = {
  schema_version: 'karkinos.broker_statement.v1',
  source_type: 'canonical_broker_statement_csv',
  source_name: 'local-broker-statement.csv',
  generated_at: '2026-06-18T10:00:00+08:00',
  file_fingerprint: 'sha256-preview',
  normalized_columns: [],
  row_count: 1,
  valid_row_count: 1,
  invalid_row_count: 0,
  duplicate_row_count: 0,
  validation_status: 'pass',
  limitations: [],
  errors: [],
  events_preview: [
    {
      row_number: 2,
      event_id: 'synthetic-cash-001',
      event_type: 'cash_snapshot',
      occurred_at: '2026-01-15T15:10:00+08:00',
      settled_at: '2026-01-15',
      symbol: '',
      instrument_name: '',
      asset_class: '',
      currency: 'CNY',
      quantity: '0',
      price: '0',
      gross_amount: '0.00',
      fee: '0.00',
      tax: '0.00',
      net_amount: '0.00',
      cash_balance: '8972.00',
      position_quantity: null,
      cost_basis: null,
      is_duplicate: false,
    },
  ],
  preview_event_count: 1,
  total_event_count: 1,
  does_not_mutate_production_ledger: true,
};

const citicHistoryXlsPreview = {
  schema_version: 'karkinos.broker_statement.v2',
  source_type: 'citic_history_xls_preview',
  generated_at: '2026-08-03T10:00:00+08:00',
  file_fingerprint: 'a'.repeat(64),
  row_count: 2,
  valid_row_count: 2,
  invalid_row_count: 0,
  recognized_non_financial_activity_count: 0,
  duplicate_row_count: 0,
  validation_status: 'blocked',
  limitations: ['Settlement components and account snapshots are missing.'],
  errors: [
    {
      row_number: null,
      code: 'citic_history_xls_settlement_components_missing',
      message: 'Private broker details must not be rendered.',
    },
  ],
  total_event_count: 2,
  source_preview_fingerprint: 'c'.repeat(64),
  recordable_for_follow_up: true,
  required_evidence: [
    'itemized_settlement_or_cash_flow',
    'current_cash_and_position_snapshot',
  ],
  broker_soak_candidate: {
    schema_version: 'karkinos.account_truth.citic_broker_soak_candidate.v1',
    status: 'blocked',
    assessment_fingerprint: 'd'.repeat(64),
    source_contract_valid: true,
    recognized_event_count: 2,
    blockers: ['citic_history_xls_not_broker_connector_snapshot'],
    required_source_evidence: [
      'versioned_readonly_connector_snapshot',
      'reviewed_account_alias_binding',
      'provider_source_captured_at',
      'connector_deployment_identity',
      'connector_health_evidence',
      'current_cash_snapshot',
      'current_position_snapshot',
      'current_order_snapshot',
      'itemized_fill_fees_and_taxes',
    ],
    operational_prerequisites: [
      'explicit_adapter_release_review',
      'provider_trading_calendar_evidence',
      'clear_execution_reconciliation',
    ],
    eligible_for_broker_soak: false,
    connector_registered: false,
    provider_contacted: false,
    database_writes_performed: false,
    does_not_register_connector: true,
    does_not_record_soak_evidence: true,
    does_not_submit_broker_order: true,
    does_not_cancel_broker_order: true,
    authorizes_execution: false,
    changes_capital_authority: false,
  },
  events_included: false,
  evidence_persisted: false,
  does_not_mutate_production_ledger: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
};

const citicQueryWindowReview = {
  review_id: 'citic-window-review-synthetic',
  schema_version: 'karkinos.account_truth.citic_source_query_window_review.v1',
  intake_id: 'citic-intake-synthetic',
  file_fingerprint: 'a'.repeat(64),
  source_preview_fingerprint: 'c'.repeat(64),
  query_start_date: '2026-05-01',
  query_end_date: '2026-05-31',
  query_window_attested: true,
  decision: 'accepted',
  effective_status: 'active',
  supersedes_review_id: null,
  reviewer: 'local_owner',
  review_fingerprint: `sha256:${'f'.repeat(64)}`,
  created_at: '2026-08-09T10:02:00+08:00',
  reused: false,
  review_persisted: true,
  events_included: false,
  transaction_details_included: false,
  source_name_included: false,
  source_path_included: false,
  eligible_for_account_truth: false,
  eligible_for_reconciliation: false,
  does_not_mutate_broker_evidence: true,
  does_not_mutate_production_ledger: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
};

const citicQueryWindowReviewCommand = {
  schema_version:
    'karkinos.account_truth.citic_source_query_window_review_command.v1',
  status: 'recorded',
  review: citicQueryWindowReview,
  query_window_review_write_performed: true,
  writes_only_query_window_review_store: true,
  events_persisted: false,
  does_not_mutate_source_intake: true,
  does_not_mutate_broker_evidence: true,
  does_not_mutate_production_ledger: true,
  does_not_reconcile_account: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
};

const citicSourceScopeReview = {
  review_id: 'citic-scope-review-synthetic',
  schema_version: 'karkinos.account_truth.citic_source_scope_review.v2',
  intake_id: 'citic-intake-synthetic',
  file_fingerprint: 'a'.repeat(64),
  source_preview_fingerprint: 'c'.repeat(64),
  query_window_review_id: citicQueryWindowReview.review_id,
  query_window_review_fingerprint: citicQueryWindowReview.review_fingerprint,
  account_alias: 'citic-primary',
  account_reference_hash: `sha256:${'7'.repeat(64)}`,
  account_type: 'cash',
  market_scopes: ['shanghai_a', 'shenzhen_a'],
  asset_classes: ['stock'],
  account_value_band: 'cny_0_20000',
  business_types: ['history_trades'],
  no_other_filters_attested: true,
  complete_returned_results_attested: true,
  source_scope_attested: true,
  decision: 'accepted',
  effective_status: 'active',
  supersedes_review_id: null,
  reviewer: 'local_owner',
  review_fingerprint: `sha256:${'5'.repeat(64)}`,
  created_at: '2026-08-09T10:03:00+08:00',
  reused: false,
  review_persisted: true,
  raw_account_identifier_included: false,
  events_included: false,
  transaction_details_included: false,
  source_name_included: false,
  source_path_included: false,
  eligible_for_account_truth: false,
  eligible_for_reconciliation: false,
  does_not_mutate_broker_evidence: true,
  does_not_mutate_production_ledger: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
  account_value_band_is_capital_authority: false,
};

const citicSourceScopeReviewCommand = {
  schema_version: 'karkinos.account_truth.citic_source_scope_review_command.v2',
  status: 'recorded',
  review: citicSourceScopeReview,
  source_scope_review_write_performed: true,
  writes_only_source_scope_review_store: true,
  raw_account_identifier_persisted: false,
  events_persisted: false,
  does_not_mutate_source_intake: true,
  does_not_mutate_query_window_review: true,
  does_not_mutate_broker_evidence: true,
  does_not_mutate_production_ledger: true,
  does_not_reconcile_account: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
  account_value_band_is_capital_authority: false,
};

const citicSourceIntake = {
  intake_id: 'citic-intake-synthetic',
  schema_version: 'karkinos.account_truth.citic_source_intake.v1',
  source_type: 'citic_history_xls_preview',
  file_fingerprint: 'a'.repeat(64),
  source_preview_fingerprint: 'c'.repeat(64),
  validation_status: 'blocked',
  row_count: 2,
  valid_row_count: 2,
  invalid_row_count: 0,
  duplicate_row_count: 0,
  recognized_event_count: 2,
  recognized_non_financial_activity_count: 0,
  error_codes: ['citic_history_xls_settlement_components_missing'],
  required_evidence: [
    'itemized_settlement_or_cash_flow',
    'current_cash_and_position_snapshot',
  ],
  limitations: ['Settlement components and account snapshots are missing.'],
  recordable_for_follow_up: true,
  review_id: 'citic-review-synthetic',
  review_status: 'follow_up_required',
  reviewer: 'local',
  created_at: '2026-08-03T10:00:00+08:00',
  reviewed_at: '2026-08-03T10:01:00+08:00',
  reused: false,
  query_window_review: null,
  source_scope_review: null,
  source_intake_persisted: true,
  events_persisted: false,
  eligible_for_account_truth: false,
  eligible_for_reconciliation: false,
  does_not_mutate_production_ledger: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
};

const citicDirectoryStatus = {
  schema_version: 'karkinos.account_truth.citic_history_xls_directory.v1',
  enabled: false,
  state: 'disabled',
  max_files: 120,
  max_file_bytes: 10485760,
  max_total_bytes: 67108864,
  configured_path_included: false,
  source_names_included: false,
  scan_requires_explicit_command: true,
  scan_persisted: false,
  events_persisted: false,
  eligible_for_account_truth: false,
  eligible_for_reconciliation: false,
  does_not_mutate_production_ledger: true,
  does_not_contact_provider: true,
  does_not_enable_broker_submission: true,
  does_not_change_capital_authority: true,
};

const citicDirectoryScan = {
  ...citicDirectoryStatus,
  enabled: true,
  state: 'ready',
  source_name_month_hints_included: true,
  source_name_month_hints_are_evidence: false,
  candidate_file_count: 1,
  preview_count: 1,
  duplicate_file_count: 0,
  unreadable_file_count: 0,
  recognized_event_count: 2,
  valid_row_count: 2,
  invalid_row_count: 0,
  scan_fingerprint: 'd'.repeat(64),
  error_codes: [],
  batch_assessment: {
    schema_version:
      'karkinos.account_truth.citic_history_xls_batch_assessment.v1',
    status: 'blocked',
    integrity_status: 'clear',
    source_count: 1,
    structurally_recordable_source_count: 1,
    source_with_financial_events_count: 1,
    source_without_financial_events_count: 0,
    observed_event_count: 2,
    unique_event_count: 2,
    within_file_duplicate_row_count: 0,
    cross_file_duplicate_event_count: 0,
    conflicting_event_identity_count: 0,
    invalid_row_count: 0,
    invalid_event_time_count: 0,
    recognized_non_financial_activity_count: 0,
    observed_event_months: ['2026-05'],
    observed_event_month_counts: [{ month: '2026-05', event_count: 2 }],
    batch_fingerprint: 'e'.repeat(64),
    blockers: [
      'citic_history_xls_batch_query_windows_unreviewed',
      'citic_history_xls_batch_settlement_components_missing',
      'citic_history_xls_batch_current_account_snapshots_missing',
      'citic_history_xls_batch_account_scope_unbound',
    ],
    required_evidence: [
      'reviewed_query_window_for_each_source',
      'itemized_settlement_or_cash_flow',
      'current_cash_and_position_snapshot',
      'reviewed_account_alias_binding',
    ],
    limitations: ['Observed event months do not prove complete coverage.'],
    query_windows_reviewed: false,
    complete_coverage_proven: false,
    settlement_components_complete: false,
    current_account_snapshots_present: false,
    account_scope_bound: false,
    events_included: false,
    private_fields_included: false,
    source_names_included: false,
    paths_included: false,
    evidence_persisted: false,
    eligible_for_account_truth: false,
    eligible_for_reconciliation: false,
    does_not_mutate_production_ledger: true,
    does_not_contact_provider: true,
    does_not_enable_broker_submission: true,
    does_not_change_capital_authority: true,
  },
  canonical_lineage_assessment: {
    schema_version:
      'karkinos.account_truth.citic_history_canonical_lineage_assessment.v1',
    status: 'blocked',
    event_lineage_status: 'partial',
    match_contract_version: 'citic_history_financial_semantics.v1',
    source_batch_fingerprint: `sha256:${'e'.repeat(64)}`,
    canonical_import_reference: 'account_truth_import:import-1',
    canonical_import_file_fingerprint: 'f'.repeat(64),
    source_supported_event_count: 2,
    canonical_supported_event_count: 3,
    semantically_matched_event_count: 1,
    source_unmatched_event_count: 1,
    canonical_unmatched_event_count: 2,
    source_event_type_counts: [
      { event_type: 'dividend', count: 1 },
      { event_type: 'trade_buy', count: 1 },
    ],
    canonical_event_type_counts: [
      { event_type: 'trade_buy', count: 1 },
      { event_type: 'trade_sell', count: 2 },
    ],
    semantically_matched_event_type_counts: [
      { event_type: 'trade_buy', count: 1 },
    ],
    source_unmatched_event_type_counts: [{ event_type: 'dividend', count: 1 }],
    canonical_unmatched_event_type_counts: [
      { event_type: 'trade_sell', count: 2 },
    ],
    source_events_with_broker_order_identity_count: 2,
    canonical_events_with_broker_order_identity_count: 0,
    broker_order_identity_matched_event_count: 0,
    exact_event_identity_matched_event_count: 0,
    semantic_match_dimensions: [
      'event_type',
      'occurred_at',
      'settled_at',
      'symbol',
      'instrument_name',
      'asset_class',
      'currency',
      'quantity',
      'price',
      'gross_amount',
      'net_amount',
    ],
    blockers: [
      'citic_canonical_lineage_complete_account_coverage_unproven',
      'citic_canonical_lineage_source_events_unmatched',
      'citic_canonical_lineage_canonical_events_outside_source_batch',
      'citic_canonical_lineage_broker_order_identity_not_preserved',
      'citic_canonical_lineage_event_identity_not_preserved',
    ],
    required_evidence: [
      'preserve_source_event_and_broker_order_identity_in_canonical_import',
      'resolve_unmatched_source_and_canonical_events',
      'reviewed_query_window_for_each_source',
      'itemized_settlement_components_and_current_account_snapshots',
    ],
    complete_account_coverage_proven: false,
    events_included: false,
    transaction_details_included: false,
    private_fields_included: false,
    source_names_included: false,
    paths_included: false,
    assessment_persisted: false,
    database_writes_performed: false,
    provider_contacted: false,
    eligible_for_account_truth: false,
    eligible_for_reconciliation: false,
    authorizes_execution: false,
    changes_capital_authority: false,
    limitations: ['Semantic match is not canonical source lineage.'],
    assessment_fingerprint: `sha256:${'a'.repeat(64)}`,
  },
  query_window_review_summary: {
    reviewed_source_count: 0,
    unreviewed_source_count: 1,
    all_current_sources_reviewed: false,
    complete_coverage_proven: false,
    eligible_for_account_truth: false,
    eligible_for_reconciliation: false,
  },
  query_window_batch_assessment: {
    schema_version:
      'karkinos.account_truth.citic_query_window_batch_assessment.v1',
    status: 'blocked',
    integrity_status: 'not_available',
    source_count: 1,
    reviewed_source_count: 0,
    unreviewed_source_count: 1,
    invalid_review_count: 0,
    all_current_sources_reviewed: false,
    declared_window_start_date: null,
    declared_window_end_date: null,
    covered_calendar_day_count: 0,
    gap_calendar_day_count: 0,
    overlap_calendar_day_count: 0,
    declared_windows_contiguous: false,
    declared_windows_non_overlapping: false,
    blockers: [
      'citic_query_window_batch_complete_account_coverage_unproven',
      'citic_query_window_batch_sources_unreviewed',
    ],
    required_evidence: [
      'explicit_query_window_review_for_each_current_source',
      'contiguous_non_overlapping_declared_query_windows',
      'separate_complete_account_scope_review',
      'itemized_settlement_components_and_current_account_snapshots',
    ],
    complete_account_coverage_proven: false,
    account_scope_bound: false,
    settlement_components_complete: false,
    current_account_snapshots_present: false,
    reviewed_query_windows_included: false,
    events_included: false,
    transaction_details_included: false,
    private_fields_included: false,
    source_names_included: false,
    paths_included: false,
    assessment_persisted: false,
    database_writes_performed: false,
    provider_contacted: false,
    eligible_for_account_truth: false,
    eligible_for_reconciliation: false,
    authorizes_execution: false,
    changes_capital_authority: false,
    limitations: [
      'Continuous declared windows do not prove complete account coverage.',
    ],
    assessment_fingerprint: `sha256:${'9'.repeat(64)}`,
  },
  source_scope_review_summary: {
    reviewed_source_count: 0,
    unreviewed_source_count: 1,
    all_current_sources_reviewed: false,
    same_account_binding_proven: false,
    declared_scope_consistent: false,
    complete_account_coverage_proven: false,
    eligible_for_account_truth: false,
    eligible_for_reconciliation: false,
  },
  source_scope_batch_assessment: {
    schema_version:
      'karkinos.account_truth.citic_source_scope_batch_assessment.v2',
    status: 'blocked',
    integrity_status: 'not_available',
    source_count: 1,
    reviewed_source_count: 0,
    unreviewed_source_count: 1,
    invalid_query_window_review_count: 0,
    invalid_scope_review_count: 0,
    all_current_sources_reviewed: false,
    account_binding_consistent: false,
    declared_scope_consistent: false,
    account_scope_bound: false,
    declared_source_scope_complete: false,
    no_other_filters_attested: false,
    complete_returned_results_attested: false,
    declared_account_type: null,
    declared_market_scopes: [],
    declared_asset_classes: [],
    declared_account_value_band: null,
    declared_business_types: [],
    blockers: [
      'citic_source_scope_batch_sources_unreviewed',
      'citic_source_scope_batch_complete_account_coverage_unproven',
    ],
    required_evidence: [
      'explicit_source_scope_review_for_each_current_source',
      'same_account_binding_for_all_current_sources',
      'consistent_declared_scope_for_all_current_sources',
    ],
    complete_account_coverage_proven: false,
    settlement_components_complete: false,
    current_account_snapshots_present: false,
    account_reference_hashes_included: false,
    source_names_included: false,
    paths_included: false,
    events_included: false,
    transaction_details_included: false,
    assessment_persisted: false,
    database_writes_performed: false,
    provider_contacted: false,
    eligible_for_account_truth: false,
    eligible_for_reconciliation: false,
    authorizes_execution: false,
    changes_capital_authority: false,
    limitations: [
      'Declared source scope does not prove complete account coverage.',
    ],
    assessment_fingerprint: `sha256:${'4'.repeat(64)}`,
  },
  items: [
    {
      ...citicHistoryXlsPreview,
      local_name_month_hint: '2026-05',
      local_name_month_hint_is_evidence: false,
      query_window_inferred: false,
      source_intake: null,
    },
  ],
};

const collectorStatus = {
  schema_version: 'karkinos.account_truth.local_broker_statement_collector.v1',
  enabled: true,
  state: 'unchanged',
  configured_path: 'broker_statement.csv',
  source_name: 'broker_statement.csv',
  file_present: true,
  poll_interval_seconds: 5,
  stability_delay_seconds: 2,
  max_file_bytes: 10485760,
  last_observed_at: '2026-07-17T14:30:00Z',
  last_processed_at: '2026-07-17T14:29:58Z',
  last_success_at: '2026-07-17T14:29:58Z',
  file_fingerprint: 'sha256-local',
  import_run_id: 'import-run-1',
  validation_status: 'pass',
  row_count: 3,
  valid_row_count: 3,
  invalid_row_count: 0,
  duplicate_row_count: 0,
  error_code: null,
  message: 'unchanged',
  source_kind: 'local_file_readonly',
  does_not_mutate_production_ledger: true,
  does_not_contact_provider: true,
  does_not_change_execution_authority: true,
};

const feeScheduleReviewStatus = {
  status: 'missing',
  review: null,
  blockers: ['reviewed_fee_schedule_review_missing'],
  current_preview_fingerprint: null,
  authorizes_execution: false,
  changes_capital_authority: false,
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installFetchMock({
  evidenceReadinessResponse = evidenceReadiness,
  scoreResponse = score,
  importRunResponse = importRuns,
  reportSummaryResponse = reportSummaries,
  reportDetailResponse = reportDetail,
  collectorStatusResponse = collectorStatus,
  citicDirectoryStatusResponse = citicDirectoryStatus,
  citicDirectoryScanResponse = citicDirectoryScan,
  citicDirectoryIntakePostResponse = citicSourceIntake,
  citicDirectoryQueryWindowPostResponse = citicQueryWindowReviewCommand,
  citicPreviewResponses = [citicHistoryXlsPreview],
  citicIntakesResponse = [],
  citicIntakePostResponse = citicSourceIntake,
  citicQueryWindowPostResponse = citicQueryWindowReviewCommand,
  citicQueryWindowRevokePostResponse = {
    ...citicQueryWindowReviewCommand,
    status: 'revoked',
    review: {
      ...citicQueryWindowReview,
      decision: 'revoked',
      effective_status: 'revoked',
    },
  },
  citicSourceScopePostResponse = citicSourceScopeReviewCommand,
  citicSourceScopeRevokePostResponse = {
    ...citicSourceScopeReviewCommand,
    status: 'revoked',
    review: {
      ...citicSourceScopeReview,
      decision: 'revoked',
      effective_status: 'revoked',
    },
  },
  evidenceScopeReviewPostResponse = evidenceScopeReviewCommand,
}: {
  evidenceReadinessResponse?: unknown;
  scoreResponse?: unknown;
  importRunResponse?: unknown;
  reportSummaryResponse?: unknown;
  reportDetailResponse?: unknown;
  collectorStatusResponse?: unknown;
  citicDirectoryStatusResponse?: unknown;
  citicDirectoryScanResponse?: unknown | Response;
  citicDirectoryIntakePostResponse?: unknown | Response;
  citicDirectoryQueryWindowPostResponse?: unknown | Response;
  citicPreviewResponses?: Array<unknown | Response>;
  citicIntakesResponse?: unknown;
  citicIntakePostResponse?: unknown | Response;
  citicQueryWindowPostResponse?: unknown | Response;
  citicQueryWindowRevokePostResponse?: unknown | Response;
  citicSourceScopePostResponse?: unknown | Response;
  citicSourceScopeRevokePostResponse?: unknown | Response;
  evidenceScopeReviewPostResponse?: unknown | Response;
} = {}) {
  let citicPreviewIndex = 0;
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();
      if (url.includes('/api/account-truth/evidence-readiness')) {
        return jsonResponse(await evidenceReadinessResponse);
      }
      if (url.includes('/api/account-truth/fee-schedule/review')) {
        return jsonResponse(feeScheduleReviewStatus);
      }
      if (url.includes('/api/account-truth/evidence-scope/reviews')) {
        return evidenceScopeReviewPostResponse instanceof Response
          ? evidenceScopeReviewPostResponse
          : jsonResponse(evidenceScopeReviewPostResponse);
      }
      if (url.includes('/api/account-truth/score')) {
        return jsonResponse(await scoreResponse);
      }
      if (url.includes('/api/account-truth/broker-statement/collector')) {
        return jsonResponse(collectorStatusResponse);
      }
      if (
        url.includes('/api/account-truth/citic-history-xls/directory/intakes')
      ) {
        return citicDirectoryIntakePostResponse instanceof Response
          ? citicDirectoryIntakePostResponse
          : jsonResponse(citicDirectoryIntakePostResponse);
      }
      if (
        url.includes(
          '/api/account-truth/citic-history-xls/directory/query-window-reviews',
        )
      ) {
        return citicDirectoryQueryWindowPostResponse instanceof Response
          ? citicDirectoryQueryWindowPostResponse
          : jsonResponse(citicDirectoryQueryWindowPostResponse);
      }
      if (url.includes('/api/account-truth/citic-history-xls/directory/scan')) {
        return citicDirectoryScanResponse instanceof Response
          ? citicDirectoryScanResponse
          : jsonResponse(citicDirectoryScanResponse);
      }
      if (url.includes('/api/account-truth/citic-history-xls/directory')) {
        return jsonResponse(citicDirectoryStatusResponse);
      }
      if (url.includes('/api/account-truth/citic-history-xls/preview')) {
        const response =
          citicPreviewResponses[
            Math.min(citicPreviewIndex, citicPreviewResponses.length - 1)
          ];
        citicPreviewIndex += 1;
        return response instanceof Response ? response : jsonResponse(response);
      }
      if (
        url.includes(
          '/api/account-truth/citic-history-xls/source-scope-reviews/revoke',
        )
      ) {
        return citicSourceScopeRevokePostResponse instanceof Response
          ? citicSourceScopeRevokePostResponse
          : jsonResponse(citicSourceScopeRevokePostResponse);
      }
      if (
        url.includes(
          '/api/account-truth/citic-history-xls/source-scope-reviews',
        )
      ) {
        return citicSourceScopePostResponse instanceof Response
          ? citicSourceScopePostResponse
          : jsonResponse(citicSourceScopePostResponse);
      }
      if (
        url.includes(
          '/api/account-truth/citic-history-xls/query-window-reviews/revoke',
        )
      ) {
        return citicQueryWindowRevokePostResponse instanceof Response
          ? citicQueryWindowRevokePostResponse
          : jsonResponse(citicQueryWindowRevokePostResponse);
      }
      if (
        url.includes(
          '/api/account-truth/citic-history-xls/query-window-reviews',
        )
      ) {
        return citicQueryWindowPostResponse instanceof Response
          ? citicQueryWindowPostResponse
          : jsonResponse(citicQueryWindowPostResponse);
      }
      if (url.includes('/api/account-truth/citic-history-xls/intakes')) {
        if (init?.method === 'POST') {
          return citicIntakePostResponse instanceof Response
            ? citicIntakePostResponse
            : jsonResponse(citicIntakePostResponse);
        }
        return jsonResponse(citicIntakesResponse);
      }
      if (url.includes('/api/account-truth/broker-statement/preview')) {
        return jsonResponse(brokerStatementPreview);
      }
      if (url.includes('/api/account-truth/broker-statement/import')) {
        return jsonResponse({
          import_run: {
            ...importRuns[0],
            import_run_id: 'import-run-new',
            source_name: 'local-broker-statement.csv',
          },
          preview: brokerStatementPreview,
          report: {
            ...reportSummaries[0],
            import_run_id: 'import-run-new',
            source_name: 'local-broker-statement.csv',
          },
          does_not_mutate_production_ledger: true,
        });
      }
      if (url.includes('/api/account-truth/import-runs')) {
        return jsonResponse(await importRunResponse);
      }
      if (
        url.includes(
          '/api/account-truth/reconciliation-reports/import-run-1',
        ) &&
        init?.method !== 'POST'
      ) {
        return jsonResponse(reportDetailResponse);
      }
      if (
        url.includes('/api/account-truth/reconciliation-reports') &&
        init?.method !== 'POST'
      ) {
        return jsonResponse(await reportSummaryResponse);
      }
      if (url.includes('/items/position%3ASYN001/review')) {
        return jsonResponse({
          id: 7,
          import_run_id: 'import-run-1',
          item_key: 'position:SYN001',
          category: 'position',
          symbol: 'SYN001',
          review_status: 'known_difference',
          note: 'Reviewed from Account Truth center.',
          reviewer: 'local',
          schema_version: 'karkinos.account_truth.manual_review.v1',
          created_at: '2026-06-18T10:12:00+08:00',
          updated_at: '2026-06-18T10:12:00+08:00',
          does_not_mutate_production_ledger: true,
        });
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderAccountTruthReviewPage(
  fetchOptions?: Parameters<typeof installFetchMock>[0],
  renderOptions: RenderOptions = {},
) {
  window.localStorage.clear();
  if (renderOptions.locale) {
    window.localStorage.setItem('karkinos.locale', renderOptions.locale);
  }
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installFetchMock(fetchOptions);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <AccountTruthReviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

async function completeCiticSourceScopeReview(
  previewTool: HTMLElement,
  { startDate = '2026-05-01', endDate = '2026-05-31' } = {},
) {
  await userEvent.type(
    within(previewTool).getByLabelText('Broker query start date'),
    startDate,
  );
  await userEvent.type(
    within(previewTool).getByLabelText('Broker query end date'),
    endDate,
  );
  await userEvent.type(
    within(previewTool).getByLabelText(/Local account alias/),
    'citic-primary',
  );
  await userEvent.type(
    within(previewTool).getByLabelText(/Broker account identifier/),
    'raw-citic-account-123',
  );
  await userEvent.type(
    within(previewTool).getByLabelText(/Account type code/),
    'cash',
  );
  await userEvent.type(
    within(previewTool).getByLabelText(/Market scopes/),
    'shanghai_a, shenzhen_a',
  );
  await userEvent.type(
    within(previewTool).getByLabelText(/Asset classes/),
    'stock',
  );
  await userEvent.type(
    within(previewTool).getByLabelText(/Account-value band code/),
    'cny_0_20000',
  );
  await userEvent.click(
    within(previewTool).getByLabelText(
      /I personally checked that this exact file was exported/,
    ),
  );
  await userEvent.click(
    within(previewTool).getByLabelText(/no other broker query filters/),
  );
  await userEvent.click(
    within(previewTool).getByLabelText(/contains every row returned/),
  );
  await userEvent.click(
    within(previewTool).getByLabelText(
      /account, account type, market, asset, account-value band, and business scope/,
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the current persisted report detail while report history loads', async () => {
  let resolveReportSummaries: (value: unknown) => void = () => undefined;
  const pendingReportSummaries = new Promise<unknown>((resolve) => {
    resolveReportSummaries = resolve;
  });

  const { fetchMock } = renderAccountTruthReviewPage({
    reportSummaryResponse: pendingReportSummaries,
  });

  expect(await screen.findByText('42')).toBeTruthy();
  expect(
    await screen.findByTestId('account-truth-current-report'),
  ).toBeTruthy();
  expect(screen.queryByTestId('account-truth-reports-loading')).toBeNull();
  expect(
    document.querySelector(
      '[data-workbench-primitive="evidence-loading-layout"]',
    ),
  ).toBeNull();
  expect(screen.queryByText('0 items')).toBeNull();
  expect(
    screen.queryByText('No reconciliation reports for this filter.'),
  ).toBeNull();
  const requestedReportPaths = fetchMock.mock.calls.map(([input]) =>
    String(input),
  );
  const detailRequestIndex = requestedReportPaths.findIndex((path) =>
    path.includes('/api/account-truth/reconciliation-reports/import-run-1'),
  );
  const historyRequestIndex = requestedReportPaths.findIndex(
    (path) =>
      path.endsWith('/api/account-truth/reconciliation-reports') ||
      path === '/api/account-truth/reconciliation-reports',
  );
  expect(detailRequestIndex).toBeGreaterThanOrEqual(0);
  expect(historyRequestIndex).toBeGreaterThan(detailRequestIndex);

  resolveReportSummaries(reportSummaries);

  expect(
    await screen.findByText(
      'Cash difference ¥120.00 · Fee difference ¥0.00 · Tax difference ¥2.50',
    ),
  ).toBeTruthy();
  expect(screen.queryByTestId('account-truth-reports-loading')).toBeNull();
});

test('defers the slower report read until persisted summary projections resolve', async () => {
  let resolveReadiness: (value: unknown) => void = () => undefined;
  const pendingReadiness = new Promise<unknown>((resolve) => {
    resolveReadiness = resolve;
  });

  const { fetchMock } = renderAccountTruthReviewPage({
    evidenceReadinessResponse: pendingReadiness,
  });
  const requestedPaths = () =>
    fetchMock.mock.calls.map(
      ([input]) =>
        new URL(
          typeof input === 'string'
            ? input
            : input instanceof Request
              ? input.url
              : input.toString(),
          'http://localhost',
        ).pathname,
    );

  await waitFor(() =>
    expect(requestedPaths()).toContain('/api/account-truth/evidence-readiness'),
  );
  expect(requestedPaths()).not.toContain(
    '/api/account-truth/reconciliation-reports',
  );

  resolveReadiness(evidenceReadiness);

  await waitFor(() =>
    expect(requestedPaths()).toContain(
      '/api/account-truth/reconciliation-reports',
    ),
  );
});

test('renders Account Truth score, import runs, reconciliation detail, and review actions', async () => {
  const { fetchMock } = renderAccountTruthReviewPage();

  expect(await screen.findByText('Account Truth Review Center')).toBeTruthy();
  expect(
    document.querySelector('[data-workbench-route="account-truth"]'),
  ).toBeTruthy();
  expect(
    document.querySelector('[data-workbench-primitive="workspace-header"]'),
  ).toBeTruthy();
  expect(await screen.findByText('42')).toBeTruthy();
  expect(
    document.querySelector('[data-workbench-primitive="metric-strip"]'),
  ).toBeTruthy();
  const readinessDisclosure = await screen.findByTestId(
    'account-truth-evidence-readiness-disclosure',
  );
  expect(
    within(readinessDisclosure).getByText('Evidence requirements'),
  ).toBeTruthy();
  expect(
    within(readinessDisclosure).getByText('Persisted incomplete sources: 4'),
  ).toBeTruthy();
  expect(
    within(readinessDisclosure).getByTestId(
      'account-truth-citic-query-window-integrity',
    ).textContent,
  ).toContain('Query-window integrity: Blocked · gap days 1 · overlap days 0');
  expect(
    within(readinessDisclosure).getByText('Canonical broker evidence'),
  ).toBeTruthy();
  expect(
    within(readinessDisclosure).getByText('Current position snapshot'),
  ).toBeTruthy();
  expect(
    within(readinessDisclosure).getByText('Reviewed account and period scope'),
  ).toBeTruthy();
  const positionRequirement = within(readinessDisclosure).getByTestId(
    'account-truth-readiness-item-current_position_snapshot',
  );
  expect(
    within(positionRequirement).getByText('Supporting evidence'),
  ).toBeTruthy();
  expect(
    within(positionRequirement).getByText(
      'Account Truth score · Position component',
    ),
  ).toBeTruthy();
  expect(within(positionRequirement).getByText('Safe next step')).toBeTruthy();
  expect(
    within(positionRequirement).getByText(
      'Provide a current position snapshot',
    ),
  ).toBeTruthy();
  const positionAction = within(positionRequirement).getByRole('link', {
    name: 'Provide a current position snapshot',
  });
  expect(positionAction.getAttribute('href')).toBe(
    '#account-truth-import-tools',
  );
  expect(positionAction.getAttribute('aria-controls')).toBe(
    'account-truth-import-tools',
  );
  const importToolsDisclosure = screen.getByTestId(
    'account-truth-import-tools-disclosure',
  ) as HTMLDetailsElement;
  expect(importToolsDisclosure.open).toBe(false);
  await userEvent.click(positionAction);
  expect(importToolsDisclosure.open).toBe(true);
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
    false,
  );
  const scopeRequirement = within(readinessDisclosure).getByTestId(
    'account-truth-readiness-item-reviewed_account_and_period_scope',
  );
  const scopeAction = within(scopeRequirement).getByRole('link', {
    name: 'Bind the evidence to a reviewed account scope',
  });
  expect(scopeAction.getAttribute('href')).toBe(
    '#account-truth-evidence-scope-review',
  );
  expect(
    document.getElementById('account-truth-evidence-scope-review'),
  ).toBeTruthy();
  const evidenceScope = within(readinessDisclosure).getByTestId(
    'account-truth-evidence-scope',
  );
  expect(
    within(evidenceScope).getByText('Provable evidence scope'),
  ).toBeTruthy();
  expect(
    within(evidenceScope).getByText(
      '2026-01-05 – 2026-01-15 · 3 persisted rows',
    ),
  ).toBeTruthy();
  expect(within(evidenceScope).getByText('Stock')).toBeTruthy();
  expect(
    within(evidenceScope).getByText('Cash 2026-01-15 · Position 2026-01-15'),
  ).toBeTruthy();
  expect(
    within(readinessDisclosure).getAllByText('Review position difference')
      .length,
  ).toBeGreaterThan(0);
  expect(readinessDisclosure.textContent).toContain(
    'does not import evidence, contact a broker, reconcile the account, or grant execution or capital authority',
  );
  await waitFor(() =>
    expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0),
  );
  const scoreDisclosure = await screen.findByTestId(
    'account-truth-score-disclosure',
  );
  expect(within(scoreDisclosure).getByText('Cash')).toBeTruthy();
  expect(within(scoreDisclosure).getByText('Cost basis')).toBeTruthy();
  expect(
    within(scoreDisclosure).getAllByText('Mismatch').length,
  ).toBeGreaterThanOrEqual(3);
  expect(
    (await screen.findAllByText('Review position difference')).length,
  ).toBeGreaterThan(0);
  await waitFor(() =>
    expect(
      screen.getAllByText('synthetic-safe-example.csv').length,
    ).toBeGreaterThan(0),
  );
  expect(
    await screen.findByText(
      'Cash difference ¥120.00 · Fee difference ¥0.00 · Tax difference ¥2.50',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('Cash difference 120.00')).toBeNull();
  expect(screen.queryByText('Tax difference 2.50')).toBeNull();
  expect(screen.queryByText(/cash Δ/)).toBeNull();
  expect(screen.queryByText(/fee Δ/)).toBeNull();
  expect(await screen.findByText('Rows 3 · duplicates 0')).toBeTruthy();

  await userEvent.click(screen.getByRole('button', { name: 'Mismatch' }));

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('status=mismatch'),
      ),
    ).toBe(true);
  });

  const item = await screen.findByTestId('account-truth-item-position:SYN001');
  expect(within(item).getByText('合成样例股票A SYN001')).toBeTruthy();
  expect(within(item).getByText('Position')).toBeTruthy();
  expect(within(item).queryByText('position')).toBeNull();
  expect(within(item).getByText('Broker 100 shares')).toBeTruthy();
  expect(within(item).getByText('Karkinos 0 shares')).toBeTruthy();
  expect(within(item).getByText('Difference 100 shares')).toBeTruthy();
  expect(item.textContent).not.toContain(
    'broker_event:import-run-1:SYN001:position_snapshot',
  );
  await userEvent.click(
    within(item).getByRole('button', { name: 'Open evidence detail' }),
  );
  expect(
    screen.getByText(
      'Broker evidence · 合成样例股票A SYN001 · Position snapshot · import-run-1',
    ),
  ).toBeTruthy();
  await userEvent.click(
    screen.getAllByRole('button', { name: 'Close evidence detail' })[1],
  );
  expect(
    within(item).getByRole('button', { name: 'Create ledger candidate' }),
  ).toBeTruthy();
  expect(
    within(item).queryByRole('button', { name: 'Ledger candidate' }),
  ).toBeNull();

  await userEvent.click(
    within(item).getByRole('button', { name: 'Mark known difference' }),
  );

  await waitFor(() => {
    const postCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).includes('/items/position%3ASYN001/review') &&
        init?.method === 'POST',
    );
    expect(postCall).toBeTruthy();
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      category: 'position',
      symbol: 'SYN001',
      review_status: 'known_difference',
      reviewer: 'local',
    });
  });
  expect(
    await screen.findByText('Review saved: Known difference'),
  ).toBeTruthy();
  expect(screen.queryByText('Review saved: known_difference')).toBeNull();
});

test('keeps missing readiness evidence and its safe next step together', async () => {
  renderAccountTruthReviewPage({
    evidenceReadinessResponse: {
      ...evidenceReadiness,
      account_truth_import_run_id: null,
      items: [
        {
          requirement: 'canonical_broker_evidence',
          status: 'missing',
          evidence_reference: null,
          required_action: 'import_and_reconcile_broker_evidence',
        },
        {
          requirement: 'reviewed_account_and_period_scope',
          status: 'blocked',
          evidence_reference: null,
          required_action:
            'bind_account_truth_evidence_to_reviewed_account_scope',
        },
        {
          requirement: 'reconciliation_gate',
          status: 'blocked',
          evidence_reference: 'account_truth_score:latest',
          required_action: 'resolve_account_truth_blockers',
        },
      ],
    },
  });

  const requirement = await screen.findByTestId(
    'account-truth-readiness-item-canonical_broker_evidence',
  );
  expect(within(requirement).getByText('No persisted evidence')).toBeTruthy();
  expect(
    within(requirement).getByText(
      'Import broker evidence and run reconciliation',
    ),
  ).toBeTruthy();
  const scopeRequirement = screen.getByTestId(
    'account-truth-readiness-item-reviewed_account_and_period_scope',
  );
  expect(
    within(scopeRequirement)
      .getByRole('link', {
        name: 'Bind the evidence to a reviewed account scope',
      })
      .getAttribute('href'),
  ).toBe('#account-truth-import-tools');
  const reconciliationRequirement = screen.getByTestId(
    'account-truth-readiness-item-reconciliation_gate',
  );
  expect(
    within(reconciliationRequirement)
      .getByRole('link', { name: 'Resolve Account Truth blockers' })
      .getAttribute('href'),
  ).toBe('#account-truth-review-workspace');
  expect(
    document.getElementById('account-truth-review-workspace'),
  ).toBeTruthy();
});

test('prioritizes blocked evidence readiness over a passing reconciliation score', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAccountTruthReviewPage({
    scoreResponse: {
      ...score,
      score: 100,
      gate_status: 'pass',
      cash_status: 'pass',
      position_status: 'pass',
      cost_basis_status: 'pass',
      unresolved_mismatch_count: 0,
      blocking_reasons: [],
      required_actions: [],
    },
    evidenceReadinessResponse: {
      ...evidenceReadiness,
      account_truth_gate_status: 'pass',
      items: [
        {
          requirement: 'canonical_broker_evidence',
          status: 'pass',
          evidence_reference: 'account_truth_import:import-run-1',
          required_action: null,
        },
        {
          requirement: 'reviewed_account_and_period_scope',
          status: 'blocked',
          evidence_reference: 'account_truth_evidence_scope:sha256-scope',
          required_action:
            'bind_account_truth_evidence_to_reviewed_account_scope',
        },
        {
          requirement: 'reconciliation_gate',
          status: 'pass',
          evidence_reference: 'account_truth_score:latest',
          required_action: null,
        },
      ],
      blockers: ['account_truth_account_scope_unbound'],
      required_actions: [
        'bind_account_truth_evidence_to_reviewed_account_scope',
      ],
      known_incomplete_source_count: 0,
      next_manual_action:
        'bind_account_truth_evidence_to_reviewed_account_scope',
    },
  });

  const priority = await screen.findByTestId(
    'account-truth-readiness-priority',
  );
  expect(priority.querySelector('[data-evidence-kind="partial"]')).toBeTruthy();
  expect(priority.textContent).toContain('Account evidence is not ready');
  expect(priority.textContent).toContain(
    'A passing reconciliation score does not clear those missing requirements.',
  );
  expect(priority.textContent).toContain(
    'Next safe action: Bind the evidence to a reviewed account scope',
  );
  expect(screen.getByText('Reconciliation score')).toBeTruthy();
  expect(screen.getByText('Reconciliation gate: Pass')).toBeTruthy();

  const disclosure = document.getElementById(
    'account-truth-evidence-readiness-disclosure',
  ) as HTMLDetailsElement;
  disclosure.open = false;
  await user.click(
    within(priority).getByRole('link', {
      name: 'Review evidence requirements',
    }),
  );
  expect(disclosure.open).toBe(true);
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
    false,
  );
});

test('explains the same blocked-over-pass boundary in Chinese', async () => {
  renderAccountTruthReviewPage(
    {
      scoreResponse: {
        ...score,
        score: 100,
        gate_status: 'pass',
        cash_status: 'pass',
        position_status: 'pass',
        cost_basis_status: 'pass',
        unresolved_mismatch_count: 0,
        blocking_reasons: [],
        required_actions: [],
      },
      evidenceReadinessResponse: {
        ...evidenceReadiness,
        account_truth_gate_status: 'pass',
        blockers: ['account_truth_account_scope_unbound'],
        required_actions: [
          'bind_account_truth_evidence_to_reviewed_account_scope',
        ],
        known_incomplete_source_count: 0,
        next_manual_action:
          'bind_account_truth_evidence_to_reviewed_account_scope',
      },
    },
    { locale: 'zh' },
  );

  const priority = await screen.findByTestId(
    'account-truth-readiness-priority',
  );
  expect(priority.textContent).toContain('账户证据尚未就绪');
  expect(priority.textContent).toContain(
    '局部对账分数通过，不能清除这些证据缺失。',
  );
  expect(priority.textContent).toContain(
    '下一步安全动作: 将证据绑定到已复核账户范围',
  );
  expect(screen.getByText('对账分数')).toBeTruthy();
  expect(screen.getByText('对账门禁: 通过')).toBeTruthy();
});

test('hashes the private account identifier locally before recording scope review', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderAccountTruthReviewPage();
  const form = await screen.findByTestId(
    'account-truth-evidence-scope-review-form',
  );
  const privateAccountIdentifier = 'private-account-62220001';

  await user.type(
    within(form).getByTestId('account-truth-scope-account-alias'),
    'CITIC primary',
  );
  await user.type(
    within(form).getByTestId('account-truth-scope-account-identifier'),
    privateAccountIdentifier,
  );
  await user.click(within(form).getByTestId('account-truth-scope-attestation'));
  await user.click(
    within(form).getByRole('button', { name: 'Record scope review' }),
  );

  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('/api/account-truth/evidence-scope/reviews'),
      ),
    ).toBe(true),
  );
  const scopeCall = fetchMock.mock.calls.find(([input]) =>
    String(input).includes('/api/account-truth/evidence-scope/reviews'),
  );
  const requestBody = String(scopeCall?.[1]?.body ?? '');
  const payload = JSON.parse(requestBody) as Record<string, unknown>;

  expect(requestBody).not.toContain(privateAccountIdentifier);
  expect(payload).not.toHaveProperty('account_identifier');
  expect(payload.account_alias).toBe('CITIC primary');
  expect(payload.account_reference_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  expect(payload.coverage_start_date).toBe('2026-01-05');
  expect(payload.coverage_end_date).toBe('2026-01-15');
  expect(payload.asset_classes).toEqual(['stock']);
  expect(
    (
      within(form).getByTestId(
        'account-truth-scope-account-identifier',
      ) as HTMLInputElement
    ).value,
  ).toBe('');
  expect(form.textContent).toContain(
    'The identifier is hashed in this browser. The raw value is never sent to the API or persisted.',
  );
});

test('revokes a completed scope review without sending account identity', async () => {
  const user = userEvent.setup();
  const completeReadiness = {
    ...evidenceReadiness,
    evidence_scope: {
      ...evidenceReadiness.evidence_scope,
      status: 'complete',
      account_binding: {
        status: 'bound',
        provider: 'citic',
        account_alias: 'CITIC primary',
        account_reference_hash: 'sha256:' + 'c'.repeat(64),
      },
      declared_coverage_window: {
        status: 'complete',
        start_date: '2026-01-01',
        end_date: '2026-01-31',
      },
      asset_scope: {
        ...evidenceReadiness.evidence_scope.asset_scope,
        status: 'complete',
        reviewed_asset_classes: ['stock'],
      },
      review: {
        schema_version: 'karkinos.account_truth.evidence_scope_review.v1',
        review_id: 'scope-review-1',
        decision: 'accepted',
        provider: 'citic',
        review_fingerprint: 'sha256:' + 'e'.repeat(64),
        reviewed_at: '2026-02-01T00:00:00Z',
      },
      blockers: [],
      required_actions: [],
    },
  };
  const revokedCommand = {
    ...evidenceScopeReviewCommand,
    status: 'revoked',
    review: {
      ...evidenceScopeReviewCommand.review,
      decision: 'revoked',
    },
    readiness: evidenceReadiness,
  };
  const { fetchMock } = renderAccountTruthReviewPage({
    evidenceReadinessResponse: completeReadiness,
    evidenceScopeReviewPostResponse: revokedCommand,
  });
  const complete = await screen.findByTestId(
    'account-truth-evidence-scope-review-complete',
  );
  const evidenceScope = screen.getByTestId('account-truth-evidence-scope');
  const assetScope = within(evidenceScope).getByTestId(
    'account-truth-evidence-scope-assets',
  );

  expect(
    within(complete).getByText('CITIC primary · 2026-01-01 – 2026-01-31'),
  ).toBeTruthy();
  expect(within(assetScope).getByText('Complete')).toBeTruthy();
  expect(within(assetScope).queryByText('Blocked')).toBeNull();
  await user.click(
    within(complete).getByRole('button', { name: 'Revoke scope review' }),
  );

  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes(
          '/api/account-truth/evidence-scope/reviews/revoke',
        ),
      ),
    ).toBe(true),
  );
  const revokeCall = fetchMock.mock.calls.find(([input]) =>
    String(input).includes('/api/account-truth/evidence-scope/reviews/revoke'),
  );
  const requestBody = String(revokeCall?.[1]?.body ?? '');
  expect(requestBody).not.toContain('CITIC primary');
  expect(requestBody).not.toContain('account_reference_hash');
});

test('keeps repeated reconciliation evidence rows as distinct selectable instances', async () => {
  const consoleError = vi
    .spyOn(console, 'error')
    .mockImplementation(() => undefined);
  renderAccountTruthReviewPage({
    reportDetailResponse: {
      ...reportDetail,
      items: [
        reportDetail.items[0],
        {
          ...reportDetail.items[0],
          detail: 'A second persisted broker event has the same review key.',
          evidence_references: [
            'broker_event:import-run-1:SYN001:position_snapshot:2',
          ],
        },
      ],
    },
  });

  const selectors = await screen.findAllByTestId(
    'account-truth-item-selector-position:SYN001',
  );
  expect(selectors).toHaveLength(2);
  expect(
    await screen.findAllByTestId('account-truth-item-position:SYN001'),
  ).toHaveLength(1);
  await userEvent.click(selectors[1]);
  expect(
    await screen.findByText(
      'A second persisted broker event has the same review key.',
    ),
  ).toBeTruthy();
  expect(
    consoleError.mock.calls.some((call) =>
      call.some((argument) =>
        String(argument).includes('Encountered two children with the same key'),
      ),
    ),
  ).toBe(false);
});

test('shows the enabled local collector as evidence-only automatic reading', async () => {
  renderAccountTruthReviewPage();

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);

  const status = await screen.findByTestId('broker-statement-collector-status');

  expect(within(status).getByText('Automatic local reader')).toBeTruthy();
  expect(await within(status).findByText('Up to date')).toBeTruthy();
  expect(
    within(status).getByText(
      'The fingerprint is unchanged; no duplicate run was created.',
    ),
  ).toBeTruthy();
  expect(status.textContent).not.toContain('broker_statement.csv');
  expect(status.textContent).not.toContain('import-run-1');
  await userEvent.click(
    within(status).getByRole('button', { name: 'Open evidence detail' }),
  );
  expect(screen.getByText('broker_statement.csv')).toBeTruthy();
  expect(screen.getByText('import-run-1')).toBeTruthy();
  expect(status.textContent).toContain(
    'Automatic reading never posts the ledger.',
  );
});

test('previews and stages broker evidence from pasted CSV', async () => {
  const { fetchMock } = renderAccountTruthReviewPage();

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);

  const wizard = await screen.findByTestId('account-truth-import-wizard');
  await userEvent.clear(within(wizard).getByLabelText('CSV content'));
  await userEvent.type(
    within(wizard).getByLabelText('CSV content'),
    brokerStatementCsv,
  );
  await userEvent.click(
    within(wizard).getByRole('button', { name: 'Preview' }),
  );

  expect(await within(wizard).findByText('Preview ready')).toBeTruthy();
  expect(within(wizard).getByText('Valid rows')).toBeTruthy();
  expect(within(wizard).getByText('Review item')).toBeTruthy();

  await userEvent.click(
    within(wizard).getByRole('button', {
      name: 'Stage evidence and reconcile',
    }),
  );

  expect(await within(wizard).findByText(/Evidence staged/)).toBeTruthy();
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/account-truth/broker-statement/preview'),
    ),
  ).toBe(true);
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/account-truth/broker-statement/import'),
    ),
  ).toBe(true);
});

test('scans the configured CITIC directory only on command and rechecks by fingerprint before review', async () => {
  const { fetchMock } = renderAccountTruthReviewPage({
    citicDirectoryStatusResponse: {
      ...citicDirectoryStatus,
      enabled: true,
      state: 'configured',
    },
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const scanButton = await within(previewTool).findByRole('button', {
    name: 'Scan configured directory',
  });

  expect(within(previewTool).queryByText('Configured source 1')).toBeNull();
  await userEvent.click(scanButton);

  expect(
    await within(previewTool).findByText('Configured source 1'),
  ).toBeTruthy();
  expect(previewTool.textContent).toContain(
    'Local filename month hint: 2026-05',
  );
  expect(previewTool.textContent).toContain(
    'Identification aid only. It does not prefill or prove the broker query window.',
  );
  expect(
    within(previewTool).getByText(
      '1 candidates · 1 unique previews · 0 duplicates',
    ),
  ).toBeTruthy();
  const batchAssessment = within(previewTool).getByTestId(
    'citic-directory-batch-assessment',
  );
  expect(
    within(batchAssessment).getByText(
      'File-set integrity clear; coverage unverified',
    ),
  ).toBeTruthy();
  expect(
    within(batchAssessment).getByText('Observed event months: 2026-05'),
  ).toBeTruthy();
  expect(
    within(batchAssessment).getByText(
      '2 unique events · 0 cross-file duplicates · 0 identity conflicts · 0 sources without financial events',
    ),
  ).toBeTruthy();
  expect(
    within(batchAssessment).getByText(
      '0 of 1 current source query windows explicitly reviewed',
    ),
  ).toBeTruthy();
  const queryWindowBatchAssessment = within(batchAssessment).getByTestId(
    'citic-query-window-batch-assessment',
  );
  expect(
    within(queryWindowBatchAssessment).getByText('No reviewed query windows'),
  ).toBeTruthy();
  expect(queryWindowBatchAssessment.textContent).toContain(
    'No current source has an explicitly reviewed query window.',
  );
  expect(queryWindowBatchAssessment.textContent).toContain(
    'Continuous dates do not prove full account or asset scope',
  );
  expect(batchAssessment.textContent).toContain(
    'Observed months do not prove exported query windows or complete coverage.',
  );
  const lineageAssessment = within(batchAssessment).getByTestId(
    'citic-canonical-lineage-assessment',
  );
  expect(
    within(lineageAssessment).getByText('Partial lineage; review required'),
  ).toBeTruthy();
  expect(lineageAssessment.textContent).toContain(
    '1 of 2 source events match canonical financial semantics',
  );
  expect(lineageAssessment.textContent).toContain(
    '0 preserve exact event identity',
  );
  expect(lineageAssessment.textContent).toContain(
    '0 of 2 broker-order identities are preserved',
  );
  expect(lineageAssessment.textContent).toContain(
    '2 comparable canonical events are outside this source batch',
  );
  expect(lineageAssessment.textContent).toContain(
    'Source types: Dividend 1 · Buy 1',
  );
  expect(lineageAssessment.textContent).toContain(
    'Canonical types: Buy 1 · Sell 2',
  );
  expect(lineageAssessment.textContent).toContain(
    'Matched types: Buy 1 · unmatched source types: Dividend 1 · canonical types outside this batch: Sell 2',
  );
  expect(lineageAssessment.textContent).toContain(
    'Broker-order identity present in source 2 · canonical 0',
  );
  expect(lineageAssessment.textContent).not.toContain('trade_buy');
  expect(lineageAssessment.textContent).not.toContain('trade_sell');
  expect(lineageAssessment.textContent).toContain(
    'Semantic similarity without preserved event identity is not canonical provenance',
  );
  expect(previewTool.textContent).not.toContain('/Users/private');
  expect(previewTool.textContent).not.toContain('private-history-trades.xls');
  expect(
    within(previewTool).getByText(
      /No browser File or path is retained. Final review re-scans/,
    ),
  ).toBeTruthy();

  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Review for follow-up record',
    }),
  );
  expect(
    fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).includes(
          '/api/account-truth/citic-history-xls/directory/intakes',
        ) && init?.method === 'POST',
    ),
  ).toHaveLength(0);

  const confirmButton = within(previewTool).getByRole('button', {
    name: 'Confirm review',
  });
  expect((confirmButton as HTMLButtonElement).disabled).toBe(true);
  const queryStart = within(previewTool).getByLabelText(
    'Broker query start date',
  );
  const queryEnd = within(previewTool).getByLabelText('Broker query end date');
  expect((queryStart as HTMLInputElement).value).toBe('');
  expect((queryEnd as HTMLInputElement).value).toBe('');
  await completeCiticSourceScopeReview(previewTool);

  await userEvent.click(confirmButton);
  expect(
    await within(previewTool).findByText('Source scope recorded'),
  ).toBeTruthy();

  const scanRequests = fetchMock.mock.calls.filter(([input]) =>
    String(input).includes(
      '/api/account-truth/citic-history-xls/directory/scan',
    ),
  );
  expect(scanRequests).toHaveLength(1);
  expect(scanRequests[0][1]?.method).toBe('POST');
  expect(scanRequests[0][1]?.body).toBeUndefined();
  const intakeRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes(
        '/api/account-truth/citic-history-xls/directory/intakes',
      ) && init?.method === 'POST',
  );
  expect(intakeRequests).toHaveLength(1);
  const requestBody = JSON.parse(String(intakeRequests[0][1]?.body));
  expect(requestBody).toEqual({
    expected_file_fingerprint: 'a'.repeat(64),
    review_status: 'follow_up_required',
  });
  expect(requestBody).not.toHaveProperty('content_base64');
  expect(requestBody).not.toHaveProperty('path');
  expect(requestBody).not.toHaveProperty('source_name');
  const queryWindowRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes(
        '/api/account-truth/citic-history-xls/directory/query-window-reviews',
      ) && init?.method === 'POST',
  );
  expect(queryWindowRequests).toHaveLength(1);
  expect(JSON.parse(String(queryWindowRequests[0][1]?.body))).toEqual({
    expected_file_fingerprint: 'a'.repeat(64),
    expected_source_preview_fingerprint: 'c'.repeat(64),
    query_start_date: '2026-05-01',
    query_end_date: '2026-05-31',
    query_window_attested: true,
  });
  expect(queryWindowRequests[0][1]?.body).not.toContain('path');
  expect(queryWindowRequests[0][1]?.body).not.toContain('source_name');
  const sourceScopeRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes(
        '/api/account-truth/citic-history-xls/source-scope-reviews',
      ) && init?.method === 'POST',
  );
  expect(sourceScopeRequests).toHaveLength(1);
  const sourceScopeBody = JSON.parse(String(sourceScopeRequests[0][1]?.body));
  expect(sourceScopeBody).toMatchObject({
    expected_file_fingerprint: 'a'.repeat(64),
    expected_source_preview_fingerprint: 'c'.repeat(64),
    expected_query_window_review_id: citicQueryWindowReview.review_id,
    expected_query_window_review_fingerprint:
      citicQueryWindowReview.review_fingerprint,
    account_alias: 'citic-primary',
    account_type: 'cash',
    market_scopes: ['shanghai_a', 'shenzhen_a'],
    asset_classes: ['stock'],
    account_value_band: 'cny_0_20000',
    business_types: ['history_trades'],
    no_other_filters_attested: true,
    complete_returned_results_attested: true,
    source_scope_attested: true,
  });
  expect(sourceScopeBody.account_reference_hash).toMatch(
    /^sha256:[0-9a-f]{64}$/,
  );
  expect(String(sourceScopeRequests[0][1]?.body)).not.toContain(
    'raw-citic-account-123',
  );
  expect(String(sourceScopeRequests[0][1]?.body)).not.toContain('path');
  expect(String(sourceScopeRequests[0][1]?.body)).not.toContain('source_name');
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/account-truth/broker-statement/import'),
    ),
  ).toBe(false);
});

test('shows contiguous declared query windows without claiming account coverage', async () => {
  renderAccountTruthReviewPage({
    citicDirectoryStatusResponse: {
      ...citicDirectoryStatus,
      enabled: true,
      state: 'configured',
    },
    citicDirectoryScanResponse: {
      ...citicDirectoryScan,
      query_window_review_summary: {
        ...citicDirectoryScan.query_window_review_summary,
        reviewed_source_count: 1,
        unreviewed_source_count: 0,
        all_current_sources_reviewed: true,
      },
      query_window_batch_assessment: {
        ...citicDirectoryScan.query_window_batch_assessment,
        integrity_status: 'clear',
        reviewed_source_count: 1,
        unreviewed_source_count: 0,
        all_current_sources_reviewed: true,
        declared_window_start_date: '2026-05-01',
        declared_window_end_date: '2026-05-31',
        covered_calendar_day_count: 31,
        declared_windows_contiguous: true,
        declared_windows_non_overlapping: true,
        reviewed_query_windows_included: true,
        blockers: [
          'citic_query_window_batch_complete_account_coverage_unproven',
        ],
        assessment_fingerprint: `sha256:${'8'.repeat(64)}`,
      },
      source_scope_review_summary: {
        ...citicDirectoryScan.source_scope_review_summary,
        reviewed_source_count: 1,
        unreviewed_source_count: 0,
        all_current_sources_reviewed: true,
        same_account_binding_proven: true,
        declared_scope_consistent: true,
      },
      source_scope_batch_assessment: {
        ...citicDirectoryScan.source_scope_batch_assessment,
        integrity_status: 'clear',
        reviewed_source_count: 1,
        unreviewed_source_count: 0,
        all_current_sources_reviewed: true,
        account_binding_consistent: true,
        declared_scope_consistent: true,
        account_scope_bound: true,
        declared_source_scope_complete: true,
        no_other_filters_attested: true,
        complete_returned_results_attested: true,
        declared_account_type: 'cash',
        declared_market_scopes: ['shanghai_a', 'shenzhen_a'],
        declared_asset_classes: ['stock'],
        declared_account_value_band: 'cny_0_20000',
        declared_business_types: ['history_trades'],
        blockers: [
          'citic_source_scope_batch_complete_account_coverage_unproven',
        ],
        assessment_fingerprint: `sha256:${'3'.repeat(64)}`,
      },
    },
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Scan configured directory',
    }),
  );

  const assessment = await within(previewTool).findByTestId(
    'citic-query-window-batch-assessment',
  );
  expect(
    within(assessment).getByText('Declared dates are contiguous'),
  ).toBeTruthy();
  expect(assessment.textContent).toContain(
    'Declared span 2026-05-01 — 2026-05-31 · 31 covered calendar days · 0 gap days · 0 overlap days',
  );
  expect(assessment.textContent).toContain(
    'Continuous dates do not prove full account or asset scope',
  );
  expect(assessment.textContent).not.toContain('Account Truth ready');
  const sourceScopeAssessment = within(previewTool).getByTestId(
    'citic-source-scope-batch-assessment',
  );
  expect(
    within(sourceScopeAssessment).getByText(
      'Declared source scopes are consistent',
    ),
  ).toBeTruthy();
  expect(sourceScopeAssessment.textContent).toContain(
    '1 of 1 sources reviewed · account binding consistent · declared scope consistent',
  );
  expect(sourceScopeAssessment.textContent).toContain(
    'Account type cash · markets shanghai_a, shenzhen_a · assets stock · account-value band cny_0_20000 · business types history_trades',
  );
  expect(sourceScopeAssessment.textContent).toContain(
    'does not prove complete account coverage',
  );
});

test('blocks configured-directory source decisions when no safe local month hint exists', async () => {
  renderAccountTruthReviewPage({
    citicDirectoryStatusResponse: {
      ...citicDirectoryStatus,
      enabled: true,
      state: 'configured',
    },
    citicDirectoryScanResponse: {
      ...citicDirectoryScan,
      source_name_month_hints_included: false,
      items: [
        {
          ...citicDirectoryScan.items[0],
          local_name_month_hint: null,
        },
      ],
    },
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Scan configured directory',
    }),
  );

  expect(
    await within(previewTool).findByText(
      /has no unambiguous YYYYMM filename token/,
    ),
  ).toBeTruthy();
  expect(
    within(previewTool).queryByRole('button', {
      name: 'Review for follow-up record',
    }),
  ).toBeNull();
  expect(
    within(previewTool).queryByRole('button', { name: 'Review and reject' }),
  ).toBeNull();
});

test('previews CITIC XLS files sequentially without exposing canonical staging', async () => {
  const { fetchMock } = renderAccountTruthReviewPage();

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);

  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const fileInput = within(previewTool).getByLabelText(
    'Choose CITIC history-trade XLS files',
  );
  await userEvent.upload(fileInput, [
    new File(['private account export one'], 'history-trades-01.xls', {
      type: 'application/vnd.ms-excel',
    }),
    new File(['private account export two'], 'history-trades-02.xls', {
      type: 'application/vnd.ms-excel',
    }),
  ]);
  const previewButton = within(previewTool).getByRole('button', {
    name: 'Preview selected CITIC XLS files',
  });
  await waitFor(() =>
    expect((previewButton as HTMLButtonElement).disabled).toBe(false),
  );
  await userEvent.click(previewButton);

  expect(
    await within(previewTool).findByText('Evidence is still incomplete'),
  ).toBeTruthy();
  expect(
    within(previewTool).getByText('Read-only batch preview complete'),
  ).toBeTruthy();
  expect(within(previewTool).getByText('history-trades-01.xls')).toBeTruthy();
  expect(within(previewTool).getByText('history-trades-02.xls')).toBeTruthy();
  expect(
    within(previewTool).getByText('Duplicate file — excluded from totals'),
  ).toBeTruthy();
  expect(within(previewTool).getByText('Recognized events')).toBeTruthy();
  expect(
    within(previewTool).getByText('Not eligible for broker soak'),
  ).toBeTruthy();
  expect(
    within(previewTool).getByText('Versioned read-only connector snapshot'),
  ).toBeTruthy();
  expect(
    screen.getByText(/^Preview only: no evidence is persisted/),
  ).toBeTruthy();
  expect(previewTool.textContent).not.toContain(
    'Private broker details must not be rendered.',
  );
  expect(
    within(previewTool).queryByRole('button', {
      name: 'Stage evidence and reconcile',
    }),
  ).toBeNull();

  const requests = fetchMock.mock.calls.filter(([input]) =>
    String(input).includes('/api/account-truth/citic-history-xls/preview'),
  );
  expect(requests).toHaveLength(2);
  for (const request of requests) {
    const requestBody = JSON.parse(String(request[1]?.body));
    expect(Object.keys(requestBody)).toEqual(['content_base64']);
    expect(requestBody).not.toHaveProperty('source_name');
    expect(String(request[1]?.body)).not.toContain('history-trades');
  }
  expect((fileInput as HTMLInputElement).files).toHaveLength(0);
  expect((previewButton as HTMLButtonElement).disabled).toBe(true);
});

test('separates reviewed non-financial CITIC activity from events and invalid rows', async () => {
  renderAccountTruthReviewPage({
    citicPreviewResponses: [
      {
        ...citicHistoryXlsPreview,
        row_count: 3,
        recognized_non_financial_activity_count: 1,
        errors: [
          ...citicHistoryXlsPreview.errors,
          {
            row_number: 4,
            code: 'citic_history_xls_non_financial_activity_ignored',
            message: 'Synthetic private-free provider activity.',
          },
        ],
        required_evidence: [
          ...citicHistoryXlsPreview.required_evidence,
          'review_non_financial_activity',
        ],
      },
    ],
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const fileInput = within(previewTool).getByLabelText(
    'Choose CITIC history-trade XLS files',
  );
  await userEvent.upload(
    fileInput,
    new File(['private account export'], 'history-trades-01.xls'),
  );
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Preview selected CITIC XLS files',
    }),
  );

  expect(
    await within(previewTool).findByText('Non-financial activities: 1'),
  ).toBeTruthy();
  expect(
    within(previewTool).getByText(
      '1 reviewed designated-trading activity was isolated without creating broker events.',
    ),
  ).toBeTruthy();
  expect(within(previewTool).getByText('Invalid rows: 0')).toBeTruthy();
  expect(
    within(previewTool).queryByRole('button', {
      name: 'Stage evidence and reconcile',
    }),
  ).toBeNull();
});

test('requires a second explicit confirmation before recording a CITIC follow-up source', async () => {
  const { fetchMock } = renderAccountTruthReviewPage();

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const fileInput = within(previewTool).getByLabelText(
    'Choose CITIC history-trade XLS files',
  );
  await userEvent.upload(
    fileInput,
    new File(['private account export'], 'history-trades-01.xls', {
      type: 'application/vnd.ms-excel',
    }),
  );
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Preview selected CITIC XLS files',
    }),
  );

  const reviewButton = await within(previewTool).findByRole('button', {
    name: 'Review for follow-up record',
  });
  await userEvent.click(reviewButton);
  expect(
    within(previewTool).getByText(
      /Record only this fingerprint, validation summary, and missing-evidence checklist/,
    ),
  ).toBeTruthy();
  expect(
    fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).includes(
          '/api/account-truth/citic-history-xls/intakes',
        ) && init?.method === 'POST',
    ),
  ).toHaveLength(0);

  const confirmButton = within(previewTool).getByRole('button', {
    name: 'Confirm review',
  });
  expect((confirmButton as HTMLButtonElement).disabled).toBe(true);
  expect(
    within(previewTool).getByText(
      /Dates stay blank until you enter them. They are not inferred/,
    ),
  ).toBeTruthy();
  await completeCiticSourceScopeReview(previewTool);

  await userEvent.click(confirmButton);

  expect(
    await within(previewTool).findByText('Source scope recorded'),
  ).toBeTruthy();
  const requests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes('/api/account-truth/citic-history-xls/intakes') &&
      init?.method === 'POST',
  );
  expect(requests).toHaveLength(1);
  const requestBody = JSON.parse(String(requests[0][1]?.body));
  expect(requestBody.expected_file_fingerprint).toBe('a'.repeat(64));
  expect(requestBody.review_status).toBe('follow_up_required');
  expect(requestBody.content_base64).toBeTruthy();
  expect(requestBody).not.toHaveProperty('source_name');
  expect(String(requests[0][1]?.body)).not.toContain('history-trades-01.xls');
  const queryWindowRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes(
        '/api/account-truth/citic-history-xls/query-window-reviews',
      ) &&
      !String(input).includes('/revoke') &&
      init?.method === 'POST',
  );
  expect(queryWindowRequests).toHaveLength(1);
  const queryWindowBody = JSON.parse(String(queryWindowRequests[0][1]?.body));
  expect(queryWindowBody).toMatchObject({
    expected_file_fingerprint: 'a'.repeat(64),
    expected_source_preview_fingerprint: 'c'.repeat(64),
    query_start_date: '2026-05-01',
    query_end_date: '2026-05-31',
    query_window_attested: true,
  });
  expect(queryWindowBody.content_base64).toBeTruthy();
  expect(String(queryWindowRequests[0][1]?.body)).not.toContain(
    'history-trades-01.xls',
  );
  const sourceScopeRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes(
        '/api/account-truth/citic-history-xls/source-scope-reviews',
      ) && init?.method === 'POST',
  );
  expect(sourceScopeRequests).toHaveLength(1);
  const sourceScopeBody = JSON.parse(String(sourceScopeRequests[0][1]?.body));
  expect(sourceScopeBody).toMatchObject({
    expected_query_window_review_id: citicQueryWindowReview.review_id,
    expected_query_window_review_fingerprint:
      citicQueryWindowReview.review_fingerprint,
    account_alias: 'citic-primary',
    account_type: 'cash',
    market_scopes: ['shanghai_a', 'shenzhen_a'],
    asset_classes: ['stock'],
    account_value_band: 'cny_0_20000',
    business_types: ['history_trades'],
    no_other_filters_attested: true,
    complete_returned_results_attested: true,
    source_scope_attested: true,
  });
  expect(sourceScopeBody.account_reference_hash).toMatch(
    /^sha256:[0-9a-f]{64}$/,
  );
  expect(String(sourceScopeRequests[0][1]?.body)).not.toContain(
    'raw-citic-account-123',
  );
  expect(previewTool.textContent).not.toContain('private account export');
});

test('shows persisted CITIC source reviews without local filenames or event details', async () => {
  renderAccountTruthReviewPage({
    citicIntakesResponse: [citicSourceIntake],
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const historySummary = await within(previewTool).findByText(
    'Persisted source-review queue',
  );
  await userEvent.click(historySummary.closest('summary')!);

  expect(
    within(previewTool).getByText('Follow-up source recorded'),
  ).toBeTruthy();
  expect(previewTool.textContent).toContain('a'.repeat(64));
  expect(previewTool.textContent).not.toContain('history-trades');
  expect(previewTool.textContent).not.toContain('SYN001');
});

test('keeps a saved source incomplete when query-window recording fails closed', async () => {
  const { fetchMock } = renderAccountTruthReviewPage({
    citicQueryWindowPostResponse: new Response(
      JSON.stringify({ detail: { code: 'query-window-rejected' } }),
      { status: 409 },
    ),
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  await userEvent.upload(
    within(previewTool).getByLabelText('Choose CITIC history-trade XLS files'),
    new File(['private account export'], 'history-trades-01.xls'),
  );
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Preview selected CITIC XLS files',
    }),
  );
  await userEvent.click(
    await within(previewTool).findByRole('button', {
      name: 'Review for follow-up record',
    }),
  );
  await completeCiticSourceScopeReview(previewTool);
  await userEvent.click(
    within(previewTool).getByRole('button', { name: 'Confirm review' }),
  );

  expect(
    await within(previewTool).findAllByText(
      'The source was recorded, but its query window was not recorded',
    ),
  ).toHaveLength(2);
  expect(previewTool.textContent).toContain(
    'The sanitized source review remains saved',
  );
  expect(
    within(previewTool).getByRole('button', {
      name: 'Review source query window',
    }),
  ).toBeTruthy();
  expect(
    fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).includes('/citic-history-xls/intakes') &&
        init?.method === 'POST',
    ),
  ).toHaveLength(1);
});

test('keeps a reviewed query window incomplete when source-scope recording fails closed', async () => {
  const { fetchMock } = renderAccountTruthReviewPage({
    citicSourceScopePostResponse: new Response(
      JSON.stringify({ detail: { code: 'source-scope-rejected' } }),
      { status: 409 },
    ),
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  await userEvent.upload(
    within(previewTool).getByLabelText('Choose CITIC history-trade XLS files'),
    new File(['private account export'], 'history-trades-01.xls'),
  );
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Preview selected CITIC XLS files',
    }),
  );
  await userEvent.click(
    await within(previewTool).findByRole('button', {
      name: 'Review for follow-up record',
    }),
  );
  await completeCiticSourceScopeReview(previewTool);
  await userEvent.click(
    within(previewTool).getByRole('button', { name: 'Confirm review' }),
  );

  expect(
    await within(previewTool).findAllByText(
      'The source and query window were recorded, but the source scope was not recorded',
    ),
  ).toHaveLength(2);
  expect(previewTool.textContent).toContain('2026-05-01 — 2026-05-31');
  expect(
    within(previewTool).getByRole('button', {
      name: 'Review source query and scope',
    }),
  ).toBeTruthy();
  expect(
    fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).includes('/query-window-reviews') &&
        !String(input).includes('/revoke') &&
        init?.method === 'POST',
    ),
  ).toHaveLength(1);
  expect(
    fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).includes('/source-scope-reviews') &&
        init?.method === 'POST',
    ),
  ).toHaveLength(1);
});

test('revokes a dependent source scope before its query window', async () => {
  const { fetchMock } = renderAccountTruthReviewPage({
    citicIntakesResponse: [
      {
        ...citicSourceIntake,
        query_window_review: citicQueryWindowReview,
        source_scope_review: citicSourceScopeReview,
      },
    ],
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const historySummary = await within(previewTool).findByText(
    'Persisted source-review queue',
  );
  await userEvent.click(historySummary.closest('summary')!);
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Revoke query-window review',
    }),
  );
  expect(
    fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/query-window-reviews/revoke'),
    ),
  ).toHaveLength(0);
  expect(
    fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/source-scope-reviews/revoke'),
    ),
  ).toHaveLength(0);

  await userEvent.click(
    within(previewTool).getByRole('button', { name: 'Confirm revocation' }),
  );

  const revokeRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes('/query-window-reviews/revoke') &&
      init?.method === 'POST',
  );
  expect(revokeRequests).toHaveLength(1);
  expect(JSON.parse(String(revokeRequests[0][1]?.body))).toEqual({
    intake_id: 'citic-intake-synthetic',
    expected_active_review_id: 'citic-window-review-synthetic',
    expected_active_review_fingerprint: `sha256:${'f'.repeat(64)}`,
  });
  const sourceScopeRevokeRequests = fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input).includes('/source-scope-reviews/revoke') &&
      init?.method === 'POST',
  );
  expect(sourceScopeRevokeRequests).toHaveLength(1);
  expect(JSON.parse(String(sourceScopeRevokeRequests[0][1]?.body))).toEqual({
    intake_id: 'citic-intake-synthetic',
    expected_active_review_id: 'citic-scope-review-synthetic',
    expected_active_review_fingerprint: `sha256:${'5'.repeat(64)}`,
  });
  const revocationUrls = fetchMock.mock.calls
    .filter(
      ([input, init]) =>
        String(input).includes('-reviews/revoke') && init?.method === 'POST',
    )
    .map(([input]) => String(input));
  expect(revocationUrls).toEqual([
    expect.stringContaining('/source-scope-reviews/revoke'),
    expect.stringContaining('/query-window-reviews/revoke'),
  ]);
});

test('isolates one CITIC XLS request failure and keeps the batch blocked', async () => {
  const { fetchMock } = renderAccountTruthReviewPage({
    citicPreviewResponses: [
      new Response('private upstream failure', { status: 500 }),
      {
        ...citicHistoryXlsPreview,
        file_fingerprint: 'b'.repeat(64),
        valid_row_count: 4,
        total_event_count: 4,
      },
    ],
  });

  const importToolsTitle = await screen.findByText('Stage new broker evidence');
  await userEvent.click(importToolsTitle.closest('summary')!);
  const previewTool = await screen.findByTestId(
    'account-truth-citic-xls-preview',
  );
  const fileInput = within(previewTool).getByLabelText(
    'Choose CITIC history-trade XLS files',
  );
  await userEvent.upload(fileInput, [
    new File(['first private export'], 'history-trades-01.xls'),
    new File(['second private export'], 'history-trades-02.xls'),
  ]);
  await userEvent.click(
    within(previewTool).getByRole('button', {
      name: 'Preview selected CITIC XLS files',
    }),
  );

  expect(
    await within(previewTool).findByText(
      'CITIC XLS preview failed: 1 file failed',
    ),
  ).toBeTruthy();
  expect(within(previewTool).getByText('Preview failed')).toBeTruthy();
  expect(within(previewTool).getByText('Checked')).toBeTruthy();
  expect(
    within(previewTool).getByText('Evidence is still incomplete'),
  ).toBeTruthy();
  expect(previewTool.textContent).not.toContain('private upstream failure');
  expect(
    fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/api/account-truth/citic-history-xls/preview'),
    ),
  ).toHaveLength(2);
});

test('localizes manual review action buttons as user actions in Chinese', async () => {
  renderAccountTruthReviewPage({}, { locale: 'zh' });

  const item = await screen.findByTestId('account-truth-item-position:SYN001');

  expect(
    within(item).getByRole('button', { name: '列为账本修正候选' }),
  ).toBeTruthy();
  expect(within(item).queryByRole('button', { name: '账本候选' })).toBeNull();
  expect(
    within(item).getByRole('button', { name: '标记为已知差异' }),
  ).toBeTruthy();
});

test('keeps observed Account Truth scope explicitly incomplete in Chinese', async () => {
  renderAccountTruthReviewPage({}, { locale: 'zh' });

  const readinessItem = await screen.findByTestId(
    'account-truth-readiness-item-current_position_snapshot',
  );
  expect(within(readinessItem).getByText('支持证据')).toBeTruthy();
  expect(
    within(readinessItem).getByText('账户事实评分 · 持仓分项'),
  ).toBeTruthy();
  expect(within(readinessItem).getByText('安全下一步')).toBeTruthy();
  expect(within(readinessItem).getByText('提供当前持仓快照')).toBeTruthy();
  const scope = await screen.findByTestId('account-truth-evidence-scope');
  expect(within(scope).getByText('可证明的证据范围')).toBeTruthy();
  expect(
    within(scope).getByText(
      '已观察到的记录只能说明文件里有什么，不能证明它完整覆盖了整个账户或完整时段。',
    ),
  ).toBeTruthy();
  expect(
    within(scope).getByText('2026-01-05 – 2026-01-15 · 持久化记录 3 条'),
  ).toBeTruthy();
  expect(within(scope).getByText('股票')).toBeTruthy();
});

test('localizes generated reconciliation detail copy in Chinese locale', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            detail_code: 'account_truth.position_quantity_compared',
            detail: 'Raw backend detail should not be visible.',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId('account-truth-item-position:SYN001');

  expect(
    within(item).getByText('券商持仓数量已与 Karkinos 本地持仓数量对比。'),
  ).toBeTruthy();
  expect(item.textContent).not.toContain('Raw backend detail');
});

test('localizes reconciliation detail codes that are review actions', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'fee:SYN001',
            category: 'fee',
            detail_code: 'review_fee_difference',
            detail: 'Raw review action detail should not be visible.',
            suggested_review_action: 'review_fee_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId('account-truth-item-fee:SYN001');

  expect(within(item).getAllByText('复核费用差异').length).toBeGreaterThan(0);
  expect(item.textContent).not.toContain('review_fee_difference');
  expect(item.textContent).not.toContain('Raw review action detail');
  expect(item.textContent).not.toContain('复核备注');
});

test('formats reconciliation report summary differences as money in Chinese locale', async () => {
  renderAccountTruthReviewPage(undefined, { locale: 'zh' });

  expect(
    await screen.findByText(
      '现金差异 ¥120.00 · 费用差异 ¥0.00 · 税费差异 ¥2.50',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('现金差异 120.00')).toBeNull();
  expect(screen.queryByText('税费差异 2.50')).toBeNull();
  expect(screen.queryByText(/cash Δ/)).toBeNull();
  expect(screen.queryByText(/fee Δ/)).toBeNull();
});

test('formats reconciliation values with category-aware units in Chinese locale', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
          },
          {
            ...reportDetail.items[0],
            item_key: 'cost_basis:SYN001',
            category: 'cost_basis',
            broker_value: '8.8',
            karkinos_value: '8.7',
            difference: '0.1',
            detail_code: 'account_truth.cost_basis_compared',
            detail: 'Broker cost basis does not match local ledger.',
            suggested_review_action: 'review_cost_basis_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const positionItem = await screen.findByTestId(
    'account-truth-item-position:SYN001',
  );
  expect(within(positionItem).getByText('券商 100 股')).toBeTruthy();
  expect(within(positionItem).getByText('Karkinos 0 股')).toBeTruthy();
  expect(within(positionItem).getByText('差异 100 股')).toBeTruthy();

  await userEvent.click(
    screen.getByTestId('account-truth-item-selector-cost_basis:SYN001'),
  );
  const costBasisItem = await screen.findByTestId(
    'account-truth-item-cost_basis:SYN001',
  );
  expect(within(costBasisItem).getByText('券商 ¥8.8000')).toBeTruthy();
  expect(within(costBasisItem).getByText('Karkinos ¥8.7000')).toBeTruthy();
  expect(within(costBasisItem).getByText('差异 ¥0.1000')).toBeTruthy();
  expect(within(costBasisItem).queryByText('券商 8.8')).toBeNull();
  expect(within(costBasisItem).queryByText('差异 0.1')).toBeNull();
});

test('localizes known reconciliation detail text when detail_code is missing', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'cost_basis:SYN001',
            category: 'cost_basis',
            broker_value: '8.8',
            karkinos_value: '8.7',
            difference: '0.1',
            detail_code: null,
            detail: 'Broker cost basis does not match local ledger.',
            suggested_review_action: 'review_cost_basis_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId(
    'account-truth-item-cost_basis:SYN001',
  );

  expect(
    within(item).getByText('券商成本价与 Karkinos 本地账本不一致。'),
  ).toBeTruthy();
  expect(item.textContent).not.toContain(
    'Broker cost basis does not match local ledger.',
  );
});

test('localizes latest review notes without showing backend operational text', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            latest_review: {
              id: 7,
              import_run_id: 'import-run-1',
              item_key: 'position:SYN001',
              category: 'position',
              symbol: 'SYN001',
              review_status: 'known_difference',
              note: 'Reviewed from Account Truth center.',
              reviewer: 'local',
              is_current: false,
              schema_version: 'karkinos.account_truth.manual_review.v1',
              created_at: '2026-06-18T10:12:00+08:00',
              updated_at: '2026-06-18T10:12:00+08:00',
              does_not_mutate_production_ledger: true,
            },
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId('account-truth-item-position:SYN001');

  expect(within(item).getByText('最近复核: 已知差异')).toBeTruthy();
  expect(within(item).getByText('复核已失效：对账事实已变化')).toBeTruthy();
  expect(
    within(item).getByText('已从账户事实复核中心记录人工处理。'),
  ).toBeTruthy();
  expect(item.textContent).not.toContain('Reviewed from Account Truth center.');
});

test('renders structured reconciliation detail context without raw codes', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'cost_basis:SYN001',
            category: 'cost_basis',
            detail_code: 'account_truth.cost_basis_compared',
            detail:
              'Broker per-share cost basis compared with Karkinos per-share cost basis. precision may differ because brokers can allocate fees, taxes, and transfer fees differently from local projections.',
            detail_context: {
              broker_cost_basis_method: 'broker_remaining_cost',
              karkinos_cost_basis_method: 'moving_average_buy_cost',
              comparison_unit: 'per_share_cost_basis',
              comparison_precision: 'decimal_string_no_rounding',
              precision_limitation:
                'broker_display_precision_fee_allocation_tax_timing_transfer_fee_rounding',
            },
            suggested_review_action: 'review_cost_basis_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId(
    'account-truth-item-cost_basis:SYN001',
  );

  expect(within(item).getByText('券商成本口径')).toBeTruthy();
  expect(within(item).getByText('券商剩余持仓成本')).toBeTruthy();
  expect(within(item).getByText('本地成本口径')).toBeTruthy();
  expect(within(item).getByText('移动平均买入成本')).toBeTruthy();
  expect(within(item).getByText('对比单位')).toBeTruthy();
  expect(within(item).getByText('单股成本价')).toBeTruthy();
  expect(within(item).getByText('对比精度')).toBeTruthy();
  expect(within(item).getByText('原始小数值')).toBeTruthy();
  expect(within(item).getByText('精度限制')).toBeTruthy();
  expect(
    within(item).getByText(
      '券商显示精度、费用分摊、税费确认与过户费舍入可能不同',
    ),
  ).toBeTruthy();
  expect(within(item).getByText('复核成本价差异')).toBeTruthy();
  expect(item.textContent).not.toContain('broker_remaining_cost');
  expect(item.textContent).not.toContain('moving_average_buy_cost');
  expect(item.textContent).not.toContain('per_share_cost_basis');
  expect(item.textContent).not.toContain('decimal_string_no_rounding');
  expect(item.textContent).not.toContain('Broker per-share cost basis');
  expect(item.textContent).not.toContain('未映射原因');
});

test('formats broker trade evidence references through shared ledger labels', async () => {
  renderAccountTruthReviewPage({
    reportDetailResponse: {
      ...reportDetail,
      items: [
        {
          ...reportDetail.items[0],
          item_key: 'trade:SYN001',
          category: 'trade_gross_amount',
          detail_code: 'account_truth.trade_gross_amount_compared',
          evidence_references: ['broker_event:import-run-1:SYN001:trade_buy'],
          suggested_review_action: 'review_trade_gross_amount_difference',
        },
      ],
    },
  });

  const item = await screen.findByTestId('account-truth-item-trade:SYN001');

  await userEvent.click(
    within(item).getByRole('button', { name: 'Open evidence detail' }),
  );
  expect(
    screen.getByText(
      'Broker evidence · 合成样例股票A SYN001 · Buy · import-run-1',
    ),
  ).toBeTruthy();
  expect(item.textContent).not.toContain('Buy trade');
  expect(item.textContent).not.toContain('trade_buy');
});

test('keeps matched rows quiet until the operator explicitly inspects them', async () => {
  const matchedItems = [
    {
      ...reportDetail.items[0],
      item_key: 'position:SYN001',
      status: 'pass',
      severity: 'pass',
      broker_value: '100',
      karkinos_value: '100',
      difference: '0',
      suggested_review_action: '',
    },
    {
      ...reportDetail.items[0],
      item_key: 'cash:account',
      category: 'cash',
      status: 'pass',
      severity: 'pass',
      symbol: '',
      display_name: null,
      broker_value: '10000',
      karkinos_value: '10000',
      difference: '0',
      suggested_review_action: '',
    },
    {
      ...reportDetail.items[0],
      item_key: 'fee:SYN001',
      category: 'fee',
      status: 'pass',
      severity: 'pass',
      broker_value: '5',
      karkinos_value: '5',
      difference: '0',
      suggested_review_action: '',
    },
  ];
  renderAccountTruthReviewPage({
    reportSummaryResponse: [
      {
        ...reportSummaries[0],
        status: 'pass',
        unresolved_count: 0,
      },
    ],
    reportDetailResponse: {
      ...reportDetail,
      status: 'pass',
      unresolved_count: 0,
      items: matchedItems,
    },
  });

  expect(
    await screen.findByText(
      '3 matched rows are quiet because no current blocker was found.',
    ),
  ).toBeTruthy();
  expect(
    screen.getByRole('heading', { name: 'Reconciliation detail' }),
  ).toBeTruthy();
  expect(screen.queryByTestId('account-truth-item-position:SYN001')).toBeNull();
  await userEvent.click(
    screen.getByRole('button', { name: 'Inspect 3 matched rows' }),
  );
  const itemList = await screen.findByRole('list', {
    name: 'Reconciliation item selection',
  });
  expect(within(itemList).getAllByRole('listitem')).toHaveLength(3);
  expect(itemList.className).toContain('overflow-y-auto');
  expect(
    await screen.findAllByTestId('account-truth-item-position:SYN001'),
  ).toHaveLength(1);
  expect(
    screen.getByTestId('account-truth-item-selector-cash:account'),
  ).toBeTruthy();
});

test('uses specific localized labels for cash-impact reconciliation categories', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'net_cash_impact:SYN001',
            category: 'net_cash_impact',
            broker_value: '-1028.00',
            karkinos_value: '-1023.00',
            difference: '-5.00',
            detail_code: 'account_truth.net_cash_impact_compared',
            suggested_review_action: 'review_net_cash_impact_difference',
          },
          {
            ...reportDetail.items[0],
            item_key: 'transfer_fee:SYN001',
            category: 'transfer_fee',
            broker_value: '0.60',
            karkinos_value: '0.00',
            difference: '0.60',
            detail_code: 'account_truth.transfer_fee_compared',
            suggested_review_action: 'review_transfer_fee_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const netCashItem = await screen.findByTestId(
    'account-truth-item-net_cash_impact:SYN001',
  );
  expect(within(netCashItem).getByText('净现金影响')).toBeTruthy();
  expect(within(netCashItem).getByText('券商 -¥1,028.00')).toBeTruthy();
  expect(netCashItem.textContent).not.toContain('net_cash_impact');
  expect(netCashItem.textContent).not.toContain('待人工复核项');

  await userEvent.click(
    screen.getByTestId('account-truth-item-selector-transfer_fee:SYN001'),
  );
  const transferFeeItem = await screen.findByTestId(
    'account-truth-item-transfer_fee:SYN001',
  );
  expect(within(transferFeeItem).getByText('过户费')).toBeTruthy();
  expect(within(transferFeeItem).getByText('差异 ¥0.60')).toBeTruthy();
  expect(transferFeeItem.textContent).not.toContain('transfer_fee');
  expect(transferFeeItem.textContent).not.toContain('待人工复核项');
});

test('explains the blocked empty state without exposing internal action codes', async () => {
  renderAccountTruthReviewPage({
    scoreResponse: {
      schema_version: 'karkinos.account_truth.score.v1',
      status: 'missing',
      import_run_id: null,
      score: null,
      gate_status: 'blocked',
      cash_status: 'missing',
      position_status: 'missing',
      fee_status: 'missing',
      cost_basis_status: 'missing',
      data_freshness_status: 'missing',
      unresolved_mismatch_count: null,
      resolved_review_count: 0,
      required_actions: ['import_and_reconcile_broker_evidence'],
      blocking_reasons: ['account_truth_score_unavailable'],
      limitations: [
        'Account Truth review requires staged broker evidence before trusted use.',
      ],
    },
    importRunResponse: [],
    reportSummaryResponse: [],
  });

  expect(
    (await screen.findAllByText('Account facts are not ready')).length,
  ).toBeGreaterThan(0);
  expect(
    await screen.findByText(
      'No broker statement, position snapshot, or cash snapshot has been staged yet.',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('How to use this page')).toBeTruthy();
  expect(screen.getAllByText('Import broker evidence').length).toBeGreaterThan(
    0,
  );
  expect(
    await screen.findByText('Then return here to review differences'),
  ).toBeTruthy();
  expect(screen.queryByText('import_and_reconcile_broker_evidence')).toBeNull();
  expect(screen.queryByText('account_truth_score_unavailable')).toBeNull();
});
