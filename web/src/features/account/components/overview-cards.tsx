import { useCopy } from '../../../app/copy';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { AccountOverview } from '../api';

type OverviewCardMetrics = AccountOverview & {
  today_pnl?: number | null;
  current_drawdown?: number | null;
};

export function OverviewCards({ overview }: { overview: OverviewCardMetrics }) {
  const copy = useCopy();
  const items = [
    {
      label: copy.overview.cards.totalAssets,
      value: formatCurrency(overview.total_equity),
    },
    {
      label: copy.overview.cards.todayPnl,
      value: formatCurrency(overview.today_pnl ?? 0),
    },
    {
      label: copy.overview.cards.unrealizedPnl,
      value: formatCurrency(overview.unrealized_pnl),
    },
    {
      label: copy.overview.cards.cashRatio,
      value: formatPercent(overview.cash_ratio),
    },
    {
      label: copy.overview.cards.currentDrawdown,
      value: formatPercent(overview.current_drawdown ?? 0),
    },
  ];

  return (
    <div
      data-testid="account-metrics-rail"
      className="grid overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_22%,transparent)] divide-y divide-[color-mix(in_srgb,var(--app-border)_30%,transparent)] font-mono shadow-[0_18px_50px_rgba(17,17,27,0.12)] sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-5 xl:divide-x tabular-nums"
    >
      {items.map((item, index) => (
        <div
          key={item.label}
          className="group relative min-w-0 px-4 py-3 transition-colors duration-200 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] sm:px-5"
        >
          <div
            className={`absolute left-0 top-3 h-7 w-px bg-[var(--app-accent)] opacity-0 transition-opacity duration-200 group-hover:opacity-60 ${
              index === 0 ? 'opacity-60' : ''
            }`}
          />
          <div className="app-kicker app-tier-4-label text-[11px] font-bold text-[var(--app-subtext-0)]">
            {item.label}
          </div>
          <div className="mt-2 truncate text-lg font-semibold tracking-[-0.02em] sm:text-xl lg:text-[1.35rem]">
            {item.value}
          </div>
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
      className="grid animate-pulse overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_22%,transparent)] divide-y divide-[color-mix(in_srgb,var(--app-border)_26%,transparent)] shadow-[0_18px_50px_rgba(17,17,27,0.12)] sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-5 xl:divide-x"
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
