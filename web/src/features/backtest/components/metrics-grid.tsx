import {
  MetricStrip,
  type MetricStripItem,
} from '../../../app/components/workbench';
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
  tone?: MetricStripItem['tone'];
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
      tone:
        finiteNumber(metrics.total_return) > 0
          ? 'pnl-positive'
          : finiteNumber(metrics.total_return) < 0
            ? 'pnl-negative'
            : 'neutral',
    },
    {
      label: labels.sharpe,
      value: formatNumber(metrics.sharpe),
      detail: `${labels.sortino} ${formatNumber(metrics.sortino)}`,
    },
    {
      label: labels.maxDrawdown,
      value: formatRatio(metrics.max_drawdown),
      detail: `${labels.calmar} ${formatNumber(metrics.calmar)}`,
    },
    {
      label: labels.winRate,
      value: formatRatio(metrics.win_rate),
      detail: labels.durationDays(finiteNumber(metrics.duration_days)),
    },
    {
      label: labels.volatility,
      value: formatRatio(metrics.volatility),
      detail: `${labels.annualReturn} ${formatRatio(metrics.annual_return)}`,
    },
    {
      label: labels.grossTurnover,
      value: formatCurrency(costs.gross_turnover ?? metrics.gross_turnover),
      detail: labels.fills(finiteNumber(totalTrades)),
    },
    {
      label: labels.totalCommission,
      value: formatCurrency(totalCommission),
      detail: labels.commissionDetail,
      tone: 'pnl-negative',
    },
    {
      label: labels.totalSlippage,
      value: formatCurrency(totalSlippage),
      detail: labels.slippageDetail,
      tone: 'pnl-negative',
    },
  ];

  const metricStripItems = items.map<MetricStripItem>((item, index) => ({
    id: `backtest-metric-${index}`,
    label: item.label,
    value: item.value,
    detail: item.detail,
    tone: item.tone,
  }));

  return (
    <section
      data-backtest-report-section="metrics"
      className="grid min-w-0 gap-2"
    >
      <MetricStrip
        ariaLabel={`${labels.totalReturn} · ${labels.maxDrawdown}`}
        items={metricStripItems.slice(0, 4)}
      />
      <MetricStrip
        ariaLabel={`${labels.volatility} · ${labels.totalSlippage}`}
        items={metricStripItems.slice(4)}
      />
    </section>
  );
}
