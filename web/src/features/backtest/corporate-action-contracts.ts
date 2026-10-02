export type CorporateActionEvidence = {
  schema_version: 'karkinos.corporate_action_evidence.v1';
  status: 'observed';
  observation_ids: string[];
  provider: 'tushare';
  available_at: string;
  availability_basis: 'capture_completed_at';
  historical_availability_verified: false;
  covered_action_types: string[];
  coverage_status: 'provider_reported_only';
  total_record_count: number;
  matched_event_count: number;
  undated_event_count: number;
  events: Array<{
    symbol: string;
    instrument_type: string;
    div_proc: string | null;
    end_date: string | null;
    ann_date: string | null;
    imp_ann_date: string | null;
    record_date: string | null;
    ex_date: string | null;
    pay_date: string | null;
    div_listdate: string | null;
    cash_div_tax: string | null;
    cash_div: string | null;
    stk_div: string | null;
    stk_bo_rate: string | null;
    stk_co_rate: string | null;
    available_at: string;
    captured_at: string;
    source_revision_id: string;
    observation_id: string;
  }>;
  returns_modeled: false;
  limitations: string[];
};

export type CorporateActionMode =
  'price_only' | 'cash_dividends_gross' | 'reported_distributions_gross';

type DistributionAccounting = {
  gross_income: string;
  cash_paid: string;
  receivable: string;
  taxes_modeled: false;
  coverage_verified: false;
  historical_availability_verified: false;
  ex_date_execution_blocked_count: number;
  limitations: string[];
};

type CashDistribution = {
  action_id: string;
  symbol: string;
  record_date: string;
  ex_date: string;
  pay_date: string;
  cash_per_share: string;
  eligible_quantity: string;
  gross_amount: string;
  paid: boolean;
};

export type CashDividendAccounting = DistributionAccounting &
  (
    | {
        schema_version: 'karkinos.backtest_cash_dividends.v1';
        mode: 'cash_dividends_gross';
        distributions: CashDistribution[];
      }
    | {
        schema_version: 'karkinos.backtest_cash_dividends.v2';
        mode: 'reported_distributions_gross';
        share_quantity: string;
        unlisted_quantity: string;
        distributions: Array<
          Omit<CashDistribution, 'pay_date'> & {
            pay_date: string | null;
            shares_per_share: string;
            share_quantity: string;
            listing_date: string | null;
            shares_listed: boolean;
          }
        >;
      }
  );
