import { formatCurrency, formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { MetricStrip } from '../../../shared/ui/workbench';
import type { AccountOverview } from '../overview-feature-boundary';
import { overviewPresentation, pnlTone } from '../model/overview-presentation';

function financialValue(
  value: number | null | undefined,
  unavailableLabel: string,
) {
  return value == null ? unavailableLabel : formatCurrency(value);
}

function supportMetricTone(value: number | null | undefined) {
  if (value == null || value === 0) return 'neutral' as const;
  return value > 0 ? ('pnl-positive' as const) : ('pnl-negative' as const);
}

export function OverviewSummary({ summary }: { summary: AccountOverview }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];

  const headlineMetrics = [
    {
      key: 'latest',
      label: labels.latestPnl,
      value: financialValue(summary.today_pnl, labels.pendingValuation),
      returnValue: null,
      tone:
        summary.today_pnl == null
          ? 'text-[var(--app-text)]'
          : pnlTone(summary.today_pnl),
      testId: 'overview-session-pnl',
    },
    {
      key: 'cumulative',
      label: copy.overview.cards.cumulativePnl,
      value: financialValue(summary.cumulative_pnl, labels.pendingValuation),
      returnValue:
        summary.cumulative_return == null
          ? null
          : formatPercent(summary.cumulative_return),
      tone:
        summary.cumulative_pnl == null
          ? 'text-[var(--app-text)]'
          : pnlTone(summary.cumulative_pnl),
      testId: 'overview-cumulative-pnl',
    },
  ];

  const supportMetrics = [
    {
      key: 'cash',
      label: copy.overview.cards.availableCash,
      value: financialValue(summary.available_cash, labels.pendingValuation),
      tone: 'neutral' as const,
    },
    {
      key: 'deposits',
      label: copy.overview.cards.netDeposits,
      value: financialValue(summary.total_deposits, labels.pendingValuation),
      tone: 'neutral' as const,
    },
    {
      key: 'realized',
      label: copy.overview.breakdown.realizedPnl,
      value: financialValue(summary.realized_pnl, labels.pendingValuation),
      tone: supportMetricTone(summary.realized_pnl),
    },
    {
      key: 'unrealized',
      label: copy.overview.cards.unrealizedPnl,
      value: financialValue(summary.unrealized_pnl, labels.pendingValuation),
      tone: supportMetricTone(summary.unrealized_pnl),
    },
  ];

  return (
    <section
      data-testid="overview-summary"
      aria-label={copy.overview.cards.totalAssets}
      className="overview-hero min-w-0 border-b border-[var(--app-divider)]"
    >
      <div className="grid min-w-0 gap-4 py-3.5 md:grid-cols-[minmax(16rem,1.25fr)_minmax(12rem,0.9fr)_minmax(12rem,0.9fr)] md:items-end md:gap-0 md:divide-x md:divide-[var(--app-divider)]">
        <div className="min-w-0 md:pr-7">
          <div className="app-type-label font-semibold text-[var(--app-text-secondary)]">
            {copy.overview.cards.totalAssets}
          </div>
          <div
            data-testid="overview-total-value"
            className="app-type-overview-hero mt-1 whitespace-nowrap tabular-nums text-[var(--app-text)]"
          >
            {financialValue(summary.total_equity, labels.pendingValuation)}
          </div>
        </div>

        {headlineMetrics.map((metric) => (
          <div key={metric.key} className="min-w-0 md:px-7">
            <div className="app-type-label font-semibold text-[var(--app-text-secondary)]">
              {metric.label}
            </div>
            <div
              data-testid={metric.testId}
              className={
                'mt-1 flex min-w-0 flex-wrap items-baseline gap-x-2 tabular-nums ' +
                metric.tone
              }
            >
              <span className="app-type-overview-headline">{metric.value}</span>
              {metric.returnValue ? (
                <span className="app-type-compact font-semibold">
                  {metric.returnValue}
                </span>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      <MetricStrip
        ariaLabel={copy.overview.cards.supportingMetrics}
        className="overview-hero-support border-b-0 bg-transparent"
        items={supportMetrics.map((metric) => ({
          id: metric.key,
          label: metric.label,
          value: metric.value,
          tone: metric.tone,
        }))}
      />
    </section>
  );
}
