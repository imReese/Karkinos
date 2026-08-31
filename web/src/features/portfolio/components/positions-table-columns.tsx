import type { ColumnDef } from '@tanstack/react-table';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import { StatusBadge } from '../../../shared/ui/workbench';
import type { Position } from '../api';
import { quoteNeedsReview } from '../position-observation';
import {
  formatPositionAge,
  handlePositionLinkClick,
  holdingDetailHref,
  resolvePositionAssetClass,
  resolvePositionName,
  resolvePositionTone,
  type PositionsTableModel,
} from './positions-table-model';

type PortfolioCopy = ReturnType<typeof useCopy>;

function PositionNumericCell({
  value,
  tone = 'text-[var(--app-text)]',
}: {
  value: string;
  tone?: string;
}) {
  return (
    <span className={`block text-right font-medium tabular-nums ${tone}`}>
      {value}
    </span>
  );
}

export function buildPositionColumns({
  copy,
  locale,
  model,
}: {
  copy: PortfolioCopy;
  locale: Locale;
  model: PositionsTableModel;
}): ColumnDef<Position, unknown>[] {
  const labels = copy.portfolio.table;
  const detailLabels = copy.portfolio.detail;
  const symbolColumn: ColumnDef<Position, unknown> = {
    id: 'symbol',
    header: labels.symbol,
    cell: ({ row }) => {
      const position = row.original;
      const displayName = resolvePositionName(position);
      return (
        <a
          href={holdingDetailHref(position.symbol)}
          onClick={(event) =>
            handlePositionLinkClick(
              event,
              position.symbol,
              model.onOpenPosition,
            )
          }
          aria-label={`${labels.detailsTitle}: ${displayName} ${position.symbol}`}
          className="block min-w-40 font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)]"
          title={`${displayName} · ${position.symbol}`}
        >
          <span className="block max-w-52 truncate">{displayName}</span>
          <span className="app-type-micro mt-0.5 flex items-center gap-1.5 font-medium text-[var(--app-text-tertiary)]">
            <span className="font-mono">{position.symbol}</span>
            <span aria-hidden="true">·</span>
            <span className="truncate">
              {formatAssetClassLabel(
                resolvePositionAssetClass(position, model.assetClassBySymbol),
                copy.common,
              )}
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
        <PositionNumericCell
          value={formatCurrency(row.original.market_value)}
        />
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
        <PositionNumericCell
          value={formatCurrency(row.original.today_change)}
          tone={resolvePositionTone(row.original.today_change)}
        />
      </span>
    ),
  };
  const unrealizedColumn: ColumnDef<Position, unknown> = {
    id: 'unrealized',
    header: () => <span className="block text-right">{labels.unrealized}</span>,
    cell: ({ row }) => (
      <span data-testid={`position-unrealized-${row.original.symbol}`}>
        <PositionNumericCell
          value={formatCurrency(row.original.unrealized_pnl)}
          tone={resolvePositionTone(row.original.unrealized_pnl)}
        />
      </span>
    ),
  };
  const realizedColumn: ColumnDef<Position, unknown> = {
    id: 'realized',
    header: () => <span className="block text-right">{labels.realized}</span>,
    cell: ({ row }) => (
      <span data-testid={`position-realized-${row.original.symbol}`}>
        <PositionNumericCell
          value={formatCurrency(row.original.realized_pnl)}
          tone={resolvePositionTone(row.original.realized_pnl)}
        />
      </span>
    ),
  };
  const closedAtColumn: ColumnDef<Position, unknown> = {
    id: 'closed-at',
    header: labels.closedOn,
    cell: ({ row }) => (
      <span
        className="block whitespace-nowrap font-mono text-[var(--app-text-secondary)] tabular-nums"
        data-testid={`position-closed-at-${row.original.symbol}`}
      >
        {formatDate(row.original.closed_at)}
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
          <div className="mt-1 max-w-44 truncate text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
            {formatPositionAge(position.quote_age_seconds)} ·{' '}
            {formatTimestamp(position.quote_timestamp)}
          </div>
          {position.stale_reason ? (
            <div
              className={`mt-0.5 text-[length:var(--app-font-size-micro)] text-[var(--app-warning-text)] ${
                model.variant === 'dashboard'
                  ? 'max-w-full whitespace-normal [overflow-wrap:anywhere]'
                  : 'max-w-44 whitespace-normal [overflow-wrap:anywhere]'
              }`}
              data-testid="position-quote-stale-reason"
              title={staleReason}
            >
              {staleReason}
            </div>
          ) : null}
        </div>
      );
    },
  };

  if (model.showHistoryColumns) {
    return [
      symbolColumn,
      closedAtColumn,
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
            <PositionNumericCell
              value={formatCurrency(row.original.commission_paid)}
              tone="text-[var(--app-text-secondary)]"
            />
          </span>
        ),
      },
    ];
  }

  return [
    symbolColumn,
    marketValueColumn,
    ...(model.showFullColumns
      ? [
          {
            id: 'weight',
            header: () => (
              <span className="block text-right">{labels.weight}</span>
            ),
            cell: ({ row }: { row: { original: Position } }) => (
              <span data-testid={`position-weight-${row.original.symbol}`}>
                <PositionNumericCell
                  value={formatPercent(
                    model.weightBySymbol[row.original.symbol],
                  )}
                />
              </span>
            ),
          } satisfies ColumnDef<Position, unknown>,
        ]
      : []),
    todayColumn,
    unrealizedColumn,
    ...(model.showFullColumns ? [realizedColumn] : []),
    quoteColumn,
  ];
}
