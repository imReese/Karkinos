import { useCopy } from '../../../app/copy';
import type { KeyboardEvent, MouseEvent } from 'react';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
  formatReturnPercent,
  formatTimestamp,
} from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { useRefreshMarketQuotesMutation } from '../../market/api';
import type { Position } from '../api';
import { formatStaleReason } from '../../../shared/stale-reason';

function holdingDetailHref(symbol: string) {
  return `/portfolio/${encodeURIComponent(symbol)}`;
}

function symbolActivityHref(symbol: string) {
  return `/activity?symbol=${encodeURIComponent(symbol)}`;
}

function symbolTradingHref(symbol: string) {
  return `/trading?symbol=${encodeURIComponent(symbol)}`;
}

function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(0, Math.round(seconds))}s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours}h`;
  }
  return `${Math.round(hours / 24)}d`;
}

function resolvePositionName(position: Position) {
  return position.display_name || position.name || position.symbol;
}

function resolvePnlPct(position: Position) {
  const costBasis = position.avg_cost * position.quantity;
  if (costBasis <= 0) {
    return null;
  }
  return position.unrealized_pnl / costBasis;
}

function detailAriaLabel(
  labels: ReturnType<typeof useCopy>['portfolio']['table'],
  displayName: string,
  symbol: string,
) {
  return `${labels.detailsTitle}: ${displayName} ${symbol}`;
}

function openHoldingDetail(href: string) {
  window.location.assign(href);
}

function stopEntryNavigation(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

function handleEntryKeyDown(event: KeyboardEvent<HTMLElement>, href: string) {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return;
  }
  event.preventDefault();
  openHoldingDetail(href);
}

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
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const showFullColumns = variant === 'full';
  const showDashboardColumns = variant === 'dashboard';
  const hasStaleQuotes = positions.some(
    (position) => position.quote_status === 'stale',
  );

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
      {hasStaleQuotes ? (
        <div className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
          <span className="truncate">{labels.cachedQuoteNotice}</span>
        </div>
      ) : null}
      <div className="grid gap-4 md:hidden">
        {positions.map((position) => {
          const pnlPositive = position.unrealized_pnl >= 0;
          const isStale = position.quote_status === 'stale';
          const displayName = resolvePositionName(position);
          const assetClass =
            position.asset_class ?? assetClassBySymbol[position.symbol] ?? '--';
          const assetClassDisplay = formatAssetClassLabel(
            assetClass,
            copy.common,
          );
          const staleReason = formatStaleReason(
            position.stale_reason,
            copy.common.staleReasons,
          );
          const detailHref = holdingDetailHref(position.symbol);
          const detailLabel = detailAriaLabel(
            labels,
            displayName,
            position.symbol,
          );
          const refreshing =
            refreshQuotes.isPending &&
            refreshQuotes.variables?.symbols?.includes(position.symbol);
          return (
            <div
              key={position.symbol}
              data-testid={`position-card-${position.symbol}`}
              className="app-panel cursor-pointer rounded-3xl p-4 transition-colors hover:border-[color-mix(in_srgb,var(--app-accent)_42%,transparent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
              tabIndex={0}
              aria-label={detailLabel}
              onClick={() => {
                openHoldingDetail(detailHref);
              }}
              onKeyDown={(event) => {
                handleEntryKeyDown(event, detailHref);
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <a
                    href={detailHref}
                    className="text-base font-semibold text-[var(--app-text)] underline-offset-4 transition-colors hover:text-[var(--app-accent)] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
                    aria-label={detailLabel}
                    onClick={stopEntryNavigation}
                  >
                    {displayName}
                  </a>
                  <div className="mt-1 font-mono text-xs font-medium text-[var(--app-soft)]">
                    {position.symbol}
                  </div>
                  <div className="app-muted mt-1 text-xs">
                    {assetClassDisplay}
                  </div>
                  {isStale ? (
                    <div
                      className="mt-2 inline-flex items-center gap-1 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_30%,transparent)] px-2 py-0.5 text-[10px] font-semibold text-[var(--app-warning)]"
                      title={staleReason}
                    >
                      {labels.cachedQuoteAt(
                        formatTimestamp(position.quote_timestamp),
                      )}
                    </div>
                  ) : null}
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
                  [
                    labels.returnPct,
                    formatReturnPercent(resolvePnlPct(position)),
                  ],
                  [labels.quoteAge, formatAge(position.quote_age_seconds)],
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
              <div className="mt-4 grid grid-cols-2 gap-2">
                <a
                  href={detailHref}
                  className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
                  onClick={stopEntryNavigation}
                >
                  {labels.detailsTitle}
                </a>
                <button
                  type="button"
                  className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={refreshing}
                  aria-busy={refreshing}
                  onClick={(event) => {
                    stopEntryNavigation(event);
                    void refreshQuotes.mutateAsync({
                      symbols: [position.symbol],
                      force: true,
                    });
                  }}
                >
                  {refreshing ? labels.refreshing : labels.refresh}
                </button>
                <a
                  href={symbolTradingHref(position.symbol)}
                  className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
                  onClick={stopEntryNavigation}
                >
                  {labels.trade}
                </a>
                <a
                  href={symbolActivityHref(position.symbol)}
                  className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
                  onClick={stopEntryNavigation}
                >
                  {labels.ledger}
                </a>
              </div>
            </div>
          );
        })}
      </div>

      <div
        data-testid="positions-table-scroll"
        className="hidden min-w-0 max-w-full overflow-x-auto overscroll-x-contain rounded-[26px] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_18%,transparent)] md:block"
      >
        <table
          data-testid="positions-table-desktop"
          className="app-data-table w-full min-w-[1180px] text-left text-sm"
        >
          <thead className="app-kicker text-xs uppercase tracking-[0.16em]">
            <tr>
              <th className="px-4 py-3">{labels.symbol}</th>
              <th className="px-4 py-3">{labels.assetClass}</th>
              <th className="px-4 py-3 text-right">{labels.quantity}</th>
              <th className="px-4 py-3 text-right">{labels.avgCost}</th>
              <th className="px-4 py-3 text-right">{labels.latestPrice}</th>
              <th className="px-4 py-3 text-right">{labels.marketValue}</th>
              <th className="px-4 py-3 text-right">{labels.unrealized}</th>
              <th className="px-4 py-3 text-right">{labels.returnPct}</th>
              <th className="px-4 py-3">{labels.quoteState}</th>
              {showFullColumns ? (
                <>
                  <th className="px-4 py-3 text-right">{labels.availFrozen}</th>
                  <th className="px-4 py-3 text-right">{labels.realized}</th>
                </>
              ) : null}
              <th className="px-4 py-3 text-right">{labels.actions}</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => {
              const pnlPositive = position.unrealized_pnl >= 0;
              const isStale = position.quote_status === 'stale';
              const displayName = resolvePositionName(position);
              const assetClass =
                position.asset_class ??
                assetClassBySymbol[position.symbol] ??
                '--';
              const assetClassDisplay = formatAssetClassLabel(
                assetClass,
                copy.common,
              );
              const staleReason = formatStaleReason(
                position.stale_reason,
                copy.common.staleReasons,
              );
              const detailHref = holdingDetailHref(position.symbol);
              const detailLabel = detailAriaLabel(
                labels,
                displayName,
                position.symbol,
              );
              const refreshing =
                refreshQuotes.isPending &&
                refreshQuotes.variables?.symbols?.includes(position.symbol);
              return (
                <tr
                  key={position.symbol}
                  data-testid={`position-row-${position.symbol}`}
                  className="group cursor-pointer transition-colors hover:bg-[color-mix(in_srgb,var(--app-accent)_5%,transparent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--app-focus)]"
                  tabIndex={0}
                  aria-label={detailLabel}
                  onClick={() => {
                    openHoldingDetail(detailHref);
                  }}
                  onKeyDown={(event) => {
                    handleEntryKeyDown(event, detailHref);
                  }}
                >
                  <td className="px-4 py-3.5 text-[var(--app-text)]">
                    <span className="flex min-w-44 items-start gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-accent)] opacity-70 transition-opacity group-hover:opacity-100" />
                      <span className="min-w-0">
                        <a
                          href={detailHref}
                          className="block truncate font-semibold underline-offset-4 transition-colors hover:text-[var(--app-accent)] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
                          aria-label={detailLabel}
                          onClick={stopEntryNavigation}
                        >
                          {displayName}
                        </a>
                        <span className="mt-1 block truncate font-mono text-xs font-medium text-[var(--app-muted)]">
                          {position.symbol}
                        </span>
                      </span>
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-[var(--app-muted)]">
                    <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-2.5 py-1 text-xs">
                      {assetClassDisplay}
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
                  <td
                    className={`px-4 py-3.5 text-right font-mono font-semibold tabular-nums ${
                      pnlPositive
                        ? 'text-[var(--app-success)]'
                        : 'text-[var(--app-danger)]'
                    }`}
                  >
                    {formatReturnPercent(resolvePnlPct(position))}
                  </td>
                  <td className="px-4 py-3.5">
                    <div className="flex min-w-36 flex-col gap-1">
                      <span
                        className={`w-max rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                          isStale
                            ? 'border-[color-mix(in_srgb,var(--app-warning)_30%,transparent)] text-[var(--app-warning)]'
                            : 'border-[color-mix(in_srgb,var(--app-success)_30%,transparent)] text-[var(--app-success)]'
                        }`}
                        title={staleReason}
                      >
                        {isStale
                          ? labels.cachedQuoteAt(
                              formatTimestamp(position.quote_timestamp),
                            )
                          : (position.quote_status ?? '--')}
                      </span>
                      <span className="app-muted text-[10px]">
                        {labels.quoteAge}:{' '}
                        {formatAge(position.quote_age_seconds)}
                      </span>
                      {position.stale_reason ? (
                        <span className="app-muted max-w-40 truncate text-[10px]">
                          {staleReason}
                        </span>
                      ) : null}
                    </div>
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
                  <td className="px-4 py-3.5 text-right">
                    <div
                      className={`inline-flex justify-end gap-1.5 ${
                        showDashboardColumns ? 'min-w-36' : 'min-w-44'
                      }`}
                    >
                      <a
                        href={detailHref}
                        className="app-button-secondary rounded-xl px-2.5 py-1.5 text-[11px] font-semibold"
                        onClick={stopEntryNavigation}
                      >
                        {labels.detailsTitle}
                      </a>
                      <button
                        type="button"
                        className="app-button-secondary rounded-xl px-2.5 py-1.5 text-[11px] font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                        disabled={refreshing}
                        aria-busy={refreshing}
                        onClick={(event) => {
                          stopEntryNavigation(event);
                          void refreshQuotes.mutateAsync({
                            symbols: [position.symbol],
                            force: true,
                          });
                        }}
                      >
                        {refreshing ? labels.refreshing : labels.refresh}
                      </button>
                      {!showDashboardColumns ? (
                        <>
                          <a
                            href={symbolTradingHref(position.symbol)}
                            className="app-button-secondary rounded-xl px-2.5 py-1.5 text-[11px] font-semibold"
                            onClick={stopEntryNavigation}
                          >
                            {labels.trade}
                          </a>
                          <a
                            href={symbolActivityHref(position.symbol)}
                            className="app-button-secondary rounded-xl px-2.5 py-1.5 text-[11px] font-semibold"
                            onClick={stopEntryNavigation}
                          >
                            {labels.ledger}
                          </a>
                        </>
                      ) : null}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
