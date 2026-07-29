import type { ColumnDef } from '@tanstack/react-table';

import { useCopy } from '../../../app/copy';
import {
  DataTable,
  EvidenceState,
  StatusBadge,
} from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import type { Position } from '../api';
import { quoteNeedsReview } from '../position-observation';

function holdingDetailHref(symbol: string) {
  return `/portfolio/${encodeURIComponent(symbol)}`;
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
  return hours < 48 ? `${hours}h` : `${Math.round(hours / 24)}d`;
}

function resolvePositionName(position: Position) {
  return position.display_name || position.name || position.symbol;
}

function resolveTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return 'text-[var(--app-text)]';
  }
  return value > 0
    ? 'text-[var(--app-pnl-positive)]'
    : 'text-[var(--app-pnl-negative)]';
}

function numericCell(value: string, tone = 'text-[var(--app-text)]') {
  return (
    <span className={`block text-right font-medium tabular-nums ${tone}`}>
      {value}
    </span>
  );
}

export function PositionsTable({
  positions,
  assetClassBySymbol = {},
  weightBySymbol = {},
  variant = 'full',
}: {
  positions: Position[];
  assetClassBySymbol?: Record<string, string>;
  weightBySymbol?: Record<string, number | null | undefined>;
  variant?: 'full' | 'dashboard' | 'history';
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.portfolio.table;
  const detailLabels = copy.portfolio.detail;
  const showFullColumns = variant === 'full';
  const showHistoryColumns = variant === 'history';
  const hasQuotesNeedingReview = positions.some((position) =>
    quoteNeedsReview(position.quote_status),
  );
  const assetClassFor = (position: Position) =>
    position.asset_class ?? assetClassBySymbol[position.symbol] ?? 'unknown';

  const symbolColumn: ColumnDef<Position, unknown> = {
    id: 'symbol',
    header: labels.symbol,
    cell: ({ row }) => {
      const position = row.original;
      const displayName = resolvePositionName(position);
      return (
        <a
          href={holdingDetailHref(position.symbol)}
          aria-label={`${labels.detailsTitle}: ${displayName} ${position.symbol}`}
          className="block min-w-40 font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)]"
          title={`${displayName} · ${position.symbol}`}
        >
          <span className="block max-w-52 truncate">{displayName}</span>
          <span className="mt-0.5 flex items-center gap-1.5 text-[11px] font-medium text-[var(--app-text-tertiary)]">
            <span className="font-mono">{position.symbol}</span>
            <span aria-hidden="true">·</span>
            <span className="truncate">
              {formatAssetClassLabel(assetClassFor(position), copy.common)}
            </span>
          </span>
        </a>
      );
    },
  };
  const marketValueColumn: ColumnDef<Position, unknown> = {
    id: 'market-value',
    header: () => (
      <span className="block text-right">{labels.marketValue}</span>
    ),
    cell: ({ row }) => (
      <span data-testid={`position-market-value-${row.original.symbol}`}>
        {numericCell(formatCurrency(row.original.market_value))}
      </span>
    ),
  };
  const todayColumn: ColumnDef<Position, unknown> = {
    id: 'today-change',
    header: () => (
      <span className="block text-right">{labels.todayChange}</span>
    ),
    cell: ({ row }) => (
      <span data-testid={`position-today-change-${row.original.symbol}`}>
        {numericCell(
          formatCurrency(row.original.today_change),
          resolveTone(row.original.today_change),
        )}
      </span>
    ),
  };
  const unrealizedColumn: ColumnDef<Position, unknown> = {
    id: 'unrealized',
    header: () => <span className="block text-right">{labels.unrealized}</span>,
    cell: ({ row }) => (
      <span data-testid={`position-unrealized-${row.original.symbol}`}>
        {numericCell(
          formatCurrency(row.original.unrealized_pnl),
          resolveTone(row.original.unrealized_pnl),
        )}
      </span>
    ),
  };
  const realizedColumn: ColumnDef<Position, unknown> = {
    id: 'realized',
    header: () => <span className="block text-right">{labels.realized}</span>,
    cell: ({ row }) => (
      <span data-testid={`position-realized-${row.original.symbol}`}>
        {numericCell(
          formatCurrency(row.original.realized_pnl),
          resolveTone(row.original.realized_pnl),
        )}
      </span>
    ),
  };
  const quoteColumn: ColumnDef<Position, unknown> = {
    id: 'quote-state',
    header: labels.quoteState,
    cell: ({ row }) => {
      const position = row.original;
      const needsReview = quoteNeedsReview(position.quote_status);
      const staleReason = formatStaleReason(
        position.stale_reason,
        copy.common.staleReasons,
      );
      return (
        <div className="min-w-32">
          <StatusBadge tone={needsReview ? 'warning' : 'success'}>
            {position.quote_status
              ? formatPublicStatus(position.quote_status, locale)
              : '--'}
          </StatusBadge>
          <div className="mt-1 max-w-44 truncate text-[10px] text-[var(--app-text-tertiary)]">
            {formatAge(position.quote_age_seconds)} ·{' '}
            {formatTimestamp(position.quote_timestamp)}
          </div>
          {position.stale_reason ? (
            <div
              className="mt-0.5 max-w-44 truncate text-[10px] text-[var(--app-warning-text)]"
              title={staleReason}
            >
              {staleReason}
            </div>
          ) : null}
        </div>
      );
    },
  };
  const columns: ColumnDef<Position, unknown>[] = showHistoryColumns
    ? [
        symbolColumn,
        realizedColumn,
        {
          id: 'commission-paid',
          header: () => (
            <span className="block text-right">
              {detailLabels.commissionPaid}
            </span>
          ),
          cell: ({ row }) => (
            <span data-testid={`position-commission-${row.original.symbol}`}>
              {numericCell(
                formatCurrency(row.original.commission_paid),
                'text-[var(--app-text-secondary)]',
              )}
            </span>
          ),
        },
      ]
    : [
        symbolColumn,
        marketValueColumn,
        ...(showFullColumns
          ? [
              {
                id: 'weight',
                header: () => (
                  <span className="block text-right">{labels.weight}</span>
                ),
                cell: ({ row }: { row: { original: Position } }) => (
                  <span data-testid={`position-weight-${row.original.symbol}`}>
                    {numericCell(
                      formatPercent(weightBySymbol[row.original.symbol]),
                    )}
                  </span>
                ),
              } satisfies ColumnDef<Position, unknown>,
            ]
          : []),
        todayColumn,
        unrealizedColumn,
        ...(showFullColumns ? [realizedColumn] : []),
        quoteColumn,
      ];

  return (
    <div className="min-w-0 space-y-2">
      {variant === 'dashboard' && hasQuotesNeedingReview ? (
        <EvidenceState
          kind="partial"
          title={labels.cachedQuoteNotice}
          evidence={labels.quoteState}
        />
      ) : null}

      {positions.length > 0 ? (
        <ul
          data-testid="positions-mobile-list"
          className="min-w-0 max-w-full divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] md:hidden"
        >
          {positions.map((position) => {
            const displayName = resolvePositionName(position);
            const needsReview = quoteNeedsReview(position.quote_status);
            const staleReason = formatStaleReason(
              position.stale_reason,
              copy.common.staleReasons,
            );
            return (
              <li className="min-w-0 max-w-full" key={position.symbol}>
                <a
                  href={holdingDetailHref(position.symbol)}
                  data-testid={`position-mobile-row-${position.symbol}`}
                  aria-label={`${labels.detailsTitle}: ${displayName} ${position.symbol}`}
                  className={`app-position-mobile-row block w-full min-w-0 max-w-full px-1 text-[var(--app-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                    variant === 'dashboard' ? 'py-2.5' : 'py-3'
                  }`}
                >
                  <div className="flex min-w-0 items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">
                        {displayName}
                      </div>
                      <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-[var(--app-text-tertiary)]">
                        <span className="shrink-0 font-mono font-medium">
                          {position.symbol}
                        </span>
                        <span aria-hidden="true">·</span>
                        <span className="truncate">
                          {formatAssetClassLabel(
                            assetClassFor(position),
                            copy.common,
                          )}
                        </span>
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div
                        className={`text-sm font-semibold tabular-nums ${
                          showHistoryColumns
                            ? resolveTone(position.realized_pnl)
                            : 'text-[var(--app-text)]'
                        }`}
                      >
                        {formatCurrency(
                          showHistoryColumns
                            ? position.realized_pnl
                            : position.market_value,
                        )}
                      </div>
                      <div className="mt-0.5 text-[10px] text-[var(--app-text-tertiary)]">
                        {showHistoryColumns
                          ? labels.realized
                          : labels.marketValue}
                      </div>
                      {variant === 'dashboard' ? (
                        <>
                          <div
                            className={`mt-1 text-xs font-semibold tabular-nums ${resolveTone(
                              position.today_change,
                            )}`}
                          >
                            <span className="sr-only">
                              {labels.todayChange}:{' '}
                            </span>
                            {formatCurrency(position.today_change)}
                          </div>
                          <div
                            className={`mt-0.5 text-[10px] tabular-nums ${resolveTone(
                              position.unrealized_pnl,
                            )}`}
                          >
                            {labels.unrealized}{' '}
                            {formatCurrency(position.unrealized_pnl)}
                          </div>
                        </>
                      ) : null}
                    </div>
                  </div>

                  {variant !== 'dashboard' ? (
                    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                      {showHistoryColumns ? (
                        <div className="min-w-0">
                          <dt className="text-[10px] text-[var(--app-text-tertiary)]">
                            {detailLabels.commissionPaid}
                          </dt>
                          <dd className="mt-0.5 truncate text-xs tabular-nums text-[var(--app-text-secondary)]">
                            {formatCurrency(position.commission_paid)}
                          </dd>
                        </div>
                      ) : (
                        <>
                          {showFullColumns ? (
                            <div className="min-w-0">
                              <dt className="text-[10px] text-[var(--app-text-tertiary)]">
                                {labels.weight}
                              </dt>
                              <dd className="mt-0.5 truncate text-xs font-medium tabular-nums">
                                {formatPercent(weightBySymbol[position.symbol])}
                              </dd>
                            </div>
                          ) : null}
                          <div className="min-w-0">
                            <dt className="text-[10px] text-[var(--app-text-tertiary)]">
                              {labels.todayChange}
                            </dt>
                            <dd
                              className={`mt-0.5 truncate text-xs font-medium tabular-nums ${resolveTone(
                                position.today_change,
                              )}`}
                            >
                              {formatCurrency(position.today_change)}
                            </dd>
                          </div>
                          <div className="min-w-0">
                            <dt className="text-[10px] text-[var(--app-text-tertiary)]">
                              {labels.unrealized}
                            </dt>
                            <dd
                              className={`mt-0.5 truncate text-xs font-medium tabular-nums ${resolveTone(
                                position.unrealized_pnl,
                              )}`}
                            >
                              {formatCurrency(position.unrealized_pnl)}
                            </dd>
                          </div>
                          {showFullColumns ? (
                            <div className="min-w-0">
                              <dt className="text-[10px] text-[var(--app-text-tertiary)]">
                                {labels.realized}
                              </dt>
                              <dd
                                className={`mt-0.5 truncate text-xs font-medium tabular-nums ${resolveTone(
                                  position.realized_pnl,
                                )}`}
                              >
                                {formatCurrency(position.realized_pnl)}
                              </dd>
                            </div>
                          ) : null}
                        </>
                      )}
                    </dl>
                  ) : null}

                  {!showHistoryColumns ? (
                    <div
                      className={`flex min-w-0 items-center gap-2 ${
                        variant === 'dashboard'
                          ? 'mt-1.5'
                          : 'mt-3 border-t border-[var(--app-divider)] pt-2'
                      }`}
                    >
                      <StatusBadge tone={needsReview ? 'warning' : 'success'}>
                        {position.quote_status
                          ? formatPublicStatus(position.quote_status, locale)
                          : '--'}
                      </StatusBadge>
                      <span className="min-w-0 truncate text-[10px] text-[var(--app-text-tertiary)]">
                        {formatAge(position.quote_age_seconds)} ·{' '}
                        {formatTimestamp(position.quote_timestamp)}
                      </span>
                      {position.stale_reason ? (
                        <span
                          className="min-w-0 truncate text-[10px] text-[var(--app-warning-text)]"
                          title={staleReason}
                        >
                          {staleReason}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </a>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="border-y border-[var(--app-divider)] px-3 py-4 text-sm text-[var(--app-text-secondary)] md:hidden">
          {copy.portfolio.positionsEmpty}
        </div>
      )}

      <div className="hidden min-w-0 md:block">
        <DataTable
          className="app-positions-table"
          data={positions}
          columns={columns}
          caption={labels.symbol}
          emptyState={copy.portfolio.positionsEmpty}
          getRowId={(position) => position.symbol}
          rowLabel={(position) =>
            `${labels.detailsTitle}: ${resolvePositionName(position)} ${
              position.symbol
            }`
          }
          rowHref={(position) => holdingDetailHref(position.symbol)}
          rowTestId={(position) => `position-row-${position.symbol}`}
          scrollTestId="positions-table-scroll"
          tableTestId="positions-table-desktop"
        />
      </div>
    </div>
  );
}
