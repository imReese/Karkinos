import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
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

function TableSortHeader({
  label,
  columnKey,
  activeKey,
  direction,
  onSort,
  align = 'right',
  locale = 'zh',
}: {
  label: string;
  columnKey: string;
  activeKey?: string;
  direction?: 'asc' | 'desc';
  onSort?: (key: string, direction?: 'asc' | 'desc') => void;
  align?: 'left' | 'right';
  locale?: Locale;
}) {
  if (!onSort) {
    return (
      <span
        className={`block ${align === 'right' ? 'text-right' : 'text-left'}`}
      >
        {label}
      </span>
    );
  }
  const isActive = activeKey === columnKey;
  const initialDir = columnKey === 'symbol' ? 'asc' : 'desc';
  const nextDir = isActive
    ? direction === 'desc'
      ? 'asc'
      : 'desc'
    : initialDir;

  return (
    <div
      className={`flex items-center ${
        align === 'right' ? 'justify-end' : 'justify-start'
      }`}
    >
      <button
        type="button"
        onClick={() => onSort(columnKey, nextDir)}
        className={`group/col-hdr inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold transition-all hover:bg-[var(--app-surface-overlay)] active:scale-[0.98] ${
          isActive
            ? 'text-[var(--app-accent)] font-semibold'
            : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
        }`}
        title={`${label}: ${
          isActive
            ? direction === 'asc'
              ? locale === 'zh'
                ? '升序'
                : 'Asc'
              : locale === 'zh'
                ? '降序'
                : 'Desc'
            : locale === 'zh'
              ? '点击排序'
              : 'Click to sort'
        }`}
        data-testid={`positions-sort-${columnKey}`}
      >
        <span>{label}</span>
        {isActive ? (
          direction === 'asc' ? (
            <ArrowUp
              size={11}
              strokeWidth={2.2}
              className="shrink-0 text-[var(--app-accent)]"
            />
          ) : (
            <ArrowDown
              size={11}
              strokeWidth={2.2}
              className="shrink-0 text-[var(--app-accent)]"
            />
          )
        ) : (
          <ArrowUpDown
            size={11}
            strokeWidth={1.8}
            className="shrink-0 text-[var(--app-text-tertiary)] opacity-40 transition-opacity group-hover/col-hdr:opacity-80"
          />
        )}
      </button>
    </div>
  );
}

function DualSortHeader({
  title,
  pctKey,
  amountKey,
  activeKey,
  direction,
  onSort,
  pctLabel = '%',
  amountLabel = '¥',
  pctTooltip,
  amountTooltip,
  pctTestId,
  amountTestId,
}: {
  title: string;
  pctKey: string;
  amountKey: string;
  activeKey?: string;
  direction?: 'asc' | 'desc';
  onSort?: (key: string, direction?: 'asc' | 'desc') => void;
  pctLabel?: string;
  amountLabel?: string;
  pctTooltip?: string;
  amountTooltip?: string;
  pctTestId?: string;
  amountTestId?: string;
}) {
  if (!onSort) {
    return <span className="block text-right">{title}</span>;
  }
  const isPctActive = activeKey === pctKey;
  const isAmountActive = activeKey === amountKey;

  return (
    <div className="flex items-center justify-end gap-1.5">
      <button
        type="button"
        onClick={() => {
          const targetKey = isAmountActive ? amountKey : pctKey;
          const isCurrentActive = isPctActive || isAmountActive;
          const nextDir =
            isCurrentActive && direction === 'desc' ? 'asc' : 'desc';
          onSort(targetKey, nextDir);
        }}
        className={`group/col-hdr inline-flex items-center gap-1 rounded px-1 py-0.5 text-xs font-semibold transition-all hover:bg-[var(--app-surface-overlay)] active:scale-[0.98] ${
          isPctActive || isAmountActive
            ? 'text-[var(--app-accent)] font-semibold'
            : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
        }`}
        title={title}
      >
        <span>{title}</span>
        {!(isPctActive || isAmountActive) ? (
          <ArrowUpDown
            size={11}
            strokeWidth={1.8}
            className="shrink-0 text-[var(--app-text-tertiary)] opacity-40 transition-opacity group-hover/col-hdr:opacity-80"
          />
        ) : null}
      </button>
      <div
        role="group"
        aria-label={title}
        className="inline-flex items-center rounded border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] p-0.5"
      >
        <button
          type="button"
          onClick={() => {
            const nextDir =
              isPctActive && direction === 'desc' ? 'asc' : 'desc';
            onSort(pctKey, nextDir);
          }}
          className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-medium transition-all ${
            isPctActive
              ? 'bg-[color-mix(in_srgb,var(--app-accent)_18%,transparent)] text-[var(--app-accent)] font-semibold'
              : 'text-[var(--app-text-tertiary)] hover:text-[var(--app-text)] hover:bg-[var(--app-surface)]'
          }`}
          title={pctTooltip}
          data-testid={pctTestId}
        >
          <span>{pctLabel}</span>
          {isPctActive ? (
            direction === 'asc' ? (
              <ArrowUp size={10} strokeWidth={2.2} />
            ) : (
              <ArrowDown size={10} strokeWidth={2.2} />
            )
          ) : null}
        </button>
        <button
          type="button"
          onClick={() => {
            const nextDir =
              isAmountActive && direction === 'desc' ? 'asc' : 'desc';
            onSort(amountKey, nextDir);
          }}
          className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-medium transition-all ${
            isAmountActive
              ? 'bg-[color-mix(in_srgb,var(--app-accent)_18%,transparent)] text-[var(--app-accent)] font-semibold'
              : 'text-[var(--app-text-tertiary)] hover:text-[var(--app-text)] hover:bg-[var(--app-surface)]'
          }`}
          title={amountTooltip}
          data-testid={amountTestId}
        >
          <span>{amountLabel}</span>
          {isAmountActive ? (
            direction === 'asc' ? (
              <ArrowUp size={10} strokeWidth={2.2} />
            ) : (
              <ArrowDown size={10} strokeWidth={2.2} />
            )
          ) : null}
        </button>
      </div>
    </div>
  );
}

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
      className={`block text-right font-medium font-mono tabular-nums ${tone} ${className}`.trim()}
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

type ColumnContext = {
  copy: PortfolioCopy;
  locale: Locale;
  model: PositionsTableModel;
};

function buildSymbolColumn({
  copy,
  locale,
  model,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'symbol',
    header: () => (
      <TableSortHeader
        label={
          model.variant === 'dashboard'
            ? locale === 'zh'
              ? '标的'
              : 'Holding'
            : labels.symbol
        }
        columnKey="symbol"
        activeKey={model.sortKey}
        direction={model.sortDirection}
        onSort={model.onSort}
        align="left"
        locale={locale}
      />
    ),
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
}

function buildMarketValueColumn({
  copy,
  locale,
  model,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'market-value',
    header: () => (
      <TableSortHeader
        label={labels.marketValue}
        columnKey="market_value"
        activeKey={model.sortKey}
        direction={model.sortDirection}
        onSort={model.onSort}
        locale={locale}
      />
    ),
    cell: ({ row }) => {
      const position = row.original;
      const subtext = resolvePositionMarketValueSubtext(position, locale);
      const isIndicative =
        position.market_value == null &&
        (position.indicative_market_value != null ||
          (position.latest_price != null &&
            position.latest_price > 0 &&
            position.quantity > 0));
      const displayValue =
        position.market_value ??
        position.indicative_market_value ??
        (position.latest_price != null && position.quantity > 0
          ? position.quantity * position.latest_price
          : null);

      return (
        <span data-testid={`position-market-value-${position.symbol}`}>
          <PositionNumericCell value={formatCurrency(displayValue)} />
          {isIndicative ? (
            <span
              className="app-type-micro mt-0.5 block text-right font-medium font-mono tabular-nums text-[var(--app-warning-text)]"
              title={`${locale === 'zh' ? '持仓数量' : 'Quantity'}: ${formatQuantity(position.quantity)}`}
            >
              {locale === 'zh' ? '参考估值' : 'Ref Value'}
              {subtext ? ` · ${subtext}` : ''}
            </span>
          ) : subtext ? (
            <span
              className="app-type-micro mt-0.5 block text-right font-medium font-mono tabular-nums text-[var(--app-text-tertiary)]"
              title={`${locale === 'zh' ? '持仓数量' : 'Quantity'}: ${formatQuantity(position.quantity)}`}
            >
              {subtext}
            </span>
          ) : null}
        </span>
      );
    },
  };
}

function buildTodayColumn({
  copy,
  locale,
  model,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'today-change',
    header: () => (
      <DualSortHeader
        title={labels.todayChange}
        pctKey="today_change_pct"
        amountKey="today_change"
        activeKey={model.sortKey}
        direction={model.sortDirection}
        onSort={model.onSort}
        pctLabel="%"
        amountLabel="¥"
        pctTooltip={
          locale === 'zh' ? '按当日涨跌幅排序 (%)' : 'Sort by day’s change %'
        }
        amountTooltip={
          locale === 'zh' ? '按当日盈亏排序 (¥)' : 'Sort by day’s P&L (¥)'
        }
        pctTestId="positions-sort-today-pct"
        amountTestId="positions-sort-today-change"
      />
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
              className={`app-type-micro mt-0.5 block text-right font-medium font-mono tabular-nums ${pctTone}`}
            >
              {formatSignedPercent(changePct)}
            </span>
          ) : null}
        </span>
      );
    },
  };
}

function buildUnrealizedColumn({
  copy,
  locale,
  model,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'unrealized',
    header: () => (
      <DualSortHeader
        title={labels.unrealized}
        pctKey="unrealized_pnl_pct"
        amountKey="unrealized_pnl"
        activeKey={model.sortKey}
        direction={model.sortDirection}
        onSort={model.onSort}
        pctLabel="%"
        amountLabel="¥"
        pctTooltip={
          locale === 'zh' ? '按浮动盈亏率排序 (%)' : 'Sort by floating P&L %'
        }
        amountTooltip={
          locale === 'zh' ? '按浮动盈亏排序 (¥)' : 'Sort by floating P&L (¥)'
        }
        pctTestId="positions-sort-unrealized-pct"
        amountTestId="positions-sort-unrealized-amount"
      />
    ),
    cell: ({ row }) => {
      const position = row.original;
      const isIndicative =
        position.unrealized_pnl == null &&
        (position.indicative_unrealized_pnl != null ||
          (position.latest_price != null &&
            position.latest_price > 0 &&
            position.quantity > 0 &&
            position.avg_cost > 0));
      const fallbackIndicativePnl =
        position.latest_price != null &&
        position.quantity > 0 &&
        position.avg_cost > 0
          ? position.quantity * (position.latest_price - position.avg_cost)
          : null;
      const pnlValue =
        position.unrealized_pnl ??
        position.indicative_unrealized_pnl ??
        fallbackIndicativePnl;
      const changePct =
        resolvePositionUnrealizedPct(position) ??
        (isIndicative && position.avg_cost > 0 && position.latest_price != null
          ? (position.latest_price - position.avg_cost) / position.avg_cost
          : null);
      const tone = resolvePositionTone(pnlValue);
      const pctTone = resolvePositionTone(changePct ?? pnlValue);

      return (
        <span data-testid={`position-unrealized-${position.symbol}`}>
          <PositionNumericCell value={formatCurrency(pnlValue)} tone={tone} />
          {changePct != null ? (
            <span
              className={`app-type-micro mt-0.5 block text-right font-medium font-mono tabular-nums ${pctTone}`}
            >
              {formatSignedPercent(changePct)}
              {isIndicative ? (
                <span className="ml-1 text-[var(--app-text-tertiary)] font-normal">
                  ({locale === 'zh' ? '参考' : 'Ref'})
                </span>
              ) : null}
            </span>
          ) : isIndicative ? (
            <span className="app-type-micro mt-0.5 block text-right text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '参考' : 'Ref'}
            </span>
          ) : null}
        </span>
      );
    },
  };
}

function buildRealizedColumn({
  copy,
  locale,
  model,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'realized',
    header: () => (
      <TableSortHeader
        label={labels.realized}
        columnKey="realized_pnl"
        activeKey={model.sortKey}
        direction={model.sortDirection}
        onSort={model.onSort}
        locale={locale}
      />
    ),
    cell: ({ row }) => (
      <span data-testid={`position-realized-${row.original.symbol}`}>
        <PositionNumericCell
          value={formatCurrency(row.original.realized_pnl)}
          tone={resolvePositionTone(row.original.realized_pnl)}
        />
      </span>
    ),
  };
}

function buildClosedAtColumn({
  copy,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
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
}

function buildQuoteColumn({
  copy,
  locale,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'quote-state',
    header: labels.quoteState,
    cell: ({ row }) => (
      <PositionPricing position={row.original} locale={locale} />
    ),
  };
}

function buildWeightColumn({
  copy,
  locale,
  model,
}: ColumnContext): ColumnDef<Position, unknown> {
  const labels = copy.portfolio.table;
  return {
    id: 'weight',
    header: () => (
      <TableSortHeader
        label={labels.weight}
        columnKey="weight"
        activeKey={model.sortKey}
        direction={model.sortDirection}
        onSort={model.onSort}
        locale={locale}
      />
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
          {weight != null ? (
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
  };
}

function buildCommissionColumn({
  copy,
}: ColumnContext): ColumnDef<Position, unknown> {
  const detailLabels = copy.portfolio.detail;
  return {
    id: 'commission-paid',
    header: () => (
      <span className="block text-right">{detailLabels.commissionPaid}</span>
    ),
    cell: ({ row }) => (
      <span data-testid={`position-commission-${row.original.symbol}`}>
        <PositionNumericCell
          value={formatCurrency(row.original.commission_paid)}
          tone="text-[var(--app-text-secondary)]"
        />
      </span>
    ),
  };
}

export function buildPositionColumns(
  ctx: ColumnContext,
): ColumnDef<Position, unknown>[] {
  const { model } = ctx;
  const symbolColumn = buildSymbolColumn(ctx);
  const realizedColumn = buildRealizedColumn(ctx);

  if (model.showHistoryColumns) {
    return [
      symbolColumn,
      buildClosedAtColumn(ctx),
      realizedColumn,
      buildCommissionColumn(ctx),
    ];
  }

  return [
    symbolColumn,
    buildMarketValueColumn(ctx),
    ...(model.showFullColumns || model.variant === 'dashboard'
      ? [buildWeightColumn(ctx)]
      : []),
    buildTodayColumn(ctx),
    buildUnrealizedColumn(ctx),
    ...(model.showFullColumns ? [realizedColumn] : []),
    ...(model.variant === 'dashboard' ? [] : [buildQuoteColumn(ctx)]),
  ];
}
