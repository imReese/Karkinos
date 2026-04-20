import { useCopy } from "../../../app/copy";
import type { LedgerEntry } from "../api";

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});

export function ActivityFeed({ entries }: { entries: LedgerEntry[] }) {
  const copy = useCopy();

  if (entries.length === 0) {
    return <div className="app-panel rounded-2xl p-5 text-sm app-muted">{copy.activity.feed.empty}</div>;
  }

  return (
    <div className="app-panel rounded-2xl p-5">
      <div className="app-kicker mb-4 text-xs uppercase tracking-[0.18em]">
        {copy.activity.feed.title}
      </div>

      <div className="space-y-3">
        {entries.map((entry) => (
          <div key={entry.id} className="app-panel-strong rounded-xl px-4 py-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-medium">
                  {entry.entry_type}
                  {entry.symbol ? ` · ${entry.symbol}` : ""}
                </div>
                <div className="app-muted mt-1 text-xs">{entry.timestamp}</div>
              </div>
              <div className="app-soft text-sm">
                {entry.amount !== null
                  ? currency.format(entry.amount)
                  : entry.price !== null && entry.quantity !== null
                    ? currency.format(entry.price * entry.quantity)
                    : "--"}
              </div>
            </div>
            {entry.note ? <div className="app-muted mt-2 text-sm">{entry.note}</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}
