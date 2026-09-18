import { formatCurrency, formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { AccountOverview } from '../overview-feature-boundary';
import {
  overviewPresentation,
  pnlTone,
  shortDate,
} from '../model/overview-presentation';

function financialValue(
  value: number | null | undefined,
  unavailableLabel: string,
) {
  return value == null ? unavailableLabel : formatCurrency(value);
}

export function OverviewSummary({ summary }: { summary: AccountOverview }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const totalUnavailable = summary.total_equity == null;
  const cumulativeUnavailable = summary.cumulative_pnl == null;
  const latestUnavailable = summary.today_pnl == null;

  const metrics = [
    {
      key: 'total',
      label: copy.overview.cards.totalAssets,
      value: financialValue(summary.total_equity, labels.pendingValuation),
      tone: 'text-[var(--app-text)]',
      testId: 'overview-total-value',
      detail: `${copy.overview.cards.netDeposits} ${formatCurrency(summary.total_deposits)} · ${labels.holdings} ${summary.positions_count}`,
      unavailable: totalUnavailable,
    },
    {
      key: 'cumulative',
      label: labels.cumulativePnl,
      value: financialValue(summary.cumulative_pnl, labels.pendingValuation),
      tone: cumulativeUnavailable
        ? 'text-[var(--app-text)]'
        : pnlTone(summary.cumulative_pnl),
      testId: 'overview-cumulative-pnl',
      detail:
        cumulativeUnavailable || summary.cumulative_return == null
          ? labels.returnUnavailable
          : formatPercent(summary.cumulative_return),
      unavailable: cumulativeUnavailable,
    },
    {
      key: 'latest',
      label: labels.latestPnl,
      value: financialValue(summary.today_pnl, labels.pendingValuation),
      tone: latestUnavailable
        ? 'text-[var(--app-text)]'
        : pnlTone(summary.today_pnl),
      testId: 'overview-session-pnl',
      detail: shortDate(summary.latest_session_date),
      unavailable: latestUnavailable,
    },
    {
      key: 'cash',
      label: copy.overview.cards.availableCash,
      value: formatCurrency(summary.available_cash),
      tone: 'text-[var(--app-text)]',
      detail:
        summary.cash_ratio == null
          ? labels.cashRatioUnavailable
          : `${formatPercent(summary.cash_ratio)} · ${copy.overview.cards.cashRatio}`,
      unavailable: false,
    },
    {
      key: 'holdings',
      label: labels.holdings,
      value: String(summary.positions_count),
      tone: 'text-[var(--app-text)]',
      detail: labels.holdingsDetail,
      unavailable: false,
    },
  ];

  return (
    <section
      data-testid="overview-summary"
      aria-label={copy.overview.cards.totalAssets}
      className="min-w-0 border-b border-[var(--app-divider)] py-4 sm:py-5"
    >
      <dl className="grid min-w-0 grid-cols-2 gap-y-5 sm:grid-cols-5 sm:gap-y-0 sm:divide-x sm:divide-[var(--app-divider)]">
        {metrics.map((metric, index) => (
          <div
            key={metric.key}
            className={`min-w-0 ${index === 0 ? 'sm:pr-5' : 'sm:px-5'} ${index === metrics.length - 1 ? 'sm:pr-0' : ''}`}
          >
            <dt className="text-xs font-medium text-[var(--app-text-secondary)]">
              {metric.label}
            </dt>
            <dd
              data-testid={metric.testId}
              className={`mt-1.5 text-[clamp(1.35rem,2.3vw,2rem)] leading-none font-semibold tracking-tight tabular-nums ${metric.tone}`}
            >
              {metric.value}
            </dd>
            <dd className="mt-2 truncate text-xs tabular-nums text-[var(--app-text-tertiary)]">
              {metric.detail}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
