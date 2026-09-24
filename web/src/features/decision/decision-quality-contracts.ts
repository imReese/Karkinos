export type DecisionQualityDimension = {
  name:
    | 'data_complete'
    | 'risk_checked'
    | 'benchmark_aware'
    | 'journaled'
    | 'later_reviewable';
  passed: boolean;
  status: string;
  evidence: Record<string, unknown>;
  blockers: string[];
};

export type DecisionQualityTarget = {
  schema_version: 'karkinos.decision_quality_target.v1';
  decision_date: string;
  decision: string;
  candidate_count: number;
  decision_fingerprint: string;
  dimensions: DecisionQualityDimension[];
  passed_dimension_count: number;
  dimension_count: number;
  diagnostic_score_percent: number;
  qualified: boolean;
  qualification_status: 'qualified' | 'blocked';
  blockers: string[];
  valuation_snapshot_id: string | null;
  ledger_cutoff_id: number;
  ledger_fingerprint: string | null;
  quote_set_fingerprint: string | null;
  target_fingerprint: string;
  persisted_facts_only: true;
  runtime_cache_used: false;
  provider_contacted: false;
  database_writes_performed: false;
  authorizes_execution: false;
  authority_effect: 'none';
  limitations: string[];
};

export type DecisionQualityCapture = {
  schema_version: 'karkinos.decision_quality_capture.v1';
  snapshot_id: string;
  decision_date: string;
  captured_at: string;
  captured_by: string;
  qualified: boolean;
  request_fingerprint: string;
  stored_target_fingerprint: string;
  stored_target: DecisionQualityTarget;
};

export type DecisionQualityReport = {
  schema_version: 'karkinos.decision_quality_report.v1';
  status: 'empty' | 'complete' | 'blocked';
  score_percent: number | null;
  evaluated_day_count: number;
  qualified_day_count: number;
  blocked_day_count: number;
  total_capture_count: number;
  coverage_start: string | null;
  coverage_end: string | null;
  latest_by_day: Array<{
    snapshot_id: string;
    decision_date: string;
    captured_at: string;
    qualified: boolean;
    diagnostic_score_percent: number;
    target_fingerprint: string;
    audit_valid: boolean;
  }>;
  blockers: string[];
  coverage_scope: 'explicitly_captured_decision_days_only';
  limitations: string[];
};

export type DecisionQualityView = {
  schema_version: 'karkinos.decision_quality_view.v1';
  current_target: DecisionQualityTarget;
  report: DecisionQualityReport;
  current_day_capture: DecisionQualityCapture | null;
  current_day_captured: boolean;
  current_binding_valid: boolean | null;
  persisted_facts_only: true;
  provider_contacted: false;
  database_writes_performed: false;
  authorizes_execution: false;
  authority_effect: 'none';
};

export type DecisionQualityCaptureResult = {
  schema_version: 'karkinos.decision_quality_capture.v1';
  capture: DecisionQualityCapture;
  current_target: DecisionQualityTarget;
  target_binding_valid: boolean;
  report: DecisionQualityReport;
  audit_replay: {
    valid: boolean;
    event_count: number;
    errors: string[];
  };
  reused: boolean;
  persisted_facts_only: true;
  provider_contacted: false;
  database_writes_performed: true;
  does_not_mutate_financial_state: true;
  authorizes_execution: false;
  authority_effect: 'none';
};
