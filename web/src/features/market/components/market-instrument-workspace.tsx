import { useState, type ReactNode } from 'react';
import { ArrowUpRight, Check, Copy, LineChart, PieChart } from 'lucide-react';

import { useCopy } from '../../../shared/i18n/context';
import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
} from '../../../shared/ui/workbench';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import {
  usePreferences,
  type Locale,
} from '../../../shared/preferences/context';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { isUnconfirmedMarketDataStatus } from '../../../shared/market-data-status';
import { formatStaleReason } from '../../../shared/stale-reason';
import type { KlineBar, MarketHealthQuote, ResearchBoardItem } from '../api';
import {
  formatMarketQuoteLabel,
  marketQuoteCacheLabel,
} from '../market-quote-presentation';
import {
  PriceStructureChart,
  PriceStructureLoadingState,
} from './price-structure-chart';
import { MarketWatchlistSidebar } from './market-watchlist-sidebar';

export {
  MarketWatchlistSidebar,
  type MarketSortKey,
  type SortDirection,
} from './market-watchlist-sidebar';

function CopySymbolButton({
  symbol,
  copyLabel,
  copiedLabel,
}: {
  symbol: string;
  copyLabel: string;
  copiedLabel: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(symbol);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }
    } catch {
      // Fallback
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="group/copy inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[var(--app-text-secondary)] transition-colors hover:bg-[var(--app-surface-overlay)] hover:text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--app-focus-ring)] active:scale-[0.97]"
      aria-label={`${copied ? copiedLabel : copyLabel}: ${symbol}`}
      title={`${copied ? copiedLabel : copyLabel}: ${symbol}`}
      data-testid="market-copy-symbol-btn"
    >
      <span className="font-semibold">{symbol}</span>
      {copied ? (
        <Check
          size={12}
          strokeWidth={2.2}
          className="text-[var(--app-pnl-positive)]"
          aria-hidden="true"
        />
      ) : (
        <Copy
          size={12}
          strokeWidth={1.8}
          className="opacity-50 transition-opacity group-hover/copy:opacity-100"
          aria-hidden="true"
        />
      )}
      {copied ? (
        <span className="app-type-micro font-sans font-medium text-[var(--app-pnl-positive)]">
          {copiedLabel}
        </span>
      ) : null}
    </button>
  );
}

function formatAge(seconds: number | null | undefined, locale: Locale) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    const value = Math.max(0, Math.round(seconds));
    return locale === 'zh' ? `${value}秒` : `${value}s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return locale === 'zh' ? `${minutes}分钟` : `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return locale === 'zh' ? `${hours}小时` : `${hours}h`;
  }
  const days = Math.round(hours / 24);
  return locale === 'zh' ? `${days}天` : `${days}d`;
}

function quoteTone(status: string | null | undefined) {
  if (status !== 'cache' && isUnconfirmedMarketDataStatus(status)) {
    return 'warning' as const;
  }
  return 'neutral' as const;
}

function moveTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return 'text-[var(--app-pnl-neutral)]';
  }
  return value > 0
    ? 'text-[var(--app-pnl-positive)]'
    : 'text-[var(--app-pnl-negative)]';
}

export function MarketInstrumentWorkspaceLoading({
  title,
  description,
}: {
  title: ReactNode;
  description?: ReactNode;
}) {
  return (
    <div
      aria-busy="true"
      className="grid min-w-0 items-start gap-4 md:grid-cols-[minmax(280px,320px)_minmax(0,1fr)] xl:grid-cols-[minmax(320px,360px)_minmax(0,1fr)]"
      data-testid="market-instrument-loading-workspace"
    >
      <aside
        aria-hidden="true"
        className="min-w-0 border-y border-[var(--app-divider)] md:sticky md:top-3"
      >
        <div className="border-b border-[var(--app-divider)] px-3 py-3">
          <span className="block h-3 w-24 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
          <span className="mt-2 block h-2 w-40 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
        </div>
        <div className="grid auto-cols-[minmax(15rem,85%)] grid-flow-col divide-x divide-[var(--app-divider)] overflow-hidden sm:auto-cols-[minmax(15rem,48%)] md:block md:divide-x-0 md:divide-y">
          {Array.from({ length: 3 }, (_, index) => (
            <div
              key={index}
              className="grid min-w-0 grid-cols-[minmax(0,1fr)_4.5rem] gap-3 px-3 py-3"
            >
              <span className="min-w-0">
                <span className="block h-3 w-28 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
                <span className="mt-2 block h-2 w-20 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
                <span className="mt-2 block h-2 w-32 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
              </span>
              <span className="min-w-0">
                <span className="ml-auto block h-3 w-16 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
                <span className="ml-auto mt-2 block h-2 w-12 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
              </span>
            </div>
          ))}
        </div>
      </aside>

      <section className="min-w-0">
        <EvidenceState kind="loading" title={title} description={description} />
        <div aria-hidden="true" className="mt-4 min-w-0">
          <div className="flex items-end justify-between gap-4 border-b border-[var(--app-divider)] pb-4">
            <span className="min-w-0 flex-1">
              <span className="block h-2 w-24 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
              <span className="mt-2 block h-6 w-44 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
            </span>
            <span className="block h-6 w-20 shrink-0 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
          </div>
          <div className="mt-3 h-44 border-y border-[var(--app-divider)] bg-[linear-gradient(to_right,var(--app-divider)_1px,transparent_1px),linear-gradient(to_bottom,var(--app-divider)_1px,transparent_1px)] bg-[size:25%_100%,100%_33.333%] opacity-70 motion-safe:animate-pulse sm:h-56 xl:h-[26rem] 2xl:h-[28rem]" />
          <div className="mt-3 grid grid-cols-3 divide-x divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {Array.from({ length: 3 }, (_, index) => (
              <span key={index} className="min-w-0 px-3 py-3">
                <span className="block h-2 w-14 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
                <span className="mt-2 block h-3 w-20 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function resolveQuoteSourceLabel(
  source: string | null | undefined,
  locale: Locale,
): string {
  if (!source) return '--';
  const quoteSourceLabels: Record<string, string> = {
    tushare_realtime_quote:
      locale === 'zh' ? 'TuShare 实时行情' : 'TuShare real-time quote',
    tushare_daily: locale === 'zh' ? 'TuShare 日行情' : 'TuShare daily quote',
    tushare_fund_nav: locale === 'zh' ? 'TuShare 基金净值' : 'TuShare fund NAV',
    eastmoney_fund_estimate:
      locale === 'zh' ? '东方财富基金估值' : 'Eastmoney fund estimate',
    sina_fund_estimate:
      locale === 'zh' ? '新浪基金盘中估值' : 'Sina intraday fund estimate',
  };
  return quoteSourceLabels[source] ?? source;
}

export function MarketInstrumentWorkspace({
  items,
  healthBySymbol,
  activeSymbol,
  selectedItem,
  selectedHealthQuote,
  selectedQuoteNextAction,
  bars,
  barsLoading,
  barsError,
  onRetryBars,
  watchlistEditor,
  onSelect,
  onRemove,
}: {
  items: ResearchBoardItem[];
  healthBySymbol: Map<string, MarketHealthQuote>;
  activeSymbol: string;
  selectedItem: ResearchBoardItem | null;
  selectedHealthQuote: MarketHealthQuote | null;
  selectedQuoteNextAction: string | null;
  bars: KlineBar[];
  barsLoading: boolean;
  barsError: boolean;
  onRetryBars: () => void;
  watchlistEditor?: ReactNode;
  onSelect: (symbol: string) => void;
  onRemove: (symbol: string) => Promise<void>;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.market;
  const selectedQuoteStatus = selectedHealthQuote?.quote_status ?? null;
  const selectedCacheLabel = marketQuoteCacheLabel(selectedHealthQuote, locale);
  const selectedDailyMove = selectedHealthQuote?.daily_change ?? null;
  const selectedQuoteSource = resolveQuoteSourceLabel(
    selectedHealthQuote?.quote_source,
    locale,
  );
  return (
    <div
      className="grid min-w-0 items-start gap-4 md:grid-cols-[minmax(280px,320px)_minmax(0,1fr)] xl:grid-cols-[minmax(320px,360px)_minmax(0,1fr)]"
      data-testid="market-instrument-workspace"
    >
      <MarketWatchlistSidebar
        items={items}
        healthBySymbol={healthBySymbol}
        activeSymbol={activeSymbol}
        watchlistEditor={watchlistEditor}
        onSelect={onSelect}
        onRemove={onRemove}
      />

      <section
        id="market-instrument-detail"
        className="min-w-0 scroll-mt-20"
        data-testid="market-selected-instrument"
      >
        {selectedItem ? (
          <>
            <header className="flex min-w-0 items-end justify-between gap-4 border-b border-[var(--app-divider)] pb-4">
              <div className="min-w-0">
                <div className="app-kicker app-type-overline flex flex-wrap items-center gap-1.5">
                  <span>
                    {formatAssetClassLabel(
                      selectedItem.asset_class,
                      copy.common,
                    )}
                  </span>
                  <span aria-hidden="true">·</span>
                  <CopySymbolButton
                    symbol={selectedItem.symbol}
                    copyLabel={labels.copySymbol}
                    copiedLabel={labels.symbolCopied}
                  />
                  {selectedItem.is_holding ? (
                    <span
                      data-testid="market-selected-holding-badge"
                      className="app-type-micro rounded px-1.5 py-0.2 font-sans font-medium bg-[color-mix(in_srgb,var(--app-accent)_15%,transparent)] text-[var(--app-accent)] border border-[color-mix(in_srgb,var(--app-accent)_30%,transparent)]"
                    >
                      {labels.holdingBadge}
                    </span>
                  ) : null}
                </div>
                <h2 className="app-page-title mt-1 truncate text-[var(--app-text)]">
                  {selectedItem.name || selectedItem.symbol}
                </h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--app-text-secondary)]">
                  <StatusBadge tone={quoteTone(selectedQuoteStatus)}>
                    {formatMarketQuoteLabel(selectedHealthQuote, locale)}
                  </StatusBadge>
                  {selectedCacheLabel ? (
                    <span>{selectedCacheLabel}</span>
                  ) : null}
                  <span className="tabular-nums">
                    {formatTimestamp(selectedHealthQuote?.timestamp)}
                  </span>
                  {selectedHealthQuote?.nav_date ? (
                    <span>
                      {locale === 'zh' ? '净值日期' : 'NAV date'}{' '}
                      {selectedHealthQuote.nav_date}
                    </span>
                  ) : null}
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  <a
                    href={`/backtest?symbol=${encodeURIComponent(selectedItem.symbol)}&assetClass=${encodeURIComponent(selectedItem.asset_class)}`}
                    onClick={(e) =>
                      handleClientNavigation(
                        e,
                        `/backtest?symbol=${encodeURIComponent(selectedItem.symbol)}&assetClass=${encodeURIComponent(selectedItem.asset_class)}`,
                      )
                    }
                    className="app-button-secondary inline-flex min-h-7 items-center gap-1.5 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-semibold hover:border-[var(--app-accent-border)] hover:bg-[var(--app-accent-bg)] transition-colors"
                    data-testid="market-open-backtest-link"
                    title={`${labels.openBacktest}: ${selectedItem.symbol}`}
                  >
                    <LineChart
                      size={13}
                      className="text-[var(--app-accent)]"
                      aria-hidden="true"
                    />
                    <span>{labels.openBacktest}</span>
                    <ArrowUpRight
                      size={11}
                      className="opacity-60"
                      aria-hidden="true"
                    />
                  </a>
                  {selectedItem.is_holding ? (
                    <a
                      href={`/portfolio/${encodeURIComponent(selectedItem.symbol)}`}
                      onClick={(e) =>
                        handleClientNavigation(
                          e,
                          `/portfolio/${encodeURIComponent(selectedItem.symbol)}`,
                        )
                      }
                      className="app-button-secondary inline-flex min-h-7 items-center gap-1.5 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-semibold hover:border-[var(--app-accent-border)] hover:bg-[var(--app-accent-bg)] transition-colors"
                      data-testid="market-view-holding-link"
                      title={`${labels.viewHolding}: ${selectedItem.symbol}`}
                    >
                      <PieChart
                        size={13}
                        className="text-[var(--app-accent)]"
                        aria-hidden="true"
                      />
                      <span>{labels.viewHolding}</span>
                      <ArrowUpRight
                        size={11}
                        className="opacity-60"
                        aria-hidden="true"
                      />
                    </a>
                  ) : null}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div
                  className="app-page-title tabular-nums text-[var(--app-text)]"
                  data-testid="market-selected-price"
                >
                  {formatCurrency(selectedItem.price)}
                </div>
                <div
                  className={`mt-1 text-sm font-semibold tabular-nums ${moveTone(selectedDailyMove)}`}
                  data-testid="market-selected-move"
                >
                  {selectedDailyMove == null
                    ? '--'
                    : formatCurrency(selectedDailyMove)}
                </div>
              </div>
            </header>

            <div className="mt-3">
              {barsLoading ? (
                <PriceStructureLoadingState
                  title={labels.klineLoading}
                  description={labels.klineLoadingDetail}
                />
              ) : barsError ? (
                <EvidenceState
                  kind="error"
                  title={labels.klineError}
                  description={labels.klineErrorDetail}
                  action={
                    <button
                      type="button"
                      className="app-button-secondary min-h-8 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
                      onClick={onRetryBars}
                    >
                      {copy.states.retry}
                    </button>
                  }
                />
              ) : (
                <PriceStructureChart
                  bars={bars}
                  emptyLabel={labels.noChart}
                  titleLabel={labels.priceRangeKline}
                  priceLabel={labels.priceLabel}
                  rangeLabels={labels.klineRanges}
                  axisLabels={labels.klineAxes}
                  rangeAriaLabel={labels.showKlineRange}
                  chartTypeLabels={labels.chartViews}
                />
              )}
            </div>

            <MetricStrip
              className="mt-3"
              ariaLabel={labels.selectedSymbol}
              items={[
                {
                  id: 'holding',
                  label: labels.holdingsContext,
                  value:
                    selectedItem.is_holding && selectedItem.market_value != null
                      ? formatCurrency(selectedItem.market_value)
                      : '--',
                  detail: selectedItem.is_holding
                    ? `${copy.explainability.quantity} ${formatQuantity(
                        selectedItem.quantity,
                      )}`
                    : '--',
                },
                {
                  id: 'quote-age',
                  label: labels.quoteAge,
                  value: formatAge(
                    selectedHealthQuote?.quote_age_seconds,
                    locale,
                  ),
                  detail: formatTimestamp(selectedHealthQuote?.timestamp),
                  tone: quoteTone(selectedQuoteStatus),
                },
                {
                  id: 'research-count',
                  label: labels.researchCount,
                  value: selectedItem.research_count,
                  detail: formatTimestamp(selectedItem.last_research_at),
                },
              ]}
            />

            <MarketInstrumentMetadataList
              labels={labels}
              quoteSource={selectedQuoteSource}
              snapshotAt={selectedItem.last_snapshot_at}
              staleReason={formatStaleReason(
                selectedHealthQuote?.stale_reason,
                copy.common.staleReasons,
              )}
              nextAction={selectedQuoteNextAction}
            />
          </>
        ) : (
          <EvidenceState kind="empty" title={labels.noSelection} />
        )}
      </section>
    </div>
  );
}

function MarketInstrumentMetadataList({
  labels,
  quoteSource,
  snapshotAt,
  staleReason,
  nextAction,
}: {
  labels: {
    quoteSource: string;
    snapshotLabel: string;
    staleReason: string;
    providerNextAction: string;
  };
  quoteSource: string;
  snapshotAt: string | null | undefined;
  staleReason: string;
  nextAction: string | null;
}) {
  return (
    <dl className="mt-3 grid min-w-0 border-t border-[var(--app-divider)] text-xs sm:grid-cols-2">
      {[
        [labels.quoteSource, quoteSource],
        [labels.snapshotLabel, formatTimestamp(snapshotAt)],
        [labels.staleReason, staleReason],
        [labels.providerNextAction, nextAction ?? '--'],
      ].map(([label, value]) => (
        <div
          key={label}
          className="grid min-w-0 grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)] gap-3 border-b border-[var(--app-divider)] px-2 py-2 sm:odd:border-r"
        >
          <dt className="text-[var(--app-text-tertiary)]">{label}</dt>
          <dd className="min-w-0 break-words text-right text-[var(--app-text-secondary)]">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
