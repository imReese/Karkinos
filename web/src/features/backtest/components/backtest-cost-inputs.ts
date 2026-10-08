import { useState } from 'react';
import type { BacktestCostAssumptions } from '../cost-contracts';

export const backtestCostFields = [
  'stock_commission_rate',
  'stock_min_commission',
  'etf_commission_rate',
  'etf_min_commission',
  'slippage_bps',
  'max_volume_participation',
] as const;

export function useBacktestCostInputs() {
  const [custom, setCustom] = useState(false);
  const [values, setValues] = useState<
    Partial<Record<keyof BacktestCostAssumptions, string>>
  >({});
  const assumptions: BacktestCostAssumptions = {};
  let valid = true;
  if (custom) {
    for (const field of backtestCostFields) {
      const raw = values[field]?.trim();
      if (!raw) continue;
      const value = Number(raw);
      if (
        !Number.isFinite(value) ||
        value < 0 ||
        (field.endsWith('_rate') && value > 10000) ||
        (field === 'slippage_bps' && value >= 10000) ||
        (field === 'max_volume_participation' && (value <= 0 || value > 100))
      ) {
        valid = false;
        continue;
      }
      assumptions[field] = field.endsWith('_rate')
        ? value / 10000
        : field === 'max_volume_participation'
          ? value / 100
          : value;
    }
  }
  return {
    custom,
    setCustom,
    values,
    setValues,
    valid,
    assumptions: Object.keys(assumptions).length ? assumptions : undefined,
  };
}
