export const REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION =
  'approve_reconciled_account_fee_schedule_for_research_only_without_execution_or_capital_authority';
export const REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION =
  'revoke_reconciled_account_fee_schedule_without_execution_or_capital_authority';

export type ReviewedFeeSchedule = {
  schedule_id: string;
  account_profile_id: string;
  broker_name: string;
  stock_a_commission_rate: string;
  stock_a_min_commission: string;
  fund_etf_commission_rate: string;
  fund_etf_min_commission: string;
  stamp_tax_rate: string;
  transfer_fee_rate: string;
  fund_etf_transfer_fee_rate: string;
  exchange_transfer_fee_rates: Record<string, string>;
  other_fee_rate: string;
  money_precision: string | null;
  money_rounding_mode: string;
  limitations: string[];
};

export type ReviewedFeeSchedulePreview = {
  schema_version:
    | 'karkinos.account_truth.reviewed_fee_schedule_preview.v1'
    | 'karkinos.account_truth.reviewed_fee_schedule_preview.v2'
    | 'karkinos.account_truth.reviewed_fee_schedule_preview.v3';
  status: 'ready' | 'blocked';
  schedule: ReviewedFeeSchedule;
  schedule_fingerprint: string;
  effective_start_date: string;
  effective_end_date: string;
  reviewed_asset_classes?: Array<'stock' | 'etf'>;
  account_truth_import_run_id: string;
  account_truth_source_fingerprint: string;
  account_truth_scope_fingerprint: string;
  account_reference_hash: string;
  account_truth_readiness_status: string;
  account_truth_promotion_status: string;
  component_reconciliation: {
    status: 'pass' | 'blocked';
    reviewed_asset_classes?: Array<'stock' | 'etf'>;
    source_trade_count?: number;
    trade_count: number;
    excluded_trade_count?: number;
    excluded_asset_class_counts?: Record<string, number>;
    matched_trade_count: number;
    side_counts: { buy: number; sell: number };
    asset_class_counts: Record<string, number>;
    mismatch_counts: {
      fee: number;
      tax: number;
      transfer_fee: number;
    };
    mismatch_counts_by_asset_and_side: Array<{
      asset_class: string;
      side: 'buy' | 'sell';
      fee: number;
      tax: number;
      transfer_fee: number;
    }>;
    maximum_absolute_differences: {
      fee: string;
      tax: string;
      transfer_fee: string;
    };
    tolerance: string;
  };
  issues: string[];
  preview_fingerprint: string;
  persisted_broker_events_only: true;
  stores_broker_event_details: false;
  provider_contacted: false;
  authorizes_execution: false;
  changes_capital_authority: false;
};

export type ReviewedFeeScheduleReview = {
  review_id: string;
  schema_version: 'karkinos.account_truth.reviewed_fee_schedule_review.v1';
  decision: 'accepted' | 'revoked';
  schedule: ReviewedFeeSchedule;
  schedule_fingerprint: string;
  preview: ReviewedFeeSchedulePreview;
  preview_fingerprint: string;
  account_truth_import_run_id: string;
  account_truth_source_fingerprint: string;
  account_truth_scope_fingerprint: string;
  account_reference_hash: string;
  effective_start_date: string;
  effective_end_date: string;
  reviewer: string;
  review_fingerprint: string;
  created_at: string;
  reused: boolean;
};

export type ReviewedFeeScheduleReviewStatus = {
  status: 'missing' | 'active' | 'blocked' | 'revoked';
  review: ReviewedFeeScheduleReview | null;
  blockers: string[];
  current_preview_fingerprint: string | null;
  authorizes_execution: false;
  changes_capital_authority: false;
};

export type ReviewedFeeScheduleReviewCommand = {
  status: 'accepted' | 'revoked';
  review: ReviewedFeeScheduleReview;
  approval_confirmation?: string;
  revocation_confirmation?: string;
  authorizes_execution: false;
  changes_capital_authority: false;
};
