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
      tone: 'anchor',
    },
    {
      label: copy.overview.cards.todayPnl,
      value: formatCurrency(overview.today_pnl ?? 0),
      tone: (overview.today_pnl ?? 0) >= 0 ? 'positive' : 'negative',
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

  return (
    <div
      data-testid="account-metrics-rail"
      className="app-terminal-panel grid overflow-hidden rounded-[2rem] font-mono tabular-nums sm:grid-cols-2 xl:grid-cols-[1.7fr_repeat(4,minmax(0,1fr))]"
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
          {index === 0 ? (
            <div className="mt-3 h-px w-28 bg-gradient-to-r from-[var(--app-accent)] to-transparent opacity-60" />
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
      className="app-terminal-panel grid animate-pulse overflow-hidden rounded-[2rem] sm:grid-cols-2 xl:grid-cols-[1.7fr_repeat(4,minmax(0,1fr))]"
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
