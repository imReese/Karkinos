import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import {
  formatCurrency,
  formatDateTime,
  formatPercent,
} from '../../../shared/format';
import {
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
import { formatPublicStatus } from '../../../shared/public-labels';
import type { AccountOverview } from '../api';

type OverviewCardMetrics = AccountOverview & {
  today_pnl?: number | null;
  today_pnl_breakdown?: {
    stocks?: number | null;
    funds?: number | null;
    total?: number | null;
  } | null;
  current_drawdown?: number | null;
};

type OverviewCardItem = {
  label: string;
  value: string;
  tone: 'anchor' | 'positive' | 'negative' | 'neutral';
  breakdown?: Array<{
    label: string;
    value: number;
    emphasis?: boolean;
  }>;
  contributors?: TodayPnlContributor[];
};

export type TodayPnlContributor = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  today_change: number | null;
};

function moneyTone(value: number) {
  if (value < 0) {
    return 'text-[var(--app-danger)]';
  }
  if (value > 0) {
    return 'text-[var(--app-success)]';
  }
  return 'text-[var(--app-soft)]';
}

function metricToneClass(tone: OverviewCardItem['tone']) {
  if (tone === 'positive') {
    return 'text-[var(--app-success)]';
  }
  if (tone === 'negative') {
    return 'text-[var(--app-danger)]';
  }
  return 'text-[var(--app-soft)]';
}

export function OverviewCards({
  overview,
  variant = 'rail',
}: {
  overview: OverviewCardMetrics;
  variant?: 'rail' | 'workbench';
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const valuationStatus = normalizeMarketDataStatus(overview.quote_status);
  const valuationStatusText =
    valuationStatus && !isConfirmedMarketDataStatus(valuationStatus)
      ? isCacheLikeMarketDataStatus(valuationStatus)
        ? copy.overview.cards.cachedValuation
        : copy.overview.cards.valuationStatus(
            formatPublicStatus(valuationStatus, locale),
          )
      : null;
  const todayBreakdown = {
    stocks: overview.today_pnl_breakdown?.stocks ?? 0,
    funds: overview.today_pnl_breakdown?.funds ?? 0,
    total: overview.today_pnl_breakdown?.total ?? overview.today_pnl ?? 0,
  };
  const items: OverviewCardItem[] = [
    {
      label: copy.overview.cards.totalAssets,
      value: formatCurrency(overview.total_equity),
      tone: 'anchor',
    },
    {
      label: copy.overview.cards.todayPnl,
      value: formatCurrency(todayBreakdown.total),
      tone: todayBreakdown.total >= 0 ? 'positive' : 'negative',
      breakdown: [
        {
          label: copy.overview.cards.todayStocks,
          value: todayBreakdown.stocks,
        },
        {
          label: copy.overview.cards.todayFunds,
          value: todayBreakdown.funds,
        },
        {
          label: copy.overview.cards.todayTotal,
          value: todayBreakdown.total,
          emphasis: true,
        },
      ],
      contributors: overview.today_contributors ?? [],
    },
    {
      label: copy.overview.cards.unrealizedPnl,
      value: formatCurrency(overview.unrealized_pnl),
      tone: overview.unrealized_pnl >= 0 ? 'positive' : 'negative',
    },
    {
      label: copy.overview.cards.cashRatio,
      value: formatPercent(overview.cash_ratio),
      tone: 'neutral',
    },
    {
      label: copy.overview.cards.currentDrawdown,
      value: formatPercent(overview.current_drawdown ?? 0),
      tone: (overview.current_drawdown ?? 0) > 0 ? 'negative' : 'neutral',
    },
  ];

  if (variant === 'workbench') {
    const [totalAssets, todayPnlItem, unrealizedPnl, cashRatio, drawdown] =
      items;
    const valuationBadge = valuationStatusText ? (
      <div className="mt-4 inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-warning)]">
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
        <span className="truncate">
          {valuationStatusText} {formatDateTime(overview.valuation_timestamp)}
        </span>
      </div>
    ) : null;

    return (
      <div
        data-testid="account-metrics-rail"
        className="app-terminal-panel grid min-w-0 self-start overflow-hidden rounded-[2rem] font-mono tabular-nums lg:grid-cols-[minmax(0,1.05fr)_minmax(290px,0.95fr)]"
      >
        <div className="relative min-w-0 border-b border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[radial-gradient(circle_at_0%_0%,color-mix(in_srgb,var(--app-accent)_16%,transparent),transparent_18rem)] p-5 lg:border-b-0 lg:border-r xl:p-6">
          <div className="absolute left-0 top-5 h-10 w-px bg-[linear-gradient(180deg,var(--app-accent-secondary),var(--app-accent))] shadow-[0_0_18px_color-mix(in_srgb,var(--app-accent)_38%,transparent)]" />
          <div className="app-kicker app-tier-4-label text-[10px] font-bold text-[var(--app-subtext-0)]">
            {totalAssets.label}
          </div>
          <div className="mt-3 truncate text-4xl font-semibold tracking-[-0.035em] text-[var(--app-text)] sm:text-[2.65rem] xl:text-5xl">
            {totalAssets.value}
          </div>
          <div className="mt-5 h-px w-36 bg-gradient-to-r from-[var(--app-accent)] to-transparent opacity-60" />
          {valuationBadge}

          <div className="mt-8 grid min-w-0 gap-3 sm:grid-cols-2">
            {[unrealizedPnl, drawdown].map((item) => (
              <div
                key={item.label}
                className="min-w-0 rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3"
              >
                <div className="app-kicker text-[10px] text-[var(--app-subtext-0)]">
                  {item.label}
                </div>
                <div
                  className={`mt-2 truncate text-xl font-semibold tracking-[-0.02em] ${metricToneClass(
                    item.tone,
                  )}`}
                >
                  {item.value}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
            <div className="min-w-0 rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_7%,transparent)] px-4 py-3">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-0)]">
                {copy.overview.cards.availableCash}
              </div>
              <div className="mt-2 truncate text-lg font-semibold text-[var(--app-soft)]">
                {formatCurrency(overview.available_cash)}
              </div>
            </div>
            <div className="min-w-0 rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_7%,transparent)] px-4 py-3">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-0)]">
                {copy.overview.cards.positionsCount}
              </div>
              <div className="mt-2 truncate text-lg font-semibold text-[var(--app-soft)]">
                {overview.positions_count}
              </div>
            </div>
          </div>
        </div>

        <div className="grid min-w-0 content-start divide-y divide-[color-mix(in_srgb,var(--app-border)_30%,transparent)]">
          <div className="min-w-0 p-5 xl:p-6">
            <div className="app-kicker app-tier-4-label text-[10px] font-bold text-[var(--app-subtext-0)]">
              {todayPnlItem.label}
            </div>
            <div className="mt-3 grid min-w-0 gap-2">
              {todayPnlItem.breakdown?.map((row) => (
                <div
                  key={row.label}
                  className="flex min-w-0 items-baseline justify-between gap-4 text-sm"
                >
                  <span className="min-w-0 truncate font-semibold text-[var(--app-subtext-0)]">
                    {row.label}
                  </span>
                  <span
                    className={`shrink-0 font-semibold tabular-nums ${moneyTone(
                      row.value,
                    )} ${row.emphasis ? 'text-base' : ''}`}
                  >
                    {formatCurrency(row.value)}
                  </span>
                </div>
              ))}
            </div>
            {todayPnlItem.contributors &&
            todayPnlItem.contributors.length > 0 ? (
              <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-3">
                <div className="app-kicker mb-2 text-[9px] text-[var(--app-subtext-1)]">
                  {copy.overview.cards.todayContributors}
                </div>
                <div className="grid min-w-0 gap-1.5">
                  {todayPnlItem.contributors.map((contributor) => {
                    const displayName =
                      contributor.display_name?.trim() ||
                      contributor.name?.trim() ||
                      contributor.symbol;
                    const value = contributor.today_change ?? 0;
                    return (
                      <a
                        key={contributor.symbol}
                        href={`/portfolio/${encodeURIComponent(
                          contributor.symbol,
                        )}`}
                        className="group/contributor flex min-w-0 items-baseline justify-between gap-3 rounded-xl px-1 py-0.5 text-[12px] transition-colors hover:bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)]"
                      >
                        <span className="min-w-0 truncate text-[var(--app-subtext-0)] group-hover/contributor:text-[var(--app-text)]">
                          {displayName}
                        </span>
                        <span
                          className={`shrink-0 font-semibold tabular-nums ${moneyTone(
                            value,
                          )}`}
                        >
                          {formatCurrency(value)}
                        </span>
                      </a>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>

          <div className="min-w-0 p-5 xl:p-6">
            <div className="app-kicker app-tier-4-label text-[10px] font-bold text-[var(--app-subtext-0)]">
              {cashRatio.label}
            </div>
            <div className="mt-3 text-2xl font-semibold tracking-[-0.02em] text-[var(--app-soft)]">
              {cashRatio.value}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="account-metrics-rail"
      className="app-terminal-panel grid min-w-0 overflow-hidden rounded-[2rem] font-mono tabular-nums sm:grid-cols-2 xl:grid-cols-[1.7fr_repeat(4,minmax(0,1fr))]"
    >
      {items.map((item, index) => (
        <div
          key={item.label}
          className={`group relative min-w-0 border-b border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-5 py-4 transition-[background-color,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] sm:border-r sm:border-b-0 xl:px-6 ${
            index === 0
              ? 'bg-[radial-gradient(circle_at_0%_0%,color-mix(in_srgb,var(--app-accent)_16%,transparent),transparent_18rem)] py-5'
              : ''
          }`}
        >
          <div
            className={`absolute left-0 top-4 h-8 w-px bg-[linear-gradient(180deg,var(--app-accent-secondary),var(--app-accent))] opacity-0 shadow-[0_0_18px_color-mix(in_srgb,var(--app-accent)_38%,transparent)] transition-opacity duration-300 group-hover:opacity-80 ${
              index === 0 ? 'opacity-100' : ''
            }`}
          />
          <div className="app-kicker app-tier-4-label text-[10px] font-bold text-[var(--app-subtext-0)]">
            {item.label}
          </div>
          {item.breakdown ? (
            <div className="mt-2 grid min-w-0 gap-2">
              <div className="grid min-w-0 gap-1.5">
                {item.breakdown.map((row) => (
                  <div
                    key={row.label}
                    className="flex min-w-0 items-baseline justify-between gap-3 text-xs"
                  >
                    <span className="min-w-0 truncate text-[var(--app-subtext-0)]">
                      {row.label}
                    </span>
                    <span
                      className={`shrink-0 font-semibold tabular-nums ${moneyTone(
                        row.value,
                      )} ${row.emphasis ? 'text-sm' : ''}`}
                    >
                      {formatCurrency(row.value)}
                    </span>
                  </div>
                ))}
              </div>
              {item.contributors && item.contributors.length > 0 ? (
                <div className="mt-1 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-2">
                  <div className="app-kicker mb-1.5 text-[9px] text-[var(--app-subtext-1)]">
                    {copy.overview.cards.todayContributors}
                  </div>
                  <div className="grid min-w-0 gap-1">
                    {item.contributors.map((contributor) => {
                      const displayName =
                        contributor.display_name?.trim() ||
                        contributor.name?.trim() ||
                        contributor.symbol;
                      const value = contributor.today_change ?? 0;
                      return (
                        <a
                          key={contributor.symbol}
                          href={`/portfolio/${encodeURIComponent(
                            contributor.symbol,
                          )}`}
                          className="group/contributor flex min-w-0 items-baseline justify-between gap-3 rounded-xl px-1 py-0.5 text-[11px] transition-colors hover:bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)]"
                        >
                          <span className="min-w-0 truncate text-[var(--app-subtext-0)] group-hover/contributor:text-[var(--app-text)]">
                            {displayName}
                          </span>
                          <span
                            className={`shrink-0 font-semibold tabular-nums ${moneyTone(
                              value,
                            )}`}
                          >
                            {formatCurrency(value)}
                          </span>
                        </a>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div
              className={`mt-2 truncate font-semibold tracking-[-0.035em] ${
                index === 0
                  ? 'text-3xl text-[var(--app-text)] sm:text-[2.15rem]'
                  : 'text-lg sm:text-xl'
              } ${
                item.tone === 'positive'
                  ? 'text-[var(--app-success)]'
                  : item.tone === 'negative'
                    ? 'text-[var(--app-danger)]'
                    : 'text-[var(--app-soft)]'
              }`}
            >
              {item.value}
            </div>
          )}
          {index === 0 ? (
            <>
              <div className="mt-3 h-px w-28 bg-gradient-to-r from-[var(--app-accent)] to-transparent opacity-60" />
              {valuationStatusText ? (
                <div className="mt-3 inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-warning)]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
                  <span className="truncate">
                    {valuationStatusText}{' '}
                    {formatDateTime(overview.valuation_timestamp)}
                  </span>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function OverviewCardsSkeleton() {
  return (
    <div
      data-testid="account-metrics-skeleton"
      aria-hidden="true"
      className="app-terminal-panel grid min-w-0 animate-pulse overflow-hidden rounded-[2rem] sm:grid-cols-2 xl:grid-cols-[1.7fr_repeat(4,minmax(0,1fr))]"
    >
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className="px-4 py-3 sm:px-5">
          <div className="h-3 w-24 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_76%,transparent)]" />
          <div className="mt-3 h-6 w-36 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_88%,transparent)] sm:h-7" />
        </div>
      ))}
    </div>
  );
}
