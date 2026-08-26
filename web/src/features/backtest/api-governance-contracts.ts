export type AccountStrategyAssignment = {
  strategy_id: string;
  strategy_name: string;
  status: string;
  scope: string;
  asset_class?: string | null;
  symbol?: string | null;
  effective_from?: string | null;
  auto_trade_enabled: boolean;
  attribution_status: string;
  attributed_pnl?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  total_fees?: number | null;
  notes?: string;
  updated_at?: string | null;
  limitations: string[];
};

export type AccountStrategyAttributionSummary = {
  strategy_id: string;
  attribution_status: string;
  signal_count: number;
  action_count: number;
  risk_decision_count: number;
  order_count: number;
  fill_count: number;
  unattributed_fill_count: number;
  total_fees: number;
  attributed_pnl?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  evidence_refs: string[];
  limitations: string[];
};

export type AccountStrategyContributionReport = {
  schema_version: string;
  strategy_id: string;
  contribution_status: string;
  evidence_binding_status?: string;
  next_manual_action?: string;
  blockers?: string[];
  strategy_health_status?: string;
  strategy_health_reasons?: string[];
  linked_fill_count: number;
  ledger_posted_fill_count?: number;
  unposted_linked_fill_count?: number;
  unattributed_fill_count?: number;
  gross_realized_pnl: number | null;
  gross_unrealized_pnl: number | null;
  total_commission: number | null;
  total_slippage: number | null;
  total_tax: number | null;
  net_contribution: number | null;
  unattributed_account_pnl?: number | null;
  manual_unattributed_pnl?: number | null;
  cash_flow_pnl?: number | null;
  missing_valuation_symbols: string[];
  valuation_snapshot_id?: string | null;
  valuation_as_of?: string | null;
  valuation_status?: string;
  valuation_scope_status?: string;
  ledger_cutoff_id?: number;
  ledger_fingerprint?: string | null;
  quote_set_fingerprint?: string | null;
  contribution_fingerprint?: string | null;
  evidence_refs: string[];
  persisted_facts_only?: boolean;
  provider_contacted?: boolean;
  database_writes_performed?: boolean;
  authorizes_execution?: boolean;
  limitations: string[];
};

export type StrategyLearningResearchHandoff = {
  schema_version: string;
  kind: 'copy_only_human_started_research';
  research_question: string;
  review_id: string;
  evidence_refs: string[];
  historical_review_is_current_fact: false;
  requires_human_started_capture: true;
  requires_human_started_research_task: true;
  invokes_ai: false;
  creates_memory: false;
  authorizes_strategy_change: false;
  authorizes_execution: false;
};

export type StrategyLearningReviewItem = {
  review_id: string;
  signal_id: number;
  strategy_id: string;
  symbol: string;
  reviewed_at: string;
  user_decision: string;
  outcome: string;
  learning_status: string;
  priority: 'critical' | 'high' | 'medium' | 'low' | 'none';
  safe_next_action: string;
  stored_target_fingerprint: string;
  current_target_fingerprint: string;
  target_binding_valid: boolean;
  audit_integrity_valid: boolean;
  valuation_snapshot_id: string | null;
  ledger_cutoff_id: number;
  contribution_fingerprint: string | null;
  blockers: string[];
  evidence_refs: string[];
  research_handoff: StrategyLearningResearchHandoff | null;
  item_fingerprint: string;
  persisted_facts_only: true;
  provider_contacted: false;
  database_writes_performed: false;
  financial_recalculation_performed: false;
  ai_invoked: false;
  memory_created: false;
  strategy_changed: false;
  authorizes_execution: false;
  capital_authority_changed: false;
};

export type StrategyLearningReviewQueue = {
  schema_version: string;
  status: 'not_configured' | 'blocked' | 'review_required' | 'clear';
  reviewed_signal_count: number;
  action_item_count: number;
  critical_item_count: number;
  outcome_counts: Record<string, number>;
  strategy_summaries: Array<{
    strategy_id: string;
    reviewed_signal_count: number;
    action_item_count: number;
    highest_priority: string;
    outcome_counts: Record<string, number>;
  }>;
  items: StrategyLearningReviewItem[];
  limitations: string[];
  queue_fingerprint: string;
  generated_at: string;
  persisted_facts_only: true;
  provider_contacted: false;
  database_writes_performed: false;
  financial_recalculation_performed: false;
  ai_invoked: false;
  memory_created: false;
  strategy_changed: false;
  authorizes_execution: false;
  capital_authority_changed: false;
};

export type AccountStrategyAssignmentUpdate = {
  strategy_id: string;
  status?: string;
  scope?: string;
  asset_class?: string | null;
  symbol?: string | null;
  effective_from?: string | null;
  notes?: string;
};

export type AcceptanceAuditCriterion = {
  key: string;
  checkbox_text: string;
  evidence_paths: string[];
  validation_commands: string[];
  is_complete: boolean;
};

export type AcceptanceAuditSummary = {
  key: string;
  name: string;
  required_count: number;
  completed_count: number;
  is_complete: boolean;
  criteria: AcceptanceAuditCriterion[];
  limitations: string[];
};

export type AcceptanceAuditExport = {
  generated_at: string;
  selected_audit: string;
  audits: AcceptanceAuditSummary[];
  overall_is_complete: boolean;
};
