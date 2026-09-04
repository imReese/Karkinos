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
  actions: Array<{
    action_id: string | null;
    symbol: string | null;
    asset_class: string | null;
    side: string | null;
    target_weight: number | null;
    estimated_quantity: number | null;
    submission_status: string | null;
  }>;
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
