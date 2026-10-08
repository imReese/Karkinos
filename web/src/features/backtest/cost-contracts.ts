export type BacktestCostAssumptions = {
  stock_commission_rate?: number;
  stock_min_commission?: number;
  etf_commission_rate?: number;
  etf_min_commission?: number;
  slippage_bps?: number;
  max_volume_participation?: number;
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
  schema_version?: string;
  source?: string;
  execution_cost_model_id?: string;
  commission_model_reference?: string;
  slippage_model: string;
  slippage_bps: string;
  max_volume_participation?: string;
  stock?: FeeParameters;
  etf?: FeeParameters;
  bond?: FeeParameters;
  gold?: FeeParameters;
  limitations?: string[];
};

export type BacktestCostSensitivity = (
  { cost_assumptions: BacktestEffectiveCosts } | BacktestEffectiveCosts
) & {
  total_return: number;
  max_drawdown: number;
  fill_count: number;
};

export function readBacktestEffectiveCosts(
  value: unknown,
): BacktestEffectiveCosts | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const costs = value as BacktestEffectiveCosts;
  const ordinary =
    costs.schema_version === 'karkinos.backtest_cost_assumptions.v1';
  const research =
    costs.schema_version === undefined &&
    costs.execution_cost_model_id ===
      'karkinos.research.percent_slippage.volume_cap.v1';
  const finite = (number: unknown, maximum = Infinity) =>
    (typeof number === 'number' ||
      (typeof number === 'string' && number.trim() !== '')) &&
    Number.isFinite(Number(number)) &&
    Number(number) >= 0 &&
    Number(number) <= maximum;
  if (
    (!ordinary && !research) ||
    costs.slippage_model !== 'percent_of_reference_price' ||
    !finite(costs.slippage_bps) ||
    Number(costs.slippage_bps) >= 10000 ||
    ((research || costs.max_volume_participation !== undefined) &&
      (!finite(costs.max_volume_participation, 1) ||
        Number(costs.max_volume_participation) <= 0)) ||
    (costs.commission_model_reference !== undefined &&
      (typeof costs.commission_model_reference !== 'string' ||
        !costs.commission_model_reference.trim())) ||
    (costs.source !== undefined && typeof costs.source !== 'string') ||
    (costs.limitations !== undefined &&
      (!Array.isArray(costs.limitations) ||
        !costs.limitations.every((note) => typeof note === 'string')))
  )
    return null;
  for (const asset of ['stock', 'etf', 'bond', 'gold'] as const) {
    const fees = costs[asset];
    if (fees === undefined) continue;
    if (research || !fees || typeof fees !== 'object' || Array.isArray(fees)) {
      return null;
    }
    if (
      fees.fee_rule_id !== undefined &&
      typeof fees.fee_rule_id !== 'string'
    ) {
      return null;
    }
    for (const key of [
      'commission_rate',
      'min_commission',
      'transfer_fee_rate',
      'other_fee_rate',
      'sell_stamp_tax_rate',
    ] as const) {
      if (
        fees[key] !== undefined &&
        !finite(fees[key], key === 'min_commission' ? Infinity : 1)
      ) {
        return null;
      }
    }
  }
  return costs;
}

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
