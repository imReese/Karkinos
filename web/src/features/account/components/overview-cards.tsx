import { useCopy } from "../../../app/copy";
import type { AccountOverview } from "../api";

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function OverviewCards({ overview }: { overview: AccountOverview }) {
  const copy = useCopy();
  const items = [
    {
      label: copy.overview.cards.totalAssets,
      value: currency.format(overview.total_equity),
    },
    {
      label: copy.overview.cards.availableCash,
      value: currency.format(overview.available_cash),
    },
    {
      label: copy.overview.cards.unrealizedPnl,
      value: currency.format(overview.unrealized_pnl),
    },
    {
      label: copy.overview.cards.cashRatio,
      value: percent.format(overview.cash_ratio),
    },
  ];

  return (
    <div
      data-testid="account-metrics-rail"
      className="grid overflow-hidden rounded-xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_22%,transparent)] divide-y divide-[color-mix(in_srgb,var(--app-border)_30%,transparent)] sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4 xl:divide-x tabular-nums"
    >
      {items.map((item, index) => (
        <div
          key={item.label}
          className="group relative min-w-0 px-4 py-3 transition-colors duration-200 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] sm:px-5"
        >
          <div
            className={`absolute left-0 top-3 h-7 w-px bg-[var(--app-accent)] opacity-0 transition-opacity duration-200 group-hover:opacity-60 ${
              index === 0 ? "opacity-60" : ""
            }`}
          />
          <div className="app-kicker text-[10px] uppercase tracking-[0.18em]">
            {item.label}
          </div>
          <div className="mt-2 truncate text-lg font-medium tracking-[-0.02em] sm:text-xl lg:text-[1.35rem]">
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
      className="grid animate-pulse overflow-hidden rounded-xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_22%,transparent)] divide-y divide-[color-mix(in_srgb,var(--app-border)_26%,transparent)] sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4 xl:divide-x"
    >
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="px-4 py-3 sm:px-5">
          <div className="h-3 w-24 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_76%,transparent)]" />
          <div className="mt-3 h-6 w-36 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_88%,transparent)] sm:h-7" />
        </div>
      ))}
    </div>
  );
}
