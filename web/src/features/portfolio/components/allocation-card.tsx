import { useCopy } from "../../../app/copy";
import type { AllocationItem } from "../api";

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

export function AllocationCard({ items }: { items: AllocationItem[] }) {
  const copy = useCopy();

  if (items.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-4 text-sm app-muted sm:p-5">
        {copy.portfolio.allocation.empty}
      </div>
    );
  }

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="app-kicker mb-4 text-xs uppercase tracking-[0.18em]">
        {copy.portfolio.allocation.title}
      </div>
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.symbol} className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span>{item.name}</span>
              <span>{percent.format(item.weight)}</span>
            </div>
            <div className="app-progress-track h-2 overflow-hidden rounded-full">
              <div
                className="app-progress-fill h-full rounded-full"
                style={{ width: `${Math.max(item.weight * 100, 2)}%` }}
              />
            </div>
            <div className="app-muted text-xs">{currency.format(item.value)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
