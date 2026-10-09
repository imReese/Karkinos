export type {
  AccountStrategyAssignment,
  AccountStrategyAssignmentUpdate,
  AccountStrategyAttributionSummary,
  AccountStrategyContributionReport,
} from './backtest-feature-boundary';

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
