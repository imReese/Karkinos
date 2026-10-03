export type BacktestCostAssumptions = {
  stock_commission_rate?: number;
  stock_min_commission?: number;
  etf_commission_rate?: number;
  etf_min_commission?: number;
  slippage_bps?: number;
};

export type CostSummary = {
  total_commission?: number;
  total_slippage?: number;
  total_trades?: number;
  gross_turnover?: number;
};

type FeeParameters = {
  commission_rate?: string;
  min_commission?: string;
  transfer_fee_rate?: string;
  other_fee_rate?: string;
  sell_stamp_tax_rate?: string;
  fee_rule_id?: string;
};

export type BacktestEffectiveCosts = {
  schema_version: string;
  source: string;
  slippage_model: string;
  slippage_bps: string;
  stock?: FeeParameters;
  etf?: FeeParameters;
  bond?: FeeParameters;
  gold?: FeeParameters;
  limitations?: string[];
};

export type BacktestCapacityReview = {
  schema_version: string;
  status: string;
  capacity_utilization_pct?: string;
  liquidity_utilization_pct?: string;
  max_daily_volume_participation?: string;
  fill_count?: number;
  observation_count?: number;
  issues?: string[];
  assumptions?: string[];
  limitations?: string[];
};
