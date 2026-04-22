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
    <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(250px,1fr))]">
      {items.map((item) => (
        <div key={item.label} className="app-surface-card p-5 lg:p-6">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {item.label}
          </div>
          <div className="mt-4 text-xl font-semibold sm:mt-5 sm:text-2xl lg:text-[2rem]">
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}
