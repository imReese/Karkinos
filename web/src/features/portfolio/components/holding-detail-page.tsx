import { useMemo } from 'react';

import { useAccountOverviewQuery } from '../../account/api';
import { useLedgerEntriesQuery, type LedgerEntry } from '../../activity/api';
import {
  calculateLedgerEntryAmount,
  formatLedgerExecutionDetailLines,
  formatLedgerEntryTypeLabel,
  formatLedgerPublicNote,
} from '../../../shared/ledger-format';
import {
  useMarketDataHealthQuery,
  useKlineQuery,
  useRefreshMarketQuotesMutation,
} from '../../market/api';
import { PriceStructureChart } from '../../market/components/price-structure-chart';
import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatReturnPercent,
  formatTimestamp,
} from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import {
  useLiveHoldingsQuery,
  usePortfolioSnapshotQuery,
  usePositionsQuery,
  type Position,
} from '../api';

type DetailMetric = {
  label: string;
  value: string;
  tone?: 'success' | 'danger' | 'warning';
};

function normalizeSymbol(symbol: string) {
  return symbol.trim().toLowerCase();
}

function safeDecodeSymbol(symbol: string) {
  try {
    return decodeURIComponent(symbol);
  } catch {
    return symbol;
  }
}

function resolveQuotePrice(position: Position, livePrice: number | null) {
  if (
    typeof position.latest_price === 'number' &&
    Number.isFinite(position.latest_price)
  ) {
    return position.latest_price;
  }
  if (typeof livePrice === 'number' && Number.isFinite(livePrice)) {
    return livePrice;
  }
  if (position.quantity > 0) {
    return position.market_value / position.quantity;
  }
  return null;
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

export function HoldingDetailPage({ symbol }: { symbol: string }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.portfolio.detail;
  const decodedSymbol = safeDecodeSymbol(symbol);
  const normalizedSymbol = normalizeSymbol(decodedSymbol);
  const positions = usePositionsQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const liveHoldings = useLiveHoldingsQuery();
  const overview = useAccountOverviewQuery();
  const marketHealth = useMarketDataHealthQuery();
  const kline = useKlineQuery(decodedSymbol);
  const ledger = useLedgerEntriesQuery(200);
  const refreshQuote = useRefreshMarketQuotesMutation();

  const allPositions = positions.data ?? snapshot.data?.positions ?? [];
  const position = allPositions.find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const allocation = (snapshot.data?.allocation ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const liveItem = (liveHoldings.data?.groups ?? [])
    .flatMap((group) => group.items)
    .find((item) => normalizeSymbol(item.symbol) === normalizedSymbol);
  const healthQuote = (marketHealth.data?.quotes ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );

  const ledgerEntries = useMemo(
    () =>
      (ledger.data ?? [])
        .filter(
          (entry) => normalizeSymbol(entry.symbol ?? '') === normalizedSymbol,
        )
        .slice(0, 12),
    [ledger.data, normalizedSymbol],
  );

  const coreLoading =
    !position &&
    (positions.isLoading ||
      snapshot.isLoading ||
      liveHoldings.isLoading ||
      overview.isLoading);
  const coreError = positions.isError && snapshot.isError;

  if (coreLoading) {
    return (
      <StatusPanel
        title={copy.states.loading}
        detail={labels.loading}
        tone="neutral"
      />
    );
  }

  if (coreError) {
    return (
      <StatusPanel
        title={copy.states.error}
        detail={labels.error}
        tone="danger"
      />
    );
  }

  if (!position) {
    return (
      <section className="space-y-5 sm:space-y-6">
        <a
          href="/portfolio"
          className="app-button-secondary inline-flex rounded-2xl px-4 py-2 text-sm font-semibold"
        >
          {labels.backToPortfolio}
        </a>
        <StatusPanel
          title={labels.notFoundTitle}
          detail={labels.notFoundDetail}
          tone="neutral"
        />
      </section>
    );
  }

  const quoteStatus =
    position.quote_status ??
    liveItem?.quote_status ??
    overview.data?.quote_status;
  const quoteTimestamp =
    position.quote_timestamp ??
    liveItem?.quote_timestamp ??
    healthQuote?.timestamp;
  const quoteSource =
    position.quote_source ??
    liveItem?.quote_source ??
    healthQuote?.quote_source ??
    null;
  const quoteSourceLabel = quoteSource ?? '--';
  const quoteAgeSeconds =
    position.quote_age_seconds ??
    liveItem?.quote_age_seconds ??
    healthQuote?.quote_age_seconds ??
    null;
  const staleReason =
    position.stale_reason ??
    liveItem?.stale_reason ??
    healthQuote?.stale_reason;
  const staleReasonLabel = formatStaleReason(
    staleReason,
    copy.common.staleReasons,
  );
  const isStale = quoteStatus === 'stale';
  const quoteStatusLabel = quoteStatus
    ? formatPublicStatus(quoteStatus, locale)
    : '--';
  const quotePrice = resolveQuotePrice(
    position,
    liveItem?.latest_price ?? null,
  );
  const todayChange = position.today_change ?? liveItem?.today_change ?? null;
  const todayChangePct =
    position.today_change_pct ?? liveItem?.today_change_pct ?? null;
  const baselinePrice = position.baseline_price ?? liveItem?.baseline_price;
  const baselineSource =
    position.baseline_source ?? liveItem?.baseline_source ?? 'unavailable';
  const baselineSourceLabel =
    {
      daily_close: labels.baselineSources.dailyClose,
      market_bar_close: labels.baselineSources.marketBarClose,
      previous_close: labels.baselineSources.previousClose,
      previous_quote: labels.baselineSources.previousQuote,
      intraday_trade_cost: labels.baselineSources.intradayTradeCost,
      fallback_close: labels.baselineSources.fallbackClose,
      unavailable: labels.baselineSources.unavailable,
    }[baselineSource] ?? baselineSource;
  const costBasis = position.avg_cost * position.quantity;
  const pnlPct = costBasis > 0 ? position.unrealized_pnl / costBasis : null;
  const displayName =
    liveItem?.name ??
    allocation?.name ??
    position.display_name ??
    position.name ??
    position.symbol;
  const assetClass =
    liveItem?.asset_class ??
    allocation?.asset_class ??
    position.asset_class ??
    '--';
  const assetClassDisplay = formatAssetClassLabel(assetClass, copy.common);
  const portfolioWeight = allocation?.weight ?? null;
  const marketOpen = marketHealth.data?.market_open;
  const refreshPolicy = marketHealth.data?.refresh_policy ?? '--';
  const refreshPolicyLabel = marketHealth.data?.refresh_policy
    ? formatPublicStatus(marketHealth.data.refresh_policy, locale)
    : '--';
  const refreshStatus = refreshQuote.isPending
    ? labels.refreshingQuote
    : refreshQuote.isError
      ? labels.refreshFailed
      : refreshQuote.isSuccess
        ? labels.refreshDone
        : null;

  const summaryMetrics: DetailMetric[] = [
    { label: labels.quantity, value: formatQuantity(position.quantity) },
    {
      label: labels.marketValue,
      value: formatCurrency(position.market_value),
    },
    {
      label: labels.todayChange,
      value: formatCurrency(todayChange),
      tone:
        typeof todayChange === 'number' && todayChange !== 0
          ? todayChange > 0
            ? 'success'
            : 'danger'
          : undefined,
    },
    {
      label: labels.todayChangePct,
      value: formatReturnPercent(todayChangePct),
      tone:
        typeof todayChange === 'number' && todayChange !== 0
          ? todayChange > 0
            ? 'success'
            : 'danger'
          : undefined,
    },
    {
      label: labels.unrealizedPnl,
      value: formatCurrency(position.unrealized_pnl),
      tone: position.unrealized_pnl >= 0 ? 'success' : 'danger',
    },
    { label: labels.pnlPct, value: formatReturnPercent(pnlPct) },
  ];

  const valuationMetrics: DetailMetric[] = [
    { label: labels.costBasis, value: formatCurrency(costBasis) },
    { label: labels.avgCost, value: formatPrice(position.avg_cost) },
    { label: labels.quotePrice, value: formatPrice(quotePrice) },
    { label: labels.baselinePrice, value: formatPrice(baselinePrice) },
    { label: labels.baselineSource, value: baselineSourceLabel },
    { label: labels.realizedPnl, value: formatCurrency(position.realized_pnl) },
    {
      label: labels.commissionPaid,
      value: formatCurrency(position.commission_paid),
    },
    {
      label: labels.availableFrozen,
      value: `${formatQuantity(position.available_qty)} / ${formatQuantity(
        position.frozen_qty,
      )}`,
    },
  ];

  return (
    <section className="space-y-5 sm:space-y-6">
      <header
        data-testid="holding-detail-header"
        className="app-page-header pb-0"
      >
        <div className="flex flex-col gap-3 rounded-[28px] border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_14%,transparent)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
            <a
              href="/portfolio"
              className="app-button-secondary inline-flex w-max rounded-2xl px-4 py-2 text-sm font-semibold"
              aria-label={labels.returnToPortfolio}
            >
              {labels.backToPortfolio}
            </a>
            <span className="hidden h-8 w-px bg-[color-mix(in_srgb,var(--app-border)_36%,transparent)] sm:block" />
            <div className="min-w-0">
              <div className="app-product-mark">{labels.kicker}</div>
              <div className="app-muted mt-1 truncate text-sm">
                {displayName} · {position.symbol} · {assetClassDisplay}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <StatusBadge
              label={isStale ? labels.quoteStale : labels.quoteLive}
              tone={isStale ? 'warning' : 'success'}
            />
            {marketOpen === false ? (
              <StatusBadge label={labels.marketClosed} tone="warning" />
            ) : null}
            {refreshPolicy === 'cache_only' ? (
              <StatusBadge label={labels.cacheOnly} tone="warning" />
            ) : null}
            <div className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-muted)]">
              <span className="app-kicker mr-1 text-[10px] uppercase tracking-[0.14em]">
                {labels.quoteTimestamp}
              </span>
              <span className="font-mono tabular-nums">
                {formatTimestamp(quoteTimestamp)}
              </span>
            </div>
          </div>
        </div>
      </header>

      {isStale ? (
        <div className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
          <span className="truncate">{labels.cacheNotice}</span>
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.8fr)]">
        <div className="min-w-0 space-y-5">
          <section className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]">
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div
                data-testid="holding-summary-header"
                className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="app-product-mark">{labels.summary}</div>
                  <h2
                    data-testid="holding-summary-title"
                    className="app-card-title mt-1.5 break-words"
                  >
                    {displayName}
                  </h2>
                  <p className="app-muted mt-2 text-sm">{assetClassDisplay}</p>
                </div>
                <div
                  data-testid="holding-summary-symbol"
                  className="shrink-0 font-mono text-sm font-semibold tabular-nums"
                >
                  {position.symbol}
                </div>
              </div>
              <MetricGrid
                metrics={summaryMetrics}
                testId="holding-summary-metrics"
                metricTestId="holding-summary-metric"
              />
            </div>
          </section>

          <section
            data-testid="holding-kline-panel"
            className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <PriceStructureChart
                bars={kline.data ?? []}
                emptyLabel={copy.market.noChart}
                titleLabel={copy.market.priceRangeKline}
                priceLabel={copy.market.priceLabel}
                rangeLabels={copy.market.klineRanges}
                axisLabels={copy.market.klineAxes}
                rangeAriaLabel={copy.market.showKlineRange}
              />
            </div>
          </section>

          <section className="app-terminal-panel rounded-[28px] p-[1px]">
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.valuation}</div>
              <MetricGrid metrics={valuationMetrics} />
            </div>
          </section>

          <section className="app-terminal-panel rounded-[28px] p-[1px]">
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <div className="app-product-mark">{labels.ledgerTrace}</div>
                  <h2 className="app-card-title mt-1.5">
                    {labels.ledgerCount(ledgerEntries.length)}
                  </h2>
                </div>
                {ledger.isError ? (
                  <div className="app-error-text text-sm">
                    {copy.activity.error}
                  </div>
                ) : null}
              </div>
              <LedgerTrace entries={ledgerEntries} loading={ledger.isLoading} />
            </div>
          </section>
        </div>

        <aside className="min-w-0 space-y-5">
          <section
            data-testid="holding-quote-status-panel"
            className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.quoteStatus}</div>
              <div className="mt-4 grid gap-3">
                <InfoRow
                  label={labels.quoteStatus}
                  value={quoteStatusLabel}
                  tone={isStale ? 'warning' : undefined}
                />
                <InfoRow
                  label={labels.quoteTimestamp}
                  value={formatTimestamp(quoteTimestamp)}
                />
                <InfoRow label={labels.quoteSource} value={quoteSourceLabel} />
                <InfoRow
                  label={labels.quoteAge}
                  value={formatAge(quoteAgeSeconds)}
                />
                <InfoRow
                  label={labels.staleReason}
                  value={staleReasonLabel}
                  tone={staleReason ? 'warning' : undefined}
                />
                <InfoRow
                  label={labels.valuationTimestamp}
                  value={formatTimestamp(overview.data?.valuation_timestamp)}
                />
                <InfoRow
                  label={labels.refreshPolicy}
                  value={refreshPolicyLabel}
                />
                <InfoRow
                  label={labels.marketOpen}
                  value={
                    marketOpen === undefined
                      ? '--'
                      : marketOpen
                        ? labels.marketOpen
                        : labels.marketClosed
                  }
                />
              </div>
              <button
                type="button"
                className="app-button-primary mt-4 w-full rounded-2xl px-4 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55"
                disabled={refreshQuote.isPending}
                onClick={() =>
                  refreshQuote.mutate({
                    symbols: [position.symbol],
                    force: true,
                  })
                }
                aria-label={`${labels.refreshQuote}: ${position.symbol}`}
              >
                {refreshQuote.isPending
                  ? labels.refreshingQuote
                  : labels.refreshQuote}
              </button>
              {refreshStatus ? (
                <div
                  className={`mt-3 text-sm ${
                    refreshQuote.isError
                      ? 'app-error-text'
                      : 'text-[var(--app-muted)]'
                  }`}
                  role="status"
                  aria-live="polite"
                >
                  {refreshStatus}
                </div>
              ) : null}
            </div>
          </section>

          <section
            data-testid="holding-risk-exposure-panel"
            className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.riskExposure}</div>
              <div className="mt-4 grid gap-3">
                <InfoRow
                  label={labels.portfolioWeight}
                  value={formatPercent(portfolioWeight)}
                />
                <InfoRow
                  label={labels.availableFrozen}
                  value={`${formatQuantity(position.available_qty)} / ${formatQuantity(
                    position.frozen_qty,
                  )}`}
                />
                <InfoRow
                  label={labels.unrealizedPnl}
                  value={formatCurrency(position.unrealized_pnl)}
                  tone={position.unrealized_pnl >= 0 ? 'success' : 'danger'}
                />
              </div>
            </div>
          </section>

          <section
            data-testid="holding-related-actions-panel"
            className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.relatedActions}</div>
              <div className="mt-4 grid gap-2">
                <ActionLink href="/portfolio" label={labels.actionPortfolio} />
                <ActionLink href="/market" label={labels.actionMarket} />
                <ActionLink href="/trading" label={labels.actionTrading} />
                <ActionLink href="/activity" label={labels.actionActivity} />
              </div>
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}

function MetricGrid({
  metrics,
  testId,
  metricTestId,
}: {
  metrics: DetailMetric[];
  testId?: string;
  metricTestId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="mt-5 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
    >
      {metrics.map((metric) => (
        <div
          key={metric.label}
          data-testid={metricTestId}
          className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3"
        >
          <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
            {metric.label}
          </div>
          <div
            className={`mt-2 break-words font-mono text-sm font-semibold tabular-nums ${
              metric.tone === 'success'
                ? 'text-[var(--app-success)]'
                : metric.tone === 'danger'
                  ? 'text-[var(--app-danger)]'
                  : metric.tone === 'warning'
                    ? 'text-[var(--app-warning)]'
                    : 'text-[var(--app-text)]'
            }`}
          >
            {metric.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function InfoRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'success' | 'danger' | 'warning';
}) {
  return (
    <div
      data-testid="holding-info-row"
      className="grid min-w-0 grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-start gap-3 border-b border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] pb-2 text-sm last:border-b-0 last:pb-0"
    >
      <span className="app-muted min-w-0 break-words">{label}</span>
      <span
        data-testid="holding-info-row-value"
        className={`min-w-0 break-words text-right font-mono font-semibold tabular-nums ${
          tone === 'success'
            ? 'text-[var(--app-success)]'
            : tone === 'danger'
              ? 'text-[var(--app-danger)]'
              : tone === 'warning'
                ? 'text-[var(--app-warning)]'
                : 'text-[var(--app-text)]'
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function StatusBadge({
  label,
  tone,
}: {
  label: string;
  tone: 'success' | 'warning' | 'danger';
}) {
  const colorClass =
    tone === 'success'
      ? 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-[var(--app-success-border)]'
      : tone === 'danger'
        ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-[var(--app-danger-border)]'
        : 'bg-[var(--app-warning-bg)] text-[var(--app-warning)] ring-[var(--app-warning-border)]';
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${colorClass}`}
    >
      {label}
    </span>
  );
}

function LedgerTrace({
  entries,
  loading,
}: {
  entries: LedgerEntry[];
  loading: boolean;
}) {
  const copy = useCopy();
  const labels = copy.portfolio.detail;
  const detailLabels = copy.activity.feed.detailFields;
  const { locale } = usePreferences();

  if (loading) {
    return <div className="app-muted mt-5 text-sm">{labels.loading}</div>;
  }
  if (entries.length === 0) {
    return (
      <div className="mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
        {labels.noLedger}
      </div>
    );
  }

  return (
    <div
      data-testid="holding-ledger-scroll"
      className="mt-5 min-w-0 max-w-full overflow-x-scroll overscroll-x-contain pb-2 [scrollbar-gutter:stable]"
    >
      <table
        data-testid="holding-ledger-table"
        className="app-data-table w-[880px] min-w-max text-left text-sm"
      >
        <thead className="app-kicker text-xs uppercase tracking-[0.16em]">
          <tr>
            <th className="px-4 py-3">{labels.entryType}</th>
            <th className="px-4 py-3">{labels.quantity}</th>
            <th className="px-4 py-3 text-right">{labels.price}</th>
            <th className="px-4 py-3 text-right">{labels.amount}</th>
            <th className="px-4 py-3">{labels.note}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const detailLines = formatLedgerExecutionDetailLines(
              entry,
              detailLabels,
              locale,
            );
            return (
              <tr key={entry.id}>
                <td className="px-4 py-3.5">
                  <div className="font-semibold">
                    {formatLedgerEntryTypeLabel(entry, locale)}
                  </div>
                  <div className="app-muted mt-1 text-xs tabular-nums">
                    {formatTimestamp(entry.timestamp)}
                  </div>
                </td>
                <td className="px-4 py-3.5 font-mono tabular-nums">
                  {formatQuantity(entry.quantity)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                  {formatPrice(entry.price)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                  <div>{formatCurrency(calculateLedgerEntryAmount(entry))}</div>
                  {detailLines.length > 0 ? (
                    <div className="app-muted mt-1 flex flex-col items-end gap-0.5 text-xs">
                      {detailLines.map((detail) => (
                        <span key={detail.label}>
                          {detail.label} {detail.value}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </td>
                <td className="max-w-[280px] px-4 py-3.5 text-[var(--app-muted)]">
                  <span className="line-clamp-2 break-words">
                    {formatLedgerPublicNote(entry) ?? '--'}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ActionLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      data-testid="holding-related-action-link"
      className="app-button-secondary min-w-0 break-words rounded-2xl px-4 py-2.5 text-center text-sm font-semibold"
      aria-label={label}
    >
      {label}
    </a>
  );
}

function StatusPanel({
  title,
  detail,
  tone,
}: {
  title: string;
  detail: string;
  tone: 'neutral' | 'danger';
}) {
  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-5">
        <div
          className={`app-product-mark ${
            tone === 'danger' ? 'text-[var(--app-danger)]' : ''
          }`}
        >
          {title}
        </div>
        <p className="app-muted mt-2 text-sm">{detail}</p>
      </div>
    </section>
  );
}
