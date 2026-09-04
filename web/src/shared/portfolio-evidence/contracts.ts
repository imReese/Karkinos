export type Position = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  asset_class?: string | null;
  instrument_type?: string | null;
  quantity: number;
  available_qty: number;
  frozen_qty: number;
  avg_cost: number;
  broker_displayed_unit_cost?: number | null;
  broker_displayed_cost_basis?: number | null;
  broker_cost_basis_difference?: number | null;
  broker_cost_basis_method?: string | null;
  broker_cost_basis_status?: string | null;
  latest_price?: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
  commission_paid: number;
  today_change?: number | null;
  today_change_pct?: number | null;
  baseline_price?: number | null;
  baseline_timestamp?: string | null;
  baseline_source?: string;
  quote_timestamp?: string | null;
  quote_status?: string;
  quote_source?: string | null;
  quote_age_seconds?: number | null;
  stale_reason?: string | null;
  refresh_policy?: string | null;
  using_persistent_cache?: boolean;
  nav_date?: string | null;
  closed_at?: string | null;
  valuation_available?: boolean;
  valuation_blockers?: string[];
};

export type AllocationItem = {
  symbol: string;
  name: string;
  weight: number;
  value: number;
  asset_class: string;
};

export type AllocationGroup = {
  asset_class: string;
  name: string;
  value: number;
  weight: number;
  items: AllocationItem[];
};

export type PositionEvidenceReview = {
  status: 'review_required';
  reason_codes: string[];
  position: Position;
};

export type ValuationLane = {
  asset_class: string;
  status: 'not_applicable' | 'complete' | 'degraded' | 'missing';
  quote_count: number;
  complete_quote_count: number;
  review_required_quote_count: number;
  blocker_statuses: string[];
};

export type PortfolioSnapshot = {
  cash: number;
  total_equity: number | null;
  total_deposits: number;
  positions: Position[];
  allocation: AllocationItem[];
  allocation_grouped: AllocationGroup[];
  closed_positions?: Position[];
  position_review_items?: PositionEvidenceReview[];
  realized_pnl_total?: number | null;
  valuation_snapshot_id?: string | null;
  valuation_as_of?: string | null;
  valuation_trade_date?: string | null;
  valuation_policy?: string | null;
  valuation_status?: string;
  valuation_lanes?: ValuationLane[];
  ledger_cutoff_id?: number;
  ledger_fingerprint?: string | null;
  quote_set_fingerprint?: string | null;
  missing_price_symbols?: string[];
  valuation_blockers?: string[];
};

export type CurrentHoldingMarketEvidenceReviewItem = {
  symbol: string;
  name: string;
  asset_class: string;
  instrument_type?: string | null;
  quantity: number;
  quote_status: string;
  quote_source?: string | null;
  quote_timestamp?: string | null;
  stale_reason?: string | null;
  nav_date?: string | null;
  review_reason: string;
  next_manual_action: string;
  explicit_refresh_eligible: boolean;
  blocks_authoritative_decisions: boolean;
};

export type CurrentHoldingMarketEvidenceLane = {
  asset_class: string;
  status:
    'not_applicable' | 'complete' | 'degraded' | 'missing' | 'blocked_identity';
  current_holding_count: number;
  confirmed_holding_count: number;
  review_required_count: number;
  blocker_statuses: string[];
};

export type CurrentHoldingMarketEvidenceReview = {
  schema_version: 'karkinos.current_holding_market_evidence_review.v1';
  status:
    'blocked_identity' | 'complete' | 'no_current_holdings' | 'review_required';
  next_manual_action: string;
  current_holding_count: number;
  confirmed_holding_count: number;
  review_required_count: number;
  fund_nav_review_count: number;
  estimated_review_count: number;
  stale_or_cached_review_count: number;
  missing_or_error_review_count: number;
  unknown_status_review_count: number;
  /**
   * New responses own the two refresh lanes explicitly. These remain optional
   * while the Web can still be paired with an older local service that exposes
   * only their ordered union in `refreshable_symbols`.
   */
  quote_refresh_symbols?: string[];
  confirmed_fund_nav_refresh_symbols?: string[];
  refreshable_symbols: string[];
  evidence_lanes?: CurrentHoldingMarketEvidenceLane[];
  items: CurrentHoldingMarketEvidenceReviewItem[];
  source_blockers: string[];
  review_fingerprint: string;
  valuation_snapshot_id?: string | null;
  valuation_as_of?: string | null;
  valuation_trade_date?: string | null;
  valuation_policy?: string | null;
  valuation_status: string;
  ledger_cutoff_id: number;
  ledger_fingerprint?: string | null;
  quote_set_fingerprint?: string | null;
  reads_persisted_facts_only: boolean;
  provider_contact_performed: boolean;
  runtime_connector_query_performed: boolean;
  database_writes_performed: boolean;
  does_not_mutate_oms: boolean;
  does_not_mutate_production_ledger: boolean;
  does_not_mutate_risk: boolean;
  does_not_mutate_kill_switch: boolean;
  does_not_change_capital_authority: boolean;
  authorizes_execution: boolean;
};

export type LiveHoldingItem = {
  symbol: string;
  name: string;
  display_name?: string | null;
  asset_class: string;
  quantity: number;
  avg_cost: number;
  market_value: number | null;
  latest_price: number | null;
  quote_timestamp: string | null;
  since_buy_pnl: number | null;
  since_buy_pnl_pct: number | null;
  today_change: number | null;
  today_change_pct: number | null;
  baseline_price: number | null;
  baseline_timestamp: string | null;
  baseline_source: string;
  quote_status: string;
  quote_source?: string | null;
  quote_age_seconds?: number | null;
  stale_reason?: string | null;
  refresh_policy?: string | null;
  using_persistent_cache?: boolean;
  nav_date?: string | null;
  valuation_available?: boolean;
  valuation_blockers?: string[];
};

export type LiveHoldingGroup = {
  asset_class: string;
  label: string;
  total_market_value: number | null;
  total_today_change: number | null;
  total_since_buy_pnl: number | null;
  items: LiveHoldingItem[];
};

export type LiveHoldingsResponse = {
  groups: LiveHoldingGroup[];
  valuation_snapshot_id?: string | null;
  valuation_as_of?: string | null;
  valuation_trade_date?: string | null;
  valuation_policy?: string | null;
  valuation_status?: string;
  ledger_cutoff_id?: number;
  ledger_fingerprint?: string | null;
  quote_set_fingerprint?: string | null;
  missing_price_symbols?: string[];
  valuation_blockers?: string[];
};
