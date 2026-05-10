import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
} from '../../../shared/format';
import type { Position } from '../api';

export function PositionsTable({
  positions,
  assetClassBySymbol = {},
  latestPriceBySymbol = {},
  variant = 'full',
}: {
  positions: Position[];
  assetClassBySymbol?: Record<string, string>;
  latestPriceBySymbol?: Record<string, number | null | undefined>;
  variant?: 'full' | 'dashboard';
}) {
  const copy = useCopy();
  const labels = copy.portfolio.table;
  const showFullColumns = variant === 'full';

  const resolveLatestPrice = (position: Position) => {
    const livePrice = latestPriceBySymbol[position.symbol];
    if (typeof livePrice === 'number' && Number.isFinite(livePrice)) {
      return livePrice;
    }
    if (position.quantity > 0) {
      return position.market_value / position.quantity;
    }
    return null;
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:hidden">
        {positions.map((position) => (
          <div key={position.symbol} className="app-panel rounded-2xl p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-base font-semibold">{position.symbol}</div>
                <div className="app-muted mt-1 text-sm">
                  {assetClassBySymbol[position.symbol] ?? '--'}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold">
                  {formatCurrency(position.market_value)}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {labels.marketValue}
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {[
                [labels.quantity, formatQuantity(position.quantity)],
                [labels.avgCost, formatCurrency(position.avg_cost)],
                [labels.latestPrice, formatPrice(resolveLatestPrice(position))],
                [labels.marketValue, formatCurrency(position.market_value)],
                [labels.unrealized, formatCurrency(position.unrealized_pnl)],
                ...(showFullColumns
                  ? ([
                      [
                        labels.availFrozen,
                        `${formatQuantity(position.available_qty)} / ${formatQuantity(position.frozen_qty)}`,
                      ],
                      [labels.realized, formatCurrency(position.realized_pnl)],
                    ] as Array<[string, string]>)
                  : []),
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="app-panel-strong rounded-2xl px-4 py-3"
                >
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
              <th className="px-4 py-3">{labels.avgCost}</th>
              <th className="px-4 py-3">{labels.latestPrice}</th>
              <th className="px-4 py-3">{labels.marketValue}</th>
              <th className="px-4 py-3">{labels.unrealized}</th>
              {showFullColumns ? (
                <>
                  <th className="px-4 py-3">{labels.availFrozen}</th>
                  <th className="px-4 py-3">{labels.realized}</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => (
              <tr
                key={position.symbol}
                className="border-t"
                style={{ borderColor: 'var(--app-border)' }}
              >
                <td className="px-4 py-3 font-medium">{position.symbol}</td>
                <td className="px-4 py-3">
                  {assetClassBySymbol[position.symbol] ?? '--'}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatQuantity(position.quantity)}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatCurrency(position.avg_cost)}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatPrice(resolveLatestPrice(position))}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatCurrency(position.market_value)}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatCurrency(position.unrealized_pnl)}
                </td>
                {showFullColumns ? (
                  <>
                    <td className="px-4 py-3">
                      {formatQuantity(position.available_qty)} /{' '}
                      {formatQuantity(position.frozen_qty)}
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {formatCurrency(position.realized_pnl)}
                    </td>
                  </>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
