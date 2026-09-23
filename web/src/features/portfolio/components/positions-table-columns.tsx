import type { ColumnDef } from '@tanstack/react-table';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatQuantity,
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
  className = '',
}: {
  value: string;
  tone?: string;
  className?: string;
}) {
  return (
    <span
      className={`block text-right font-medium tabular-nums ${tone} ${className}`.trim()}
    >
      {value}
    </span>
  );
}

function formatSignedPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return '--';
  }
  return formatPercent(value, {
    signDisplay: 'exceptZero',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatPriceCompact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) {
    return '--';
  }
  const hasSubCent = Math.round(value * 100) !== value * 100;
  return formatCurrency(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: hasSubCent ? 4 : 2,
  });
}

function resolvePositionMarketValueSubtext(
  position: Position,
  locale: Locale,
): string | null {
  const hasLatestPrice =
    position.latest_price != null && position.latest_price > 0;
  const hasAvgCost = position.avg_cost != null && position.avg_cost > 0;

  if (hasLatestPrice && hasAvgCost) {
    const costPrefix = locale === 'zh' ? '成本' : 'Cost';
    return `${formatPriceCompact(position.latest_price)} · ${costPrefix} ${formatPriceCompact(position.avg_cost)}`;
  }
  if (hasLatestPrice) {
    return formatPriceCompact(position.latest_price);
  }
  if (hasAvgCost) {
    const costPrefix = locale === 'zh' ? '成本' : 'Cost';
    return `${costPrefix} ${formatPriceCompact(position.avg_cost)}`;
  }
  return null;
}

function resolvePositionTodayChangePct(position: Position): number | null {
  if (
    position.today_change_pct != null &&
    Number.isFinite(position.today_change_pct)
  ) {
    return position.today_change_pct;
  }
  if (
    position.today_change != null &&
    Number.isFinite(position.today_change) &&
    position.market_value != null &&
    Number.isFinite(position.market_value)
  ) {
    const priorValue = position.market_value - position.today_change;
    if (priorValue > 0) {
      return position.today_change / priorValue;
    }
  }
  return null;
}

function resolvePositionUnrealizedPct(position: Position): number | null {
  if (
    position.unrealized_pnl == null ||
    !Number.isFinite(position.unrealized_pnl)
  ) {
    return null;
  }
  const costBasis =
    position.quantity > 0 && position.avg_cost > 0
      ? position.quantity * position.avg_cost
      : position.market_value != null && Number.isFinite(position.market_value)
        ? position.market_value - position.unrealized_pnl
        : null;
  if (costBasis != null && costBasis > 0) {
    return position.unrealized_pnl / costBasis;
  }
  return null;
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
    cell: ({ row }) => {
      const position = row.original;
      const subtext = resolvePositionMarketValueSubtext(position, locale);
      return (
        <span data-testid={`position-market-value-${position.symbol}`}>
          <PositionNumericCell value={formatCurrency(position.market_value)} />
          {subtext ? (
            <span
              className="app-type-micro mt-0.5 block text-right font-medium tabular-nums text-[var(--app-text-tertiary)]"
              title={`${locale === 'zh' ? '持仓数量' : 'Quantity'}: ${formatQuantity(position.quantity)}`}
            >
              {subtext}
            </span>
          ) : null}
        </span>
      );
    },
  };
  const todayColumn: ColumnDef<Position, unknown> = {
    id: 'today-change',
    header: () => (
      <span className="block text-right">{labels.todayChange}</span>
    ),
    cell: ({ row }) => {
      const position = row.original;
      const changePct = resolvePositionTodayChangePct(position);
      const tone = resolvePositionTone(position.today_change);
      const pctTone = resolvePositionTone(changePct ?? position.today_change);
      return (
        <span data-testid={`position-today-change-${position.symbol}`}>
          <PositionNumericCell
            value={formatCurrency(position.today_change)}
            tone={tone}
          />
          {changePct != null ? (
            <span
              className={`app-type-micro mt-0.5 block text-right font-medium tabular-nums ${pctTone}`}
            >
              {formatSignedPercent(changePct)}
            </span>
          ) : null}
        </span>
      );
    },
  };
  const unrealizedColumn: ColumnDef<Position, unknown> = {
    id: 'unrealized',
    header: () => <span className="block text-right">{labels.unrealized}</span>,
    cell: ({ row }) => {
      const position = row.original;
      const pnlPct = resolvePositionUnrealizedPct(position);
      const tone = resolvePositionTone(position.unrealized_pnl);
      const pctTone = resolvePositionTone(pnlPct ?? position.unrealized_pnl);
      return (
        <span data-testid={`position-unrealized-${position.symbol}`}>
          <PositionNumericCell
            value={formatCurrency(position.unrealized_pnl)}
            tone={tone}
          />
          {pnlPct != null ? (
            <span
              className={`app-type-micro mt-0.5 block text-right font-medium tabular-nums ${pctTone}`}
            >
              {formatSignedPercent(pnlPct)}
            </span>
          ) : null}
        </span>
      );
    },
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
                <div
                  data-testid={`position-weight-${row.original.symbol}`}
                  className="flex flex-col items-end justify-center w-full"
                >
                  <PositionNumericCell
                    value={formatPercent(weight)}
                    className="shrink-0"
                  />
                  {model.variant === 'dashboard' ? (
                    <span
                      aria-hidden="true"
                      className="hidden sm:inline-block w-16 h-1.5 rounded-full bg-[var(--app-divider)] overflow-hidden shrink-0 mt-1"
                    >
                      <span
                        className="block h-full rounded-full bg-[var(--app-accent)]"
                        style={{ width: `${fillWidth}%` }}
                      />
                    </span>
                  ) : null}
                </div>
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
