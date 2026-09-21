import type { ColumnDef } from '@tanstack/react-table';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatDate,
  formatPercent,
} from '../../../shared/format';
import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { PositionPricing } from '../../../shared/portfolio-evidence/position-pricing';
import type { Position } from '../api';
import {
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
    header:
      model.variant === 'dashboard'
        ? locale === 'zh'
          ? '标的'
          : 'Holding'
        : labels.symbol,
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
            {model.variant === 'dashboard' ? (
              <span className="rounded px-1.5 py-0.5 font-sans font-medium bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] border border-[var(--app-divider)]">
                {formatAssetClassLabel(
                  resolvePositionAssetClass(position, model.assetClassBySymbol),
                  copy.common,
                )}
              </span>
            ) : (
              <span className="truncate">
                {formatAssetClassLabel(
                  resolvePositionAssetClass(position, model.assetClassBySymbol),
                  copy.common,
                )}
              </span>
            )}
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
    cell: ({ row }) => (
      <PositionPricing position={row.original} locale={locale} />
    ),
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
    ...(model.showFullColumns || model.variant === 'dashboard'
      ? [
          {
            id: 'weight',
            header: () => (
              <span className="block text-right">{labels.weight}</span>
            ),
            cell: ({ row }: { row: { original: Position } }) => {
              const weight = model.weightBySymbol[row.original.symbol];
              const fillWidth = Math.max(0, Math.min(100, (weight ?? 0) * 100));
              return (
                <span data-testid={`position-weight-${row.original.symbol}`}>
                  <span className="inline-flex items-center justify-end gap-2.5">
                    <PositionNumericCell value={formatPercent(weight)} />
                    {model.variant === 'dashboard' ? (
                      <span
                        aria-hidden="true"
                        className="hidden sm:inline-block w-16 h-1.5 rounded-full bg-[var(--app-divider)] overflow-hidden"
                      >
                        <span
                          className="block h-full rounded-full bg-[var(--app-accent)]"
                          style={{ width: `${fillWidth}%` }}
                        />
                      </span>
                    ) : null}
                  </span>
                </span>
              );
            },
          } satisfies ColumnDef<Position, unknown>,
        ]
      : []),
    todayColumn,
    unrealizedColumn,
    ...(model.showFullColumns ? [realizedColumn] : []),
    ...(model.variant === 'dashboard' ? [] : [quoteColumn]),
  ];
}
