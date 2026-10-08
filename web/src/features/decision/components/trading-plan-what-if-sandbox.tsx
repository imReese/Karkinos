import { useMemo, useState } from 'react';
import { SlidersHorizontal, RotateCcw, AlertCircle } from 'lucide-react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
} from '../../../shared/format';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import type { DailyTradingPlanResponse } from '../api';

type AdjustedIntentState = {
  enabled: boolean;
  targetWeightPct: number;
};

function simulateAdjustedIntents(
  intents: NonNullable<DailyTradingPlanResponse['order_intents']>,
  activeAdjustments: Record<string, AdjustedIntentState>,
  totalEquity: number,
  initialAvailableCash: number,
) {
  if (
    !Number.isFinite(totalEquity) ||
    totalEquity <= 0 ||
    !Number.isFinite(initialAvailableCash) ||
    initialAvailableCash < 0 ||
    intents.some((intent) => {
      const key = intent.symbol ?? String(intent.action_id ?? '');
      const adjustment = activeAdjustments[key];
      if (adjustment?.enabled === false) return false;
      const weight = adjustment?.targetWeightPct ?? intent.target_weight * 100;
      const quantity = intent.position_effect?.current_quantity;
      return (
        !Number.isFinite(intent.estimated_price) ||
        intent.estimated_price <= 0 ||
        !Number.isFinite(weight) ||
        weight < 0 ||
        weight > 100 ||
        quantity === undefined ||
        !Number.isFinite(quantity) ||
        quantity < 0
      );
    })
  ) {
    return null;
  }
  let simGross = 0;
  let simFees = 0;
  let simNetCashImpact = 0;

  const intentSimulations = intents.map((intent) => {
    const key = intent.symbol ?? String(intent.action_id ?? '');
    const adj = activeAdjustments[key] ?? {
      enabled: true,
      targetWeightPct: intent.target_weight * 100,
    };

    if (!adj.enabled) {
      return {
        intent,
        enabled: false,
        adjustedWeight: 0,
        adjustedQty: 0,
        qtyDelta: 0,
        grossAmount: 0,
        fees: 0,
        netCashImpact: 0,
      };
    }

    const targetWeight = adj.targetWeightPct / 100;
    const price = intent.estimated_price;
    const currentQty = Number(intent.position_effect?.current_quantity);
    const rawTargetQty = (totalEquity * targetWeight) / price;
    // Round to standard lots of 100 shares for stock/ETF
    const targetQty = Math.max(0, Math.round(rawTargetQty / 100) * 100);
    const qtyDelta = targetQty - currentQty;
    const grossAmount = Math.abs(qtyDelta) * price;
    // Illustrative fixed friction rates, not reviewed instrument or account fees.
    const isSell = qtyDelta < 0;
    const feeRate = isSell ? 0.0008 : 0.0003;
    const fees = grossAmount === 0 ? 0 : Math.max(5, grossAmount * feeRate);
    const netCashImpact = isSell ? grossAmount - fees : -(grossAmount + fees);

    simGross += grossAmount;
    simFees += fees;
    simNetCashImpact += netCashImpact;

    return {
      intent,
      enabled: true,
      adjustedWeight: targetWeight,
      adjustedQty: targetQty,
      qtyDelta,
      grossAmount,
      fees,
      netCashImpact,
    };
  });

  const simTurnover = (simGross / (2 * totalEquity)) * 100;
  const simPostCash = initialAvailableCash + simNetCashImpact;
  const simCashRatio = (simPostCash / totalEquity) * 100;

  if (
    ![simGross, simFees, simTurnover, simPostCash, simCashRatio].every(
      Number.isFinite,
    )
  ) {
    return null;
  }
  return {
    simGross,
    simFees,
    simTurnover,
    simPostCash,
    simCashRatio,
    intentSimulations,
  };
}

function WhatIfSandboxHeader({
  isZh,
  hasModifications,
  onReset,
}: {
  isZh: boolean;
  hasModifications: boolean;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--app-divider)] pb-3">
      <div className="flex items-center gap-2">
        <SlidersHorizontal
          size={16}
          className="text-[var(--app-accent)]"
          aria-hidden="true"
        />
        <div>
          <h3 className="app-card-title text-sm font-semibold text-[var(--app-text)]">
            {isZh
              ? '调仓推演沙盘 (What-If Analyzer)'
              : 'What-If Rebalance Sandbox'}
          </h3>
          <p className="app-muted text-xs">
            {isZh
              ? '使用示例费率推演假设净现金、换手和摩擦；不判定正式风控，也不检查先买后卖等顺序融资条件。'
              : 'Estimate hypothetical net cash, turnover and friction with example fee rates. This does not assess formal risk or order-by-order funding.'}
          </p>
        </div>
      </div>
      {hasModifications ? (
        <button
          type="button"
          onClick={onReset}
          className="app-button-secondary inline-flex min-h-7 items-center gap-1.5 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-semibold"
        >
          <RotateCcw size={12} aria-hidden="true" />
          <span>{isZh ? '重置为模型推荐' : 'Reset to Recommendation'}</span>
        </button>
      ) : null}
    </div>
  );
}

function WhatIfSimulationMetrics({
  simulation,
  baselineFees,
  baselineTurnover,
  isZh,
}: {
  simulation: NonNullable<ReturnType<typeof simulateAdjustedIntents>>;
  baselineFees: number;
  baselineTurnover: number;
  isZh: boolean;
}) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 font-mono tabular-nums">
      <div className="rounded-[var(--app-radius-control)] bg-[var(--app-surface)] p-2.5 border border-[var(--app-divider)]">
        <div className="app-muted font-sans app-type-micro">
          {isZh ? '推演双边换手率' : 'Simulated Turnover'}
        </div>
        <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
          {formatPercent(simulation.simTurnover / 100)}
        </div>
        <div className="app-type-micro font-sans text-[var(--app-text-tertiary)]">
          {isZh ? '原计划' : 'Original'}:{' '}
          {Number.isFinite(baselineTurnover)
            ? formatPercent(baselineTurnover / 100)
            : '—'}
        </div>
      </div>

      <div className="rounded-[var(--app-radius-control)] bg-[var(--app-surface)] p-2.5 border border-[var(--app-divider)]">
        <div className="app-muted font-sans app-type-micro">
          {isZh ? '预估交易摩擦费' : 'Estimated Friction'}
        </div>
        <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
          {formatCurrency(simulation.simFees)}
        </div>
        <div className="app-type-micro font-sans text-[var(--app-text-tertiary)]">
          {isZh ? '原计划' : 'Original'}:{' '}
          {Number.isFinite(baselineFees) ? formatCurrency(baselineFees) : '—'}
        </div>
      </div>

      <div className="rounded-[var(--app-radius-control)] bg-[var(--app-surface)] p-2.5 border border-[var(--app-divider)]">
        <div className="app-muted font-sans app-type-micro">
          {isZh ? '假设净现金余额' : 'Hypothetical net cash'}
        </div>
        <div
          className={`mt-1 text-sm font-semibold ${
            simulation.simPostCash < 0
              ? 'text-[var(--app-danger-text)]'
              : 'text-[var(--app-text)]'
          }`}
        >
          {formatCurrency(simulation.simPostCash)}
        </div>
        <div className="app-type-micro font-sans text-[var(--app-text-tertiary)]">
          {isZh ? '现金占比' : 'Reserve Ratio'}:{' '}
          {formatPercent(simulation.simCashRatio / 100)}
        </div>
      </div>

      <div className="rounded-[var(--app-radius-control)] bg-[var(--app-surface)] p-2.5 border border-[var(--app-divider)]">
        <div className="app-muted font-sans app-type-micro">
          {isZh ? '假设净现金状态' : 'Hypothetical net cash status'}
        </div>
        <div className="mt-1 text-xs font-semibold text-[var(--app-text)]">
          {simulation.simPostCash >= 0
            ? isZh
              ? '净现金非负'
              : 'Non-negative net cash'
            : isZh
              ? '假设净现金为负'
              : 'Negative hypothetical net cash'}
        </div>
        <div className="app-type-micro font-sans text-[var(--app-text-tertiary)]">
          {isZh
            ? '正式风控与顺序资金约束待独立检查'
            : 'Formal risk and funding order require separate checks'}
        </div>
      </div>
    </div>
  );
}

export function TradingPlanWhatIfSandbox({
  plan,
}: {
  plan: DailyTradingPlanResponse;
}) {
  const { locale } = usePreferences();
  const isZh = locale === 'zh';
  const intents = plan.order_intents ?? [];

  // Initial intent state map keyed by symbol or action_id
  const defaultState = useMemo(() => {
    const state: Record<string, AdjustedIntentState> = {};
    for (const intent of intents) {
      const key = intent.symbol ?? String(intent.action_id ?? '');
      if (key) {
        state[key] = {
          enabled: true,
          targetWeightPct: Math.round(intent.target_weight * 1000) / 10,
        };
      }
    }
    return state;
  }, [intents]);

  const [adjustedState, setAdjustedState] = useState<
    Record<string, AdjustedIntentState>
  >({});
  const activeAdjustments = { ...defaultState, ...adjustedState };

  const totalEquity = plan.total_equity;
  const initialAvailableCash = plan.available_cash;

  // Baseline calculations from recommended plan
  const baselineGross = intents.reduce(
    (acc, it) => acc + (it.estimated_gross_amount ?? 0),
    0,
  );
  const baselineFees = intents.reduce(
    (acc, it) => acc + (it.estimated_total_fee ?? 0),
    0,
  );
  const baselineTurnover = (baselineGross / (2 * totalEquity)) * 100;

  // Simulation calculations
  const simulation = useMemo(
    () =>
      simulateAdjustedIntents(
        intents,
        activeAdjustments,
        totalEquity,
        initialAvailableCash,
      ),
    [intents, activeAdjustments, totalEquity, initialAvailableCash],
  );

  const hasModifications = Object.keys(adjustedState).length > 0;

  const handleToggle = (key: string) => {
    setAdjustedState((prev) => {
      const current = prev[key] ?? defaultState[key];
      return {
        ...prev,
        [key]: {
          ...current,
          enabled: !current.enabled,
        },
      };
    });
  };

  const handleWeightChange = (key: string, valuePct: number) => {
    setAdjustedState((prev) => {
      const current = prev[key] ?? defaultState[key];
      return {
        ...prev,
        [key]: {
          ...current,
          targetWeightPct: Math.max(0, Math.min(100, valuePct)),
        },
      };
    });
  };

  const handleReset = () => {
    setAdjustedState({});
  };

  if (intents.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="decision-what-if-sandbox"
      className="col-span-full min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-accent)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-raised)_70%,transparent)] p-4"
    >
      <WhatIfSandboxHeader
        isZh={isZh}
        hasModifications={hasModifications}
        onReset={handleReset}
      />

      {simulation ? (
        <WhatIfSimulationMetrics
          simulation={simulation}
          baselineFees={baselineFees}
          baselineTurnover={baselineTurnover}
          isZh={isZh}
        />
      ) : (
        <p role="status" className="app-muted mt-3 text-xs leading-5">
          <AlertCircle size={13} className="mr-1 inline" aria-hidden="true" />
          {isZh
            ? '无法推演。请准备有限且大于零的总权益、有限非负的可用现金，以及各纳入标的的有效价格、持仓数量和目标权重；也可移除缺少输入的标的。'
            : 'Cannot simulate. Prepare finite positive total equity, finite non-negative available cash, and valid prices, holdings quantities and target weights for every included instrument; or exclude instruments with missing inputs.'}
        </p>
      )}

      {/* Interactive candidates allocation table */}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-[var(--app-divider)] text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-text-secondary)]">
              <th className="py-2 pr-2">{isZh ? '纳入' : 'Include'}</th>
              <th className="py-2 px-2">{isZh ? '标的名称' : 'Instrument'}</th>
              <th className="py-2 px-2">{isZh ? '方向' : 'Side'}</th>
              <th className="py-2 px-2 text-right">
                {isZh ? '预估价格' : 'Price'}
              </th>
              <th className="py-2 px-3">
                {isZh ? '目标权重调节' : 'Target Weight'}
              </th>
              <th className="py-2 px-2 text-right">
                {isZh ? '推演股数' : 'Sim Qty'}
              </th>
              <th className="py-2 pl-2 text-right">
                {isZh ? '推演金额' : 'Gross Value'}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--app-divider)] font-mono tabular-nums">
            {intents.map((intent, index) => {
              const sim = simulation?.intentSimulations[index];
              const key = intent.symbol ?? String(intent.action_id ?? index);
              const adj = activeAdjustments[key] ?? {
                enabled: true,
                targetWeightPct: intent.target_weight * 100,
              };

              const enabled = adj.enabled;
              return (
                <tr
                  key={key}
                  className={
                    !enabled ? 'opacity-40 bg-[var(--app-surface)]' : undefined
                  }
                >
                  <td className="py-2 pr-2">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={() => handleToggle(key)}
                      className="cursor-pointer rounded border-[var(--app-border)] text-[var(--app-accent)] focus:ring-0"
                      aria-label={`${isZh ? '纳入推演' : 'Include in simulation'}: ${intent.symbol}`}
                    />
                  </td>
                  <td className="py-2 px-2 font-sans font-semibold text-[var(--app-text)]">
                    {formatInstrumentDisplayLabel(intent)}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`inline-flex rounded px-1.5 py-0.5 font-sans font-medium app-type-micro ${
                        intent.side === 'buy'
                          ? 'bg-[color-mix(in_srgb,var(--app-success)_12%,transparent)] text-[var(--app-success-text)]'
                          : 'bg-[color-mix(in_srgb,var(--app-danger)_12%,transparent)] text-[var(--app-danger-text)]'
                      }`}
                    >
                      {intent.side === 'buy'
                        ? isZh
                          ? '买入'
                          : 'Buy'
                        : isZh
                          ? '卖出'
                          : 'Sell'}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right text-[var(--app-text)]">
                    {Number.isFinite(intent.estimated_price) &&
                    intent.estimated_price > 0
                      ? formatPrice(intent.estimated_price)
                      : '—'}
                  </td>
                  <td className="py-2 px-3 font-sans">
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min="0"
                        max="40"
                        step="0.5"
                        disabled={!enabled}
                        value={
                          Number.isFinite(adj.targetWeightPct)
                            ? adj.targetWeightPct
                            : ''
                        }
                        onChange={(e) =>
                          handleWeightChange(
                            key,
                            Number.parseFloat(e.target.value),
                          )
                        }
                        className="h-1.5 w-24 cursor-pointer accent-[var(--app-accent)] disabled:cursor-not-allowed"
                      />
                      <span className="font-mono text-xs font-semibold text-[var(--app-text)] w-12 text-right">
                        {Number.isFinite(adj.targetWeightPct)
                          ? `${adj.targetWeightPct.toFixed(1)}%`
                          : '—'}
                      </span>
                    </div>
                  </td>
                  <td className="py-2 px-2 text-right text-[var(--app-text)]">
                    {enabled && sim ? formatQuantity(sim.adjustedQty) : '—'}
                  </td>
                  <td className="py-2 pl-2 text-right text-[var(--app-text)] font-semibold">
                    {enabled && sim ? formatCurrency(sim.grossAmount) : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
