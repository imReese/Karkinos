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
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatLedgerCostBasisMethodLabel } from '../../../shared/ledger-format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import { useRefreshMarketQuotesMutation } from '../../market/api';
import type { Position } from '../api';

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

function quoteNeedsReview(status: string | null | undefined) {
  return !['live', 'confirmed', 'cache'].includes(status ?? 'unknown');
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function resolveBrokerDisplayedUnitCost(position: Position) {
  return isFiniteNumber(position.broker_displayed_unit_cost) &&
    position.broker_displayed_unit_cost > 0
    ? position.broker_displayed_unit_cost
    : null;
}

function formatCostBasisStatus(
  labels: ReturnType<typeof useCopy>['portfolio']['detail'],
  status: string | null | undefined,
) {
  const normalized = status ?? 'unavailable';
  return (
    labels.costBasisStatuses[
      normalized as keyof typeof labels.costBasisStatuses
    ] ?? normalized
  );
}

function isProjectedLedgerCostBasis(status: string | null | undefined) {
  return status === 'projected_from_ledger';
}

function formatBrokerCostBasisDetail(
  labels: ReturnType<typeof useCopy>['portfolio']['detail'],
  locale: ReturnType<typeof usePreferences>['locale'],
  position: Position,
) {
  const method = isProjectedLedgerCostBasis(position.broker_cost_basis_status)
    ? labels.ledgerProjectedCostBasis
    : formatLedgerCostBasisMethodLabel(
        position.broker_cost_basis_method,
        locale,
      );
  const parts = [
    method,
    formatCostBasisStatus(labels, position.broker_cost_basis_status),
  ];
  if (
    isFiniteNumber(position.broker_cost_basis_difference) &&
    Math.abs(position.broker_cost_basis_difference) >= 0.005
  ) {
    parts.push(
      `${labels.costBasisDifference} ${formatCurrency(
        position.broker_cost_basis_difference,
      )}`,
    );
  }
  return parts.join(' · ');
}

function numericCell(value: string, tone = 'text-[var(--app-text)]') {
  return (
    <span
      className={`block text-right font-mono font-medium tabular-nums ${tone}`}
    >
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
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const showFullColumns = variant === 'full';
  const showHistoryColumns = variant === 'history';
  const hasQuotesNeedingReview = positions.some((position) =>
    quoteNeedsReview(position.quote_status),
  );

  const columns: ColumnDef<Position, unknown>[] = [
    {
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
            <span className="mt-0.5 block font-mono text-[11px] font-medium text-[var(--app-text-tertiary)]">
              {position.symbol}
            </span>
          </a>
        );
      },
    },
    {
      id: 'asset-class',
      header: labels.assetClass,
      cell: ({ row }) => {
        const position = row.original;
        const assetClass =
          position.asset_class ?? assetClassBySymbol[position.symbol] ?? '--';
        return (
          <span data-testid={`position-asset-class-${position.symbol}`}>
            <StatusBadge>
              {formatAssetClassLabel(assetClass, copy.common)}
            </StatusBadge>
          </span>
        );
      },
    },
    {
      id: 'quantity',
      header: () => <span className="block text-right">{labels.quantity}</span>,
      cell: ({ row }) => (
        <span data-testid={`position-quantity-${row.original.symbol}`}>
          {numericCell(
            formatQuantity(row.original.quantity),
            'text-[var(--app-text-secondary)]',
          )}
        </span>
      ),
    },
    ...(showFullColumns
      ? [
          {
            id: 'avg-cost',
            header: () => (
              <span className="block text-right">{detailLabels.avgCost}</span>
            ),
            cell: ({ row }: { row: { original: Position } }) => (
              <span data-testid={`position-avg-cost-${row.original.symbol}`}>
                {numericCell(
                  formatPrice(row.original.avg_cost),
                  'text-[var(--app-text-secondary)]',
                )}
              </span>
            ),
          },
          {
            id: 'broker-cost',
            header: () => (
              <span className="block text-right">
                {detailLabels.brokerDisplayedCost}
              </span>
            ),
            cell: ({ row }: { row: { original: Position } }) => {
              const unitCost = resolveBrokerDisplayedUnitCost(row.original);
              const detail =
                unitCost === null
                  ? undefined
                  : formatBrokerCostBasisDetail(
                      detailLabels,
                      locale,
                      row.original,
                    );
              return (
                <span
                  data-testid={`position-broker-cost-${row.original.symbol}`}
                  title={detail}
                >
                  {numericCell(
                    formatPrice(unitCost),
                    unitCost === null
                      ? 'text-[var(--app-text-tertiary)]'
                      : 'text-[var(--app-text)]',
                  )}
                  {detail ? (
                    <span className="mt-0.5 block max-w-48 whitespace-normal text-right text-[10px] leading-4 text-[var(--app-text-tertiary)]">
                      {detail}
                    </span>
                  ) : null}
                </span>
              );
            },
          },
        ]
      : []),
    {
      id: 'latest-price',
      header: () => (
        <span className="block text-right">{labels.latestPrice}</span>
      ),
      cell: ({ row }) => (
        <span data-testid={`position-latest-price-${row.original.symbol}`}>
          {numericCell(formatPrice(row.original.latest_price))}
        </span>
      ),
    },
    {
      id: 'market-value',
      header: () => (
        <span className="block text-right">{labels.marketValue}</span>
      ),
      cell: ({ row }) => (
        <span data-testid={`position-market-value-${row.original.symbol}`}>
          {numericCell(formatCurrency(row.original.market_value))}
        </span>
      ),
    },
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
          },
        ]
      : []),
    {
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
    },
    {
      id: 'unrealized',
      header: () => (
        <span className="block text-right">{labels.unrealized}</span>
      ),
      cell: ({ row }) => (
        <span data-testid={`position-unrealized-${row.original.symbol}`}>
          {numericCell(
            formatCurrency(row.original.unrealized_pnl),
            resolveTone(row.original.unrealized_pnl),
          )}
        </span>
      ),
    },
    ...(showFullColumns || showHistoryColumns
      ? [
          {
            id: 'realized',
            header: () => (
              <span className="block text-right">{labels.realized}</span>
            ),
            cell: ({ row }: { row: { original: Position } }) => (
              <span data-testid={`position-realized-${row.original.symbol}`}>
                {numericCell(
                  formatCurrency(row.original.realized_pnl),
                  resolveTone(row.original.realized_pnl),
                )}
              </span>
            ),
          },
        ]
      : []),
    ...(showFullColumns
      ? [
          {
            id: 'availability',
            header: () => (
              <span className="block text-right">{labels.availFrozen}</span>
            ),
            cell: ({ row }: { row: { original: Position } }) => (
              <span
                data-testid={`position-available-frozen-${row.original.symbol}`}
              >
                {numericCell(
                  `${formatQuantity(row.original.available_qty)} / ${formatQuantity(
                    row.original.frozen_qty,
                  )}`,
                  'text-[var(--app-text-secondary)]',
                )}
              </span>
            ),
          },
        ]
      : []),
    {
      id: 'quote-state',
      header: labels.quoteState,
      cell: ({ row }) => {
        const position = row.original;
        const needsReview = quoteNeedsReview(position.quote_status);
        return (
          <div className="min-w-32">
            <StatusBadge tone={needsReview ? 'warning' : 'success'}>
              {position.quote_status
                ? formatPublicStatus(position.quote_status, locale)
                : '--'}
            </StatusBadge>
            <div
              className="mt-1 max-w-40 truncate text-[10px] text-[var(--app-text-tertiary)]"
              title={formatStaleReason(
                position.stale_reason,
                copy.common.staleReasons,
              )}
            >
              {formatAge(position.quote_age_seconds)} ·{' '}
              {formatTimestamp(position.quote_timestamp)}
            </div>
            {position.stale_reason ? (
              <div className="mt-0.5 max-w-40 whitespace-normal text-[10px] leading-4 text-[var(--app-warning-text)]">
                {formatStaleReason(
                  position.stale_reason,
                  copy.common.staleReasons,
                )}
              </div>
            ) : null}
          </div>
        );
      },
    },
    {
      id: 'actions',
      header: () => <span className="block text-right">{labels.actions}</span>,
      cell: ({ row }) => {
        const position = row.original;
        const refreshing =
          refreshQuotes.isPending &&
          refreshQuotes.variables?.symbols?.includes(position.symbol);
        return (
          <div className="flex min-w-max justify-end gap-1">
            <a
              href={holdingDetailHref(position.symbol)}
              className="app-button-secondary rounded-[var(--app-radius-control)] px-2 py-1 text-[11px] font-semibold"
            >
              {labels.detailsTitle}
            </a>
            {!showHistoryColumns ? (
              <button
                type="button"
                className="app-button-secondary rounded-[var(--app-radius-control)] px-2 py-1 text-[11px] font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                disabled={refreshing}
                aria-busy={refreshing}
                onClick={() =>
                  void refreshQuotes.mutateAsync({
                    symbols: [position.symbol],
                    force: true,
                  })
                }
              >
                {refreshing ? labels.refreshing : labels.refresh}
              </button>
            ) : null}
            {showFullColumns ? (
              <>
                <a
                  href={symbolTradingHref(position.symbol)}
                  className="app-button-secondary rounded-[var(--app-radius-control)] px-2 py-1 text-[11px] font-semibold"
                >
                  {labels.trade}
                </a>
                <a
                  href={symbolActivityHref(position.symbol)}
                  className="app-button-secondary rounded-[var(--app-radius-control)] px-2 py-1 text-[11px] font-semibold"
                >
                  {labels.ledger}
                </a>
              </>
            ) : showHistoryColumns ? (
              <a
                href={symbolActivityHref(position.symbol)}
                className="app-button-secondary rounded-[var(--app-radius-control)] px-2 py-1 text-[11px] font-semibold"
              >
                {labels.ledger}
              </a>
            ) : null}
          </div>
        );
      },
    },
  ];

  return (
    <div className="min-w-0 space-y-2">
      {hasQuotesNeedingReview ? (
        <EvidenceState
          kind="partial"
          title={labels.cachedQuoteNotice}
          evidence={labels.quoteState}
        />
      ) : null}
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
  );
}
