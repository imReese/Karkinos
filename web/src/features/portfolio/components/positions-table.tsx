import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
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
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import { formatLedgerCostBasisMethodLabel } from '../../../shared/ledger-format';

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

function resolveTone(value: number | null | undefined): NumericCellTone {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return 'text';
  }
  return value > 0 ? 'success' : 'danger';
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function resolveBrokerDisplayedUnitCost(position: Position) {
  if (
    !isFiniteNumber(position.broker_displayed_cost_basis) ||
    position.broker_displayed_cost_basis <= 0 ||
    position.quantity <= 0
  ) {
    return null;
  }
  return position.broker_displayed_cost_basis / position.quantity;
}

function formatCostBasisMethod(
  locale: ReturnType<typeof usePreferences>['locale'],
  method: string | null | undefined,
) {
  return formatLedgerCostBasisMethodLabel(method, locale);
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

function brokerUnitCostLabel(
  labels: ReturnType<typeof useCopy>['portfolio']['detail'],
  status: string | null | undefined,
) {
  return isProjectedLedgerCostBasis(status)
    ? labels.ledgerProjectedUnitCost
    : labels.brokerDisplayedCost;
}

function formatBrokerCostBasisDetail(
  labels: ReturnType<typeof useCopy>['portfolio']['detail'],
  locale: ReturnType<typeof usePreferences>['locale'],
  position: Position,
) {
  const projectedFromLedger = isProjectedLedgerCostBasis(
    position.broker_cost_basis_status,
  );
  const detailParts = [
    projectedFromLedger
      ? labels.ledgerProjectedCostBasis
      : formatCostBasisMethod(locale, position.broker_cost_basis_method),
    formatCostBasisStatus(labels, position.broker_cost_basis_status),
  ];

  if (
    isFiniteNumber(position.broker_cost_basis_difference) &&
    Math.abs(position.broker_cost_basis_difference) >= 0.005
  ) {
    detailParts.push(
      `${labels.costBasisDifference} ${formatCurrency(
        position.broker_cost_basis_difference,
      )}`,
    );
  }

  return detailParts.join(' · ');
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

type NumericCellKind = 'quantity' | 'price' | 'amount' | 'percent';
type NumericCellTone = 'muted' | 'text' | 'success' | 'danger';

const NUMERIC_WIDTH_CLASSES: Record<NumericCellKind, string> = {
  quantity: 'min-w-24 px-4',
  price: 'min-w-28 px-5',
  amount: 'min-w-32 px-4',
  percent: 'min-w-24 px-4',
};

const NUMERIC_TONE_CLASSES: Record<NumericCellTone, string> = {
  muted: 'text-[var(--app-soft)]',
  text: 'text-[var(--app-text)]',
  success: 'text-[var(--app-success)]',
  danger: 'text-[var(--app-danger)]',
};

function numericHeaderClassName(kind: NumericCellKind) {
  return `whitespace-nowrap ${NUMERIC_WIDTH_CLASSES[kind]} py-3 text-right`;
}

function numericDisplayClassName({
  kind,
  tone = 'text',
  emphasis = false,
  surface = 'metric',
}: {
  kind: NumericCellKind;
  tone?: NumericCellTone;
  emphasis?: boolean;
  surface?: 'cell' | 'metric' | 'summary';
}) {
  const surfaceClass =
    surface === 'cell'
      ? `${NUMERIC_WIDTH_CLASSES[kind]} py-3.5 text-right`
      : surface === 'summary'
        ? 'text-sm'
        : 'mt-2 text-sm';

  return `karkinos-numeric-display whitespace-nowrap ${surfaceClass} font-mono tabular-nums ${
    emphasis ? 'font-semibold' : ''
  } ${NUMERIC_TONE_CLASSES[tone]}`;
}

function numericCellClassName({
  kind,
  tone = 'text',
  emphasis = false,
}: {
  kind: NumericCellKind;
  tone?: NumericCellTone;
  emphasis?: boolean;
}) {
  return `karkinos-numeric-cell ${numericDisplayClassName({
    kind,
    tone,
    emphasis,
    surface: 'cell',
  })}`;
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
  const { locale } = usePreferences();
  const labels = copy.portfolio.table;
  const detailLabels = copy.portfolio.detail;
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const showFullColumns = variant === 'full';
  const showDashboardColumns = variant === 'dashboard';
  const hasStaleQuotes = positions.some(
    (position) => position.quote_status === 'stale',
  );

  const resolveLatestPrice = (position: Position) => {
    if (
      typeof position.latest_price === 'number' &&
      Number.isFinite(position.latest_price)
    ) {
      return position.latest_price;
    }
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
          const latestPrice = resolveLatestPrice(position);
          const brokerDisplayedUnitCost =
            resolveBrokerDisplayedUnitCost(position);
          const brokerCostBasisDetail =
            brokerDisplayedUnitCost === null
              ? null
              : formatBrokerCostBasisDetail(detailLabels, locale, position);
          const mobileMetrics: Array<{
            key: string;
            label: string;
            value: string;
            detail?: string;
            kind: NumericCellKind;
            tone?: NumericCellTone;
            emphasis?: boolean;
          }> = [
            {
              key: 'quantity',
              label: labels.quantity,
              value: formatQuantity(position.quantity),
              kind: 'quantity',
              tone: 'muted',
            },
            {
              key: 'avg-cost',
              label: detailLabels.avgCost,
              value: formatPrice(position.avg_cost),
              kind: 'price',
              tone: 'muted',
            },
            ...(brokerDisplayedUnitCost === null
              ? []
              : [
                  {
                    key: 'broker-cost',
                    label: brokerUnitCostLabel(
                      detailLabels,
                      position.broker_cost_basis_status,
                    ),
                    value: formatPrice(brokerDisplayedUnitCost),
                    detail: brokerCostBasisDetail ?? undefined,
                    kind: 'price' as const,
                    tone: 'muted' as const,
                  },
                ]),
            {
              key: 'latest-price',
              label: labels.latestPrice,
              value: formatPrice(latestPrice),
              kind: 'price',
              tone: 'text',
            },
            {
              key: 'market-value',
              label: labels.marketValue,
              value: formatCurrency(position.market_value),
              kind: 'amount',
              tone: 'text',
              emphasis: true,
            },
            {
              key: 'today-change',
              label: labels.todayChange,
              value: formatCurrency(position.today_change),
              kind: 'amount',
              tone: resolveTone(position.today_change),
              emphasis: true,
            },
            {
              key: 'unrealized',
              label: labels.unrealized,
              value: formatCurrency(position.unrealized_pnl),
              kind: 'amount',
              tone: pnlPositive ? 'success' : 'danger',
              emphasis: true,
            },
            {
              key: 'return-pct',
              label: labels.returnPct,
              value: formatReturnPercent(resolvePnlPct(position)),
              kind: 'percent',
              tone: pnlPositive ? 'success' : 'danger',
              emphasis: true,
            },
            {
              key: 'quote-age',
              label: labels.quoteAge,
              value: formatAge(position.quote_age_seconds),
              kind: 'quantity',
              tone: 'muted',
            },
            ...(showFullColumns
              ? [
                  {
                    key: 'available-frozen',
                    label: labels.availFrozen,
                    value: `${formatQuantity(position.available_qty)} / ${formatQuantity(position.frozen_qty)}`,
                    kind: 'quantity' as const,
                    tone: 'text' as const,
                  },
                  {
                    key: 'realized',
                    label: labels.realized,
                    value: formatCurrency(position.realized_pnl),
                    kind: 'amount' as const,
                    tone: 'text' as const,
                  },
                ]
              : []),
          ];
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
                  <div
                    data-testid={`position-mobile-summary-market-value-${position.symbol}`}
                    className={numericDisplayClassName({
                      kind: 'amount',
                      tone: 'text',
                      emphasis: true,
                      surface: 'summary',
                    })}
                  >
                    {formatCurrency(position.market_value)}
                  </div>
                  <div className="app-muted mt-1 text-xs">
                    {labels.marketValue}
                  </div>
                </div>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {mobileMetrics.map((metric) => (
                  <div
                    key={metric.key}
                    className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3"
                  >
                    <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                      {metric.label}
                    </div>
                    <div
                      data-testid={`position-mobile-${metric.key}-${position.symbol}`}
                      className={numericDisplayClassName({
                        kind: metric.kind,
                        tone: metric.tone,
                        emphasis: metric.emphasis,
                      })}
                    >
                      {metric.value}
                    </div>
                    {metric.detail ? (
                      <div className="app-muted mt-1 truncate text-[10px]">
                        {metric.detail}
                      </div>
                    ) : null}
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
        className="hidden min-w-0 max-w-full overflow-x-scroll overscroll-x-contain rounded-[26px] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_18%,transparent)] pb-2 [scrollbar-gutter:stable] md:block"
      >
        <table
          data-testid="positions-table-desktop"
          className="app-data-table w-[1520px] min-w-max text-left text-sm"
        >
          <thead className="app-kicker text-xs uppercase tracking-[0.16em]">
            <tr>
              <th className="w-60 px-4 py-3">{labels.symbol}</th>
              <th className="w-24 whitespace-nowrap px-4 py-3">
                {labels.assetClass}
              </th>
              <th className={numericHeaderClassName('quantity')}>
                {labels.quantity}
              </th>
              <th className={numericHeaderClassName('price')}>
                {detailLabels.avgCost}
              </th>
              <th className={numericHeaderClassName('price')}>
                {detailLabels.brokerDisplayedCost}
              </th>
              <th className={numericHeaderClassName('price')}>
                {labels.latestPrice}
              </th>
              <th className={numericHeaderClassName('amount')}>
                {labels.marketValue}
              </th>
              <th className={numericHeaderClassName('amount')}>
                {labels.todayChange}
              </th>
              <th className={numericHeaderClassName('amount')}>
                {labels.unrealized}
              </th>
              <th className={numericHeaderClassName('percent')}>
                {labels.returnPct}
              </th>
              <th className="px-4 py-3">{labels.quoteState}</th>
              {showFullColumns ? (
                <>
                  <th className={numericHeaderClassName('quantity')}>
                    {labels.availFrozen}
                  </th>
                  <th className={numericHeaderClassName('amount')}>
                    {labels.realized}
                  </th>
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
              const quoteStatusLabel = position.quote_status
                ? formatPublicStatus(position.quote_status, locale)
                : '--';
              const brokerDisplayedUnitCost =
                resolveBrokerDisplayedUnitCost(position);
              const brokerCostBasisDetail =
                brokerDisplayedUnitCost === null
                  ? null
                  : formatBrokerCostBasisDetail(detailLabels, locale, position);
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
                  <td className="whitespace-nowrap px-4 py-3.5 text-[var(--app-muted)]">
                    <span
                      data-testid={`position-asset-class-${position.symbol}`}
                      className="inline-flex whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-2.5 py-1 text-xs"
                    >
                      {assetClassDisplay}
                    </span>
                  </td>
                  <td
                    data-testid={`position-quantity-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'quantity',
                      tone: 'muted',
                    })}
                  >
                    {formatQuantity(position.quantity)}
                  </td>
                  <td
                    data-testid={`position-avg-cost-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'price',
                      tone: 'muted',
                    })}
                  >
                    {formatPrice(position.avg_cost)}
                  </td>
                  <td
                    data-testid={`position-broker-cost-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'price',
                      tone: brokerDisplayedUnitCost === null ? 'muted' : 'text',
                    })}
                    title={brokerCostBasisDetail ?? undefined}
                  >
                    <span>{formatPrice(brokerDisplayedUnitCost)}</span>
                    {brokerCostBasisDetail ? (
                      <span className="app-muted mt-1 block max-w-44 whitespace-normal text-[10px] font-sans leading-4">
                        {brokerCostBasisDetail}
                      </span>
                    ) : null}
                  </td>
                  <td
                    data-testid={`position-latest-price-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'price',
                      tone: 'text',
                    })}
                  >
                    {formatPrice(resolveLatestPrice(position))}
                  </td>
                  <td
                    data-testid={`position-market-value-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'amount',
                      tone: 'text',
                      emphasis: true,
                    })}
                  >
                    {formatCurrency(position.market_value)}
                  </td>
                  <td
                    data-testid={`position-today-change-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'amount',
                      tone: resolveTone(position.today_change),
                      emphasis: true,
                    })}
                  >
                    {formatCurrency(position.today_change)}
                  </td>
                  <td
                    data-testid={`position-unrealized-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'amount',
                      tone: pnlPositive ? 'success' : 'danger',
                      emphasis: true,
                    })}
                  >
                    {formatCurrency(position.unrealized_pnl)}
                  </td>
                  <td
                    data-testid={`position-return-pct-${position.symbol}`}
                    className={numericCellClassName({
                      kind: 'percent',
                      tone: pnlPositive ? 'success' : 'danger',
                      emphasis: true,
                    })}
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
                          : quoteStatusLabel}
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
                      <td
                        data-testid={`position-available-frozen-${position.symbol}`}
                        className={numericCellClassName({
                          kind: 'quantity',
                          tone: 'text',
                        })}
                      >
                        {formatQuantity(position.available_qty)} /{' '}
                        {formatQuantity(position.frozen_qty)}
                      </td>
                      <td
                        data-testid={`position-realized-${position.symbol}`}
                        className={numericCellClassName({
                          kind: 'amount',
                          tone: 'text',
                        })}
                      >
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
