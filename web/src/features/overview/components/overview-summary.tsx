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

  const cumulativeValue =
    summary.cumulative_pnl == null
      ? labels.pendingValuation
      : formatCurrency(summary.cumulative_pnl);
  const cumulativeReturn =
    summary.cumulative_return == null
      ? null
      : formatPercent(summary.cumulative_return);

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
      value: cumulativeValue,
      returnValue: cumulativeReturn,
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
      style={{
        background:
          'linear-gradient(112deg, transparent 0%, transparent 68%, color-mix(in srgb, var(--app-accent) 6%, transparent) 100%)',
      }}
    >
      <div className="grid min-w-0 gap-5 py-5 lg:grid-cols-[minmax(18rem,0.78fr)_minmax(0,1.22fr)] lg:gap-0">
        <div className="min-w-0 lg:border-r lg:border-[var(--app-divider)] lg:pr-8">
          <div className="app-type-subsection-title font-semibold text-[var(--app-text-secondary)]">
            {copy.overview.cards.totalAssets}
          </div>
          <div
            data-testid="overview-total-value"
            className="app-type-overview-hero mt-2 whitespace-nowrap tabular-nums text-[var(--app-text)]"
          >
            {financialValue(summary.total_equity, labels.pendingValuation)}
          </div>
        </div>

        <div className="min-w-0 lg:pl-8">
          <dl className="grid min-w-0 gap-4 sm:grid-cols-2 sm:divide-x sm:divide-[var(--app-divider)]">
            {headlineMetrics.map((metric, index) => (
              <div
                key={metric.key}
                className={'min-w-0 ' + (index === 0 ? 'sm:pr-6' : 'sm:pl-6')}
              >
                <dt className="app-type-label font-semibold text-[var(--app-text-secondary)]">
                  {metric.label}
                </dt>
                <dd
                  data-testid={metric.testId}
                  className={
                    'mt-1 flex min-w-0 flex-wrap items-baseline gap-x-2 tabular-nums ' +
                    metric.tone
                  }
                >
                  <span className="app-type-overview-headline">
                    {metric.value}
                  </span>
                  {metric.returnValue ? (
                    <span className="app-type-compact font-semibold">
                      {metric.returnValue}
                    </span>
                  ) : null}
                </dd>
              </div>
            ))}
          </dl>

          <MetricStrip
            ariaLabel={copy.overview.cards.supportingMetrics}
            className="mt-5 border-b-0 bg-transparent"
            items={supportMetrics.map((metric) => ({
              id: metric.key,
              label: metric.label,
              value: metric.value,
              tone: metric.tone,
            }))}
          />
        </div>
      </div>
    </section>
  );
}
