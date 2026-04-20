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
    <div className="app-panel overflow-hidden rounded-2xl">
      <table className="w-full border-collapse text-left text-sm">
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
  );
}
