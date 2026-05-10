import {
  Activity,
  Gauge,
  Percent,
  ReceiptText,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  WalletCards,
  type LucideIcon,
} from 'lucide-react';

import { cn } from '../../../lib/utils/cn';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
} from '../../../shared/format';
import { useCopy } from '../../../app/copy';
import type { BacktestReport } from '../api';

type MetricItem = {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone?: 'default' | 'good' | 'danger' | 'warning';
};

function finiteNumber(value: unknown, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function formatRatio(value: unknown) {
  return formatPercent(finiteNumber(value));
}

function formatNumber(value: unknown) {
  return formatAmount(finiteNumber(value));
}

export function MetricsGrid({ report }: { report: BacktestReport }) {
  const labels = useCopy().backtest.metrics;
  const metrics = { ...report.metrics, ...report.metrics_json };
  const costs = report.cost_summary_json ?? {};
  const totalCommission =
    costs.total_commission ?? metrics.total_commission ?? 0;
  const totalSlippage = costs.total_slippage ?? metrics.total_slippage ?? 0;
  const totalTrades = costs.total_trades ?? metrics.total_trades ?? 0;

  const items: MetricItem[] = [
    {
      label: labels.totalReturn,
      value: formatRatio(metrics.total_return),
      detail: `${formatCurrency(metrics.initial_cash)} -> ${formatCurrency(
        metrics.final_equity,
      )}`,
      icon: TrendingUp,
      tone: finiteNumber(metrics.total_return) >= 0 ? 'good' : 'danger',
    },
    {
      label: labels.sharpe,
      value: formatNumber(metrics.sharpe),
      detail: `${labels.sortino} ${formatNumber(metrics.sortino)}`,
      icon: Gauge,
      tone: finiteNumber(metrics.sharpe) >= 1 ? 'good' : 'default',
    },
    {
      label: labels.maxDrawdown,
      value: formatRatio(metrics.max_drawdown),
      detail: `${labels.calmar} ${formatNumber(metrics.calmar)}`,
      icon: TrendingDown,
      tone: 'danger',
    },
    {
      label: labels.winRate,
      value: formatRatio(metrics.win_rate),
      detail: labels.durationDays(finiteNumber(metrics.duration_days)),
      icon: Percent,
    },
    {
      label: labels.volatility,
      value: formatRatio(metrics.volatility),
      detail: `${labels.annualReturn} ${formatRatio(metrics.annual_return)}`,
      icon: Activity,
    },
    {
      label: labels.grossTurnover,
      value: formatCurrency(costs.gross_turnover ?? metrics.gross_turnover),
      detail: labels.fills(finiteNumber(totalTrades)),
      icon: WalletCards,
    },
    {
      label: labels.totalCommission,
      value: formatCurrency(totalCommission),
      detail: labels.commissionDetail,
      icon: ReceiptText,
      tone: 'warning',
    },
    {
      label: labels.totalSlippage,
      value: formatCurrency(totalSlippage),
      detail: labels.slippageDetail,
      icon: ShieldAlert,
      tone: 'danger',
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div
            key={item.label}
            className={cn(
              'app-panel rounded-2xl p-4 shadow-[0_18px_50px_rgba(17,17,27,0.12)]',
              item.tone === 'danger' && 'border-[var(--app-danger-border)]',
              item.tone === 'warning' &&
                'border-[color-mix(in_srgb,#f9e2af_46%,var(--app-border))]',
            )}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                  {item.label}
                </div>
                <div
                  className={cn(
                    'mt-2 truncate text-xl font-semibold tabular-nums',
                    item.tone === 'danger' && 'text-[var(--app-danger)]',
                    item.tone === 'warning' && 'text-[#f9e2af]',
                    item.tone === 'good' && 'text-[#a6e3a1]',
                  )}
                >
                  {item.value}
                </div>
              </div>
              <span className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_30%,transparent)] p-2 text-[var(--app-muted)]">
                <Icon className="h-4 w-4" aria-hidden="true" />
              </span>
            </div>
            <div className="app-muted mt-3 text-xs">{item.detail}</div>
          </div>
        );
      })}
    </div>
  );
}
