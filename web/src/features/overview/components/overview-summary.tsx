import { formatCurrency, formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { AccountOverview } from '../overview-feature-boundary';
import {
  overviewPresentation,
  pnlTone,
  shortDate,
} from '../model/overview-presentation';

export function OverviewSummary({ summary }: { summary: AccountOverview }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  return (
    <section
      data-testid="overview-summary"
      aria-label={copy.overview.cards.totalAssets}
      className="min-w-0 py-4 sm:py-5"
    >
      <dl>
        <dt className="text-sm text-[var(--app-text-secondary)]">
          {copy.overview.cards.totalAssets}
        </dt>
        <dd
          data-testid="overview-total-value"
          className="mt-2 text-[clamp(2.25rem,4vw,3.25rem)] leading-none font-semibold tracking-tight tabular-nums text-[var(--app-text)]"
        >
          {formatCurrency(summary.total_equity)}
        </dd>
      </dl>
      <div className="mt-5 grid sm:mt-6 grid-cols-2 gap-x-5 gap-y-5 sm:grid-cols-3 sm:divide-x sm:divide-[var(--app-divider)]">
        <dl className="min-w-0 sm:pr-3">
          <dt className="text-xs text-[var(--app-text-secondary)]">
            {labels.cumulativePnl}
          </dt>
          <dd
            className={`mt-1.5 text-xl font-semibold tracking-tight tabular-nums ${pnlTone(summary.cumulative_pnl)}`}
            data-testid="overview-cumulative-pnl"
          >
            {formatCurrency(summary.cumulative_pnl)}
          </dd>
          <dd className="mt-1 text-xs text-[var(--app-text-tertiary)]">
            {summary.cumulative_return == null
              ? labels.returnUnavailable
              : formatPercent(summary.cumulative_return)}
          </dd>
        </dl>
        <dl className="min-w-0 sm:px-4">
          <dt className="text-xs text-[var(--app-text-secondary)]">
            {labels.latestPnl}
          </dt>
          <dd
            className={`mt-1.5 text-xl font-semibold tracking-tight tabular-nums ${pnlTone(summary.today_pnl)}`}
            data-testid="overview-session-pnl"
          >
            {formatCurrency(summary.today_pnl)}
          </dd>
          <dd className="mt-1 text-xs tabular-nums text-[var(--app-text-tertiary)]">
            {shortDate(summary.latest_session_date)}
          </dd>
        </dl>
        <dl className="min-w-0 sm:pl-4">
          <dt className="text-xs text-[var(--app-text-secondary)]">
            {copy.overview.cards.availableCash}
          </dt>
          <dd className="mt-1.5 text-xl font-semibold tracking-tight tabular-nums text-[var(--app-text)]">
            {formatCurrency(summary.available_cash)}
          </dd>
          <dd className="mt-1 text-xs tabular-nums text-[var(--app-text-tertiary)]">
            {formatPercent(summary.cash_ratio)} ·{' '}
            {copy.overview.cards.cashRatio}
          </dd>
        </dl>
      </div>
    </section>
  );
}
