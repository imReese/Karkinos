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

function metricTone(value: number | null | undefined) {
  if (value == null || value === 0) return 'neutral' as const;
  return value > 0 ? ('pnl-positive' as const) : ('pnl-negative' as const);
}

export function OverviewSummary({ summary }: { summary: AccountOverview }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const latestUnavailable = summary.today_pnl == null;
  const cumulativeUnavailable = summary.cumulative_pnl == null;

  const primaryMetrics = [
    {
      key: 'total',
      label: copy.overview.cards.totalAssets,
      value: financialValue(summary.total_equity, labels.pendingValuation),
      tone: 'text-[var(--app-text)]',
      testId: 'overview-total-value',
      primary: true,
    },
    {
      key: 'cumulative',
      label: copy.overview.cards.cumulativePnl,
      value:
        summary.cumulative_pnl == null
          ? labels.pendingValuation
          : summary.cumulative_return == null
            ? formatCurrency(summary.cumulative_pnl)
            : `${formatCurrency(summary.cumulative_pnl)} · ${formatPercent(
                summary.cumulative_return,
              )}`,
      tone: cumulativeUnavailable
        ? 'text-[var(--app-text)]'
        : pnlTone(summary.cumulative_pnl),
      testId: 'overview-cumulative-pnl',
    },
    {
      key: 'latest',
      label: labels.latestPnl,
      value: financialValue(summary.today_pnl, labels.pendingValuation),
      tone: latestUnavailable
        ? 'text-[var(--app-text)]'
        : pnlTone(summary.today_pnl),
      testId: 'overview-session-pnl',
    },
    {
      key: 'cash',
      label: copy.overview.cards.availableCash,
      value:
        summary.cash_ratio == null
          ? formatCurrency(summary.available_cash)
          : `${formatCurrency(summary.available_cash)} · ${formatPercent(
              summary.cash_ratio,
            )}`,
      tone: 'text-[var(--app-text)]',
    },
  ];

  return (
    <section
      data-testid="overview-summary"
      aria-label={copy.overview.cards.totalAssets}
      className="min-w-0 border-b border-[var(--app-divider)]"
    >
      <dl className="grid min-w-0 grid-cols-2 gap-y-4 py-4 lg:grid-cols-[1.35fr_repeat(3,minmax(0,1fr))] lg:gap-y-0 lg:divide-x lg:divide-[var(--app-divider)]">
        {primaryMetrics.map((metric, index) => (
          <div
            key={metric.key}
            className={index === 0 ? 'min-w-0 pr-4 lg:pr-6' : 'min-w-0 lg:px-6'}
          >
            <dt className="app-type-label font-medium text-[var(--app-text-secondary)]">
              {metric.label}
            </dt>
            <dd
              data-testid={metric.testId}
              className={
                (metric.primary
                  ? 'app-type-primary-metric '
                  : 'app-type-metric ') +
                'mt-1 tabular-nums ' +
                metric.tone
              }
            >
              {metric.value}
            </dd>
          </div>
        ))}
      </dl>

      <MetricStrip
        ariaLabel={copy.overview.cards.supportingMetrics}
        className="overview-supporting-metrics border-b-0"
        items={[
          {
            id: 'deposits',
            label: copy.overview.cards.netDeposits,
            value: financialValue(
              summary.total_deposits,
              labels.pendingValuation,
            ),
          },
          {
            id: 'realized',
            label: copy.overview.breakdown.realizedPnl,
            value: financialValue(
              summary.realized_pnl,
              labels.pendingValuation,
            ),
            tone: metricTone(summary.realized_pnl),
          },
          {
            id: 'unrealized',
            label: copy.overview.cards.unrealizedPnl,
            value: financialValue(
              summary.unrealized_pnl,
              labels.pendingValuation,
            ),
            tone: metricTone(summary.unrealized_pnl),
          },
          {
            id: 'positions',
            label: copy.overview.cards.positionsCount,
            value: String(summary.positions_count),
          },
        ]}
      />
    </section>
  );
}
