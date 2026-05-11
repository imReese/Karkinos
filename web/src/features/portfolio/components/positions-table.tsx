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
        {positions.map((position) => {
          const pnlPositive = position.unrealized_pnl >= 0;
          return (
            <div key={position.symbol} className="app-panel rounded-3xl p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-mono text-base font-semibold">
                    {position.symbol}
                  </div>
                  <div className="app-muted mt-1 text-sm">
                    {assetClassBySymbol[position.symbol] ?? '--'}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm font-semibold tabular-nums">
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
                  [
                    labels.latestPrice,
                    formatPrice(resolveLatestPrice(position)),
                  ],
                  [labels.marketValue, formatCurrency(position.market_value)],
                  [labels.unrealized, formatCurrency(position.unrealized_pnl)],
                  ...(showFullColumns
                    ? ([
                        [
                          labels.availFrozen,
                          `${formatQuantity(position.available_qty)} / ${formatQuantity(position.frozen_qty)}`,
                        ],
                        [
                          labels.realized,
                          formatCurrency(position.realized_pnl),
                        ],
                      ] as Array<[string, string]>)
                    : []),
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3"
                  >
                    <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                      {label}
                    </div>
                    <div
                      className={`mt-2 font-mono text-sm font-medium tabular-nums ${
                        label === labels.unrealized
                          ? pnlPositive
                            ? 'text-[var(--app-success)]'
                            : 'text-[var(--app-danger)]'
                          : ''
                      }`}
                    >
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="hidden overflow-x-auto rounded-[26px] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_18%,transparent)] md:block">
        <table className="app-data-table w-full min-w-[880px] text-left text-sm">
          <thead className="app-kicker text-xs uppercase tracking-[0.16em]">
            <tr>
              <th className="px-4 py-3">{labels.symbol}</th>
              <th className="px-4 py-3">{labels.assetClass}</th>
              <th className="px-4 py-3 text-right">{labels.quantity}</th>
              <th className="px-4 py-3 text-right">{labels.avgCost}</th>
              <th className="px-4 py-3 text-right">{labels.latestPrice}</th>
              <th className="px-4 py-3 text-right">{labels.marketValue}</th>
              <th className="px-4 py-3 text-right">{labels.unrealized}</th>
              {showFullColumns ? (
                <>
                  <th className="px-4 py-3 text-right">{labels.availFrozen}</th>
                  <th className="px-4 py-3 text-right">{labels.realized}</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => {
              const pnlPositive = position.unrealized_pnl >= 0;
              return (
                <tr key={position.symbol} className="group">
                  <td className="px-4 py-3.5 font-mono font-semibold tracking-[-0.01em] text-[var(--app-text)]">
                    <span className="inline-flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-accent)] opacity-70 transition-opacity group-hover:opacity-100" />
                      {position.symbol}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-[var(--app-muted)]">
                    <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-2.5 py-1 text-xs">
                      {assetClassBySymbol[position.symbol] ?? '--'}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono tabular-nums text-[var(--app-soft)]">
                    {formatQuantity(position.quantity)}
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono tabular-nums text-[var(--app-soft)]">
                    {formatCurrency(position.avg_cost)}
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono tabular-nums text-[var(--app-text)]">
                    {formatPrice(resolveLatestPrice(position))}
                  </td>
                  <td className="px-4 py-3.5 text-right font-mono font-semibold tabular-nums text-[var(--app-text)]">
                    {formatCurrency(position.market_value)}
                  </td>
                  <td
                    className={`px-4 py-3.5 text-right font-mono font-semibold tabular-nums ${
                      pnlPositive
                        ? 'text-[var(--app-success)]'
                        : 'text-[var(--app-danger)]'
                    }`}
                  >
                    {formatCurrency(position.unrealized_pnl)}
                  </td>
                  {showFullColumns ? (
                    <>
                      <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                        {formatQuantity(position.available_qty)} /{' '}
                        {formatQuantity(position.frozen_qty)}
                      </td>
                      <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                        {formatCurrency(position.realized_pnl)}
                      </td>
                    </>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
