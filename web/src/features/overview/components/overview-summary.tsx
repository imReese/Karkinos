import { formatCurrency, formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
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
    summary.total_equity == null && summary.indicative_total_equity != null;

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
      className="overview-hero min-w-0 border-b border-[var(--app-divider)] pb-4"
    >
      <dl className="grid min-w-0 gap-4 py-4 sm:grid-cols-[minmax(0,1.4fr)_repeat(2,minmax(0,1fr))] sm:items-end sm:gap-6">
        <div className="min-w-0">
          <dt className="text-xs font-medium text-[var(--app-text-secondary)]">
            {copy.overview.cards.totalAssets}
          </dt>
          <dd
            data-testid="overview-total-value"
            className="mt-1 break-words app-type-overview-hero tabular-nums text-[var(--app-text)]"
          >
            {financialValue(
              showIndicativeTotal
                ? summary.indicative_total_equity
                : summary.total_equity,
              labels.pendingValuation,
            )}
          </dd>
          {showIndicativeTotal ? (
            <p
              data-testid="overview-total-value-note"
              className="mt-1 text-xs leading-5 text-[var(--app-warning-text)]"
            >
              {summary.indicative_fund_nav_date
                ? `${labels.indicativeValue} · ${labels.fundNavAsOf} ${summary.indicative_fund_nav_date}`
                : `${labels.indicativeValue} · ${labels.referenceQuotePending}`}
            </p>
          ) : null}
        </div>
        <div className="grid grid-cols-2 gap-4 sm:contents">
          {headlineMetrics.map((metric) => (
            <div
              key={metric.key}
              data-testid={metric.testId}
              className="min-w-0 sm:border-l sm:border-[var(--app-divider)] sm:pl-6"
            >
              <dt className="text-xs text-[var(--app-text-secondary)]">
                {metric.label}
              </dt>
              <dd
                className={`mt-1 break-words app-type-overview-headline tabular-nums ${metric.tone}`}
              >
                {metric.value}
                {metric.returnValue ? (
                  <span className="ml-2 text-sm">{metric.returnValue}</span>
                ) : null}
              </dd>
              {metric.key === 'latest' && summary.latest_session_date ? (
                <p className="mt-1 text-xs tabular-nums text-[var(--app-text-tertiary)]">
                  {summary.latest_session_date}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      </dl>
      <dl
        aria-label={copy.overview.cards.supportingMetrics}
        className="overview-hero-support grid min-w-0 grid-cols-2 gap-x-6 gap-y-2 border-t border-[var(--app-divider)] pt-3 sm:grid-cols-4"
      >
        {supportMetrics.map((metric) => (
          <div
            key={metric.key}
            className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1"
          >
            <dt className="text-xs text-[var(--app-text-secondary)]">
              {metric.label}
            </dt>
            <dd
              className={`break-words text-sm font-medium tabular-nums ${metric.tone === 'pnl-positive' ? 'text-[var(--app-pnl-positive)]' : metric.tone === 'pnl-negative' ? 'text-[var(--app-pnl-negative)]' : 'text-[var(--app-text)]'}`}
            >
              {metric.value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
