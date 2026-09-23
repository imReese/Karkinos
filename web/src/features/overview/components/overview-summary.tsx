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
  const showIndicativeTotal =
    summary.total_equity == null &&
    summary.indicative_total_equity != null &&
    Boolean(summary.indicative_fund_nav_date);

  const headlineMetrics = [
    {
      key: 'latest',
      label: labels.latestPnl,
      value: financialValue(summary.today_pnl, labels.pendingValuation),
      isPending: summary.today_pnl == null,
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
      isPending: false,
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
      className="overview-hero min-w-0 border-b border-[var(--app-divider)] pb-6"
    >
      <div className="flex flex-col gap-5 py-2">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-baseline sm:justify-between">
          <div className="space-y-1">
            <div className="app-type-label font-semibold uppercase tracking-wider text-[var(--app-text-secondary)]">
              {copy.overview.cards.totalAssets}
            </div>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
              <span
                data-testid="overview-total-value"
                className="app-type-overview-hero whitespace-nowrap tabular-nums text-[var(--app-text)] font-extrabold tracking-tight"
              >
                {financialValue(
                  showIndicativeTotal
                    ? summary.indicative_total_equity
                    : summary.total_equity,
                  labels.pendingValuation,
                )}
              </span>
              {showIndicativeTotal ? (
                <span
                  data-testid="overview-total-value-note"
                  className="app-type-micro text-[var(--app-warning-text)]"
                >
                  {labels.indicativeValue} · {labels.fundNavAsOf}{' '}
                  {summary.indicative_fund_nav_date}
                </span>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                {headlineMetrics.map((metric) => (
                  <div
                    key={metric.key}
                    data-testid={metric.testId}
                    className={
                      'inline-flex min-w-0 items-center gap-1.5 tabular-nums ' +
                      metric.tone
                    }
                  >
                    {metric.isPending ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-2.5 py-1 text-xs font-semibold text-[var(--app-warning-text)]">
                        <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning-indicator)]" />
                        {metric.value}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/70 px-2.5 py-0.5 text-xs font-semibold text-[var(--app-text)]">
                        <span className="text-[var(--app-text-secondary)]">
                          {metric.label}
                        </span>
                        <span className={metric.tone}>{metric.value}</span>
                        {metric.returnValue ? (
                          <span className="text-[var(--app-text-tertiary)]">
                            {metric.returnValue}
                          </span>
                        ) : null}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <div className="app-type-micro text-[var(--app-text-tertiary)]">
              {copy.overview.modeHelper}
            </div>
          </div>
        </div>

        <MetricStrip
          ariaLabel={copy.overview.cards.supportingMetrics}
          className="overview-hero-support rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 divide-x divide-[var(--app-divider)] overflow-hidden"
          items={supportMetrics.map((metric) => ({
            id: metric.key,
            label: metric.label,
            value: metric.value,
            tone: metric.tone,
          }))}
        />
      </div>
    </section>
  );
}
