export type DailyOperationsSummary = {
  candidate_pool_count: number;
  evidence_passed_count: number;
  risk_checked_count: number;
  risk_passed_count: number;
  risk_blocked_count: number;
  paper_shadow_review_count: number;
  manual_ready_count: number;
  pending_manual_order_count: number;
  execution_record_count: number;
  fill_record_count: number;
  ledger_review_count: number;
  execution_exception_count: number;
  default_execution_mode: string;
  broker_bridge_status: string;
  conclusion_status: string;
  primary_target: string;
  limitations: string[];
};

export type DailyTradingPlanBlockerSummary = {
  category: string;
  target: string;
  count: number;
  reasons: string[];
  sample_symbols: string[];
};
