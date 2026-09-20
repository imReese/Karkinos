export type AccountRecommendationAction = {
  action_id: string | number | null;
  symbol: string | null;
  display_name?: string | null;
  name?: string | null;
  asset_class: string | null;
  side: string | null;
  target_weight: number | null;
  estimated_quantity: number | null;
  submission_status: string | null;
};

export type AccountActionRecommendation = {
  schema_version: 'karkinos.decision.account_action_recommendation.v1';
  decision_date: string | null;
  status:
    | 'manual_review_required'
    | 'paper_shadow_required'
    | 'no_action'
    | 'blocked'
    | 'unavailable';
  reason_codes: string[];
  source_action_task_ids: string[];
  actions: AccountRecommendationAction[];
  presentation?: {
    level:
      | 'manual_review'
      | 'portfolio_preview'
      | 'signal'
      | 'no_action'
      | 'blocked'
      | 'unavailable';
    actions: AccountRecommendationAction[];
    signal_status: 'ready' | 'no_signal' | 'unavailable';
    portfolio_preview_status: 'ready' | 'blocked';
    manual_review_status: 'ready' | 'blocked';
    configuration_blockers: string[];
    signal_blockers: string[];
    portfolio_preview_blockers: string[];
    manual_review_blockers: string[];
    read_only: true;
    authorizes_execution: false;
  };
  promoted_scan: {
    run_id: string | null;
    status: string;
    input_fingerprint: string | null;
    output_fingerprint: string | null;
    selected_signal_count: number;
  };
  account_evidence: {
    valuation_snapshot_id: string | null;
    ledger_cutoff_id: number | null;
    quote_set_fingerprint: string | null;
    valuation_status: string;
    account_truth_status: string;
    account_qualification_status: 'passed' | 'blocked';
    account_positions_evaluated: boolean;
  };
  read_only: true;
  manual_confirmation_required: true;
  creates_oms_order: false;
  submits_broker_order: false;
  authorizes_execution: false;
  changes_capital_authority: false;
  authority_effect: 'none';
  evidence_fingerprint: string;
};
