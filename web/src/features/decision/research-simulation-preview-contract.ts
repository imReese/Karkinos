/** Explicit saved research, modeled against an account without order authority. */
export type ResearchSimulationAction = {
  action_id: null;
  symbol: string | null;
  display_name?: string | null;
  name?: string | null;
  asset_class?: string | null;
  side: string | null;
  target_weight?: number | null;
  estimated_quantity?: number | null;
  estimated_price?: number | null;
  estimated_purchase_cost?: number | null;
  frozen_market_date?: string | null;
  trigger_condition?: string | string[] | null;
  reason?: string | null;
  risk_impact?: string | null;
  submission_status: 'research_simulation_only';
  manual_confirmation_required: true;
  executable: false;
};

export type ResearchSimulationPreview = {
  status: 'available' | 'blocked' | 'no_action';
  blockers: string[];
  actions: ResearchSimulationAction[];
  blocked_candidates: {
    symbol: string;
    side: string;
    reason: string;
  }[];
  source: {
    session_id: string | null;
    draft_id: string | null;
    backtest_run_id: string | null;
    critique_id: string | null;
    canonical_backtest_result_id: number | null;
    formula_fingerprint: string | null;
    source_fingerprint: string | null;
    historical_validation_status: string | null;
    research_evidence_bundle?: { gate_status?: string } | null;
    dataset_simulation_admission?: {
      status: string;
      historical_pit_verified: boolean;
      account_publication_admitted: false;
    } | null;
    current_CAS_replayed: boolean | null;
  };
  valuation_snapshot_id: string | null;
  ledger_cutoff_id: number | null;
  as_of_market_date: string | null;
  target_market_date: string | null;
  price_basis: 'verified_daily_close';
  uses_current_quotes: false;
  cost_basis: 'saved_research_assumptions';
  account_fee_schedule_evaluated: false;
  quantity_basis: 'desired_target_before_fill_simulation';
  execution_simulated: false;
  research_only: true;
  read_only: true;
  manual_confirmation_required: true;
  human_review_status: 'not_recorded';
  executable: false;
  creates_action_task: false;
  creates_order_intent: false;
  creates_oms_order: false;
  authorizes_account_publication: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  authority_effect: 'none';
  market_dataset_id?: string;
  cost_assumptions?: {
    source: 'research_simulation';
    slippage_bps?: string;
    max_volume_participation?: string;
    limitations?: string[];
  };
  critique?: {
    uncertainty?: string;
    concentration_risk?: string;
    possible_overfitting?: string;
    evidence_gaps?: string[];
    explicit_failure_conditions?: string[];
  };
  hypothetical_exit_proceeds_available?: false;
  evidence_fingerprint: string;
};
