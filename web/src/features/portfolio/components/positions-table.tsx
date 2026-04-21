import { useCopy } from "../../../app/copy";
import type { Position } from "../api";

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});

export function PositionsTable({
  positions,
  assetClassBySymbol = {},
}: {
  positions: Position[];
  assetClassBySymbol?: Record<string, string>;
}) {
  const copy = useCopy();
  const labels = copy.portfolio.table;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:hidden">
        {positions.map((position) => (
          <div key={position.symbol} className="app-panel rounded-2xl p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-base font-semibold">{position.symbol}</div>
                <div className="app-muted mt-1 text-sm">
                  {assetClassBySymbol[position.symbol] ?? "--"}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold">
                  {currency.format(position.market_value)}
                </div>
                <div className="app-muted mt-1 text-xs">{labels.marketValue}</div>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {[
                [labels.quantity, String(position.quantity)],
                [labels.availFrozen, `${position.available_qty} / ${position.frozen_qty}`],
                [labels.avgCost, currency.format(position.avg_cost)],
                [labels.unrealized, currency.format(position.unrealized_pnl)],
                [labels.realized, currency.format(position.realized_pnl)],
              ].map(([label, value]) => (
                <div key={label} className="app-panel-strong rounded-2xl px-4 py-3">
                  <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                    {label}
                  </div>
                  <div className="mt-2 text-sm font-medium">{value}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="app-panel hidden overflow-x-auto rounded-2xl md:block">
        <table className="w-full min-w-[880px] border-collapse text-left text-sm">
          <thead className="app-panel-strong app-kicker text-xs uppercase tracking-[0.16em]">
            <tr>
              <th className="px-4 py-3">{labels.symbol}</th>
              <th className="px-4 py-3">{labels.assetClass}</th>
              <th className="px-4 py-3">{labels.quantity}</th>
              <th className="px-4 py-3">{labels.availFrozen}</th>
              <th className="px-4 py-3">{labels.avgCost}</th>
              <th className="px-4 py-3">{labels.marketValue}</th>
              <th className="px-4 py-3">{labels.unrealized}</th>
              <th className="px-4 py-3">{labels.realized}</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => (
              <tr
                key={position.symbol}
                className="border-t"
                style={{ borderColor: "var(--app-border)" }}
              >
                <td className="px-4 py-3 font-medium">{position.symbol}</td>
                <td className="px-4 py-3">{assetClassBySymbol[position.symbol] ?? "--"}</td>
                <td className="px-4 py-3">{position.quantity}</td>
                <td className="px-4 py-3">
                  {position.available_qty} / {position.frozen_qty}
                </td>
                <td className="px-4 py-3">{currency.format(position.avg_cost)}</td>
                <td className="px-4 py-3">{currency.format(position.market_value)}</td>
                <td className="px-4 py-3">{currency.format(position.unrealized_pnl)}</td>
                <td className="px-4 py-3">{currency.format(position.realized_pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
