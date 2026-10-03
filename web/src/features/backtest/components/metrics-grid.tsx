import {
  MetricStrip,
  type MetricStripItem,
} from '../../../shared/ui/workbench';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { BacktestReport } from '../api';
import { cashDividendCopy } from '../copy-cash-dividends';
import { BacktestExecutionWindowPanel } from './backtest-execution-window';

type MetricItem = {
  label: string;
  value: string;
  detail: MetricStripItem['detail'];
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

export function MetricsGrid({
  report,
  compact = false,
}: {
  report: BacktestReport;
  compact?: boolean;
}) {
  const labels = useCopy().backtest.metrics;
  const { locale } = usePreferences();
  const metrics = { ...report.metrics, ...report.metrics_json };
  const snapshot = report.metrics_json?.dataset_snapshot;
  const distributionMode = report.metrics_json?.cash_dividend_accounting?.mode;
  const unadjustedReturns = Boolean(
    snapshot?.price_basis === 'unadjusted' ||
    snapshot?.adjustment_mode === 'none' ||
    snapshot?.research_limitations?.some(
      (issue) => issue.code === 'unadjusted_corporate_actions_unmodeled',
    ) ||
    (snapshot?.immutable_dataset_id && snapshot.price_basis === undefined),
  );
  const costs = report.cost_summary_json ?? {};
  const totalCommission =
    costs.total_commission ?? metrics.total_commission ?? 0;
  const totalSlippage = costs.total_slippage ?? metrics.total_slippage ?? 0;
  const totalTrades = costs.total_trades ?? metrics.total_trades ?? 0;

  const items: MetricItem[] = [
    {
      label: labels.totalReturn,
      value: formatRatio(metrics.total_return),
      detail: (
        <>
          {formatCurrency(metrics.initial_cash)} -&gt;{' '}
          {formatCurrency(metrics.final_equity)}
          {distributionMode || unadjustedReturns ? (
            <span className="mt-1 block text-[var(--app-warning-text)]">
              {distributionMode === 'reported_distributions_gross'
                ? cashDividendCopy[locale].reportedReturns
                : distributionMode === 'cash_dividends_gross'
                  ? cashDividendCopy[locale].returns
                  : locale === 'zh'
                    ? '模拟权益收益；未计入分红等公司行动，不代表完整经济收益。'
                    : 'Simulated equity return; excludes dividends and other corporate actions, so this is not total economic return.'}
            </span>
          ) : null}
        </>
      ),
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
      <BacktestExecutionWindowPanel report={report} />
      <MetricStrip
        ariaLabel={`${labels.totalReturn} · ${labels.maxDrawdown}`}
        className={`app-backtest-evidence-strip ${compact ? 'sm:grid-flow-row sm:grid-cols-2 [&>div:nth-child(even)]:border-r-0 [&>div:nth-child(-n+2)]:border-b [&>div]:border-[var(--app-divider)]' : ''}`}
        items={metricStripItems.slice(0, 4)}
      />
      <MetricStrip
        ariaLabel={`${labels.volatility} · ${labels.totalSlippage}`}
        className={`app-backtest-evidence-strip ${compact ? 'sm:grid-flow-row sm:grid-cols-2 [&>div:nth-child(even)]:border-r-0 [&>div:nth-child(-n+2)]:border-b [&>div]:border-[var(--app-divider)]' : ''}`}
        items={metricStripItems.slice(4)}
      />
    </section>
  );
}
