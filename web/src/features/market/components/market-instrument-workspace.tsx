import type { ReactNode } from 'react';
import { X } from 'lucide-react';

import { useCopy } from '../../../app/copy';
import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
} from '../../../app/components/workbench';
import { usePreferences, type Locale } from '../../../app/preferences';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import {
  isConfirmedMarketDataStatus,
  isUnconfirmedMarketDataStatus,
} from '../../../shared/market-data-status';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import type { KlineBar, MarketHealthQuote, ResearchBoardItem } from '../api';
import {
  PriceStructureChart,
  PriceStructureLoadingState,
} from './price-structure-chart';

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

function formatResearchCount(count: number, locale: Locale) {
  if (locale === 'zh') {
    return `${count} 条研究记录`;
  }
  return `${count} research ${count === 1 ? 'record' : 'records'}`;
}

function quoteTone(status: string | null | undefined) {
  if (isConfirmedMarketDataStatus(status)) {
    return 'success' as const;
  }
  if (isUnconfirmedMarketDataStatus(status)) {
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
      className="grid min-w-0 items-start gap-4 md:grid-cols-[minmax(220px,256px)_minmax(0,1fr)] xl:grid-cols-[minmax(264px,296px)_minmax(0,1fr)]"
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
          <div className="mt-3 h-44 border-y border-[var(--app-divider)] bg-[linear-gradient(to_right,var(--app-divider)_1px,transparent_1px),linear-gradient(to_bottom,var(--app-divider)_1px,transparent_1px)] bg-[size:25%_100%,100%_33.333%] opacity-70 motion-safe:animate-pulse sm:h-56" />
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
  const selectedDailyMove = selectedHealthQuote?.daily_change ?? null;

  return (
    <div
      className="grid min-w-0 items-start gap-4 md:grid-cols-[minmax(220px,256px)_minmax(0,1fr)] xl:grid-cols-[minmax(264px,296px)_minmax(0,1fr)]"
      data-testid="market-instrument-workspace"
    >
      <aside className="min-w-0 border-y border-[var(--app-divider)] md:sticky md:top-3">
        <div className="flex items-center justify-between gap-3 border-b border-[var(--app-divider)] px-3 py-2.5 md:items-start md:py-3">
          <div className="min-w-0">
            <div className="app-kicker app-type-overline hidden md:block">
              {labels.personalUniverse}
            </div>
            <h2 className="app-type-section-title text-[var(--app-text)] md:mt-1">
              {labels.watchlist}
            </h2>
            <p className="app-type-micro mt-1 hidden text-[var(--app-text-tertiary)] md:block">
              {labels.scopeBoundary}
            </p>
          </div>
          <span className="shrink-0 text-xs tabular-nums text-[var(--app-text-secondary)]">
            {items.length}
          </span>
        </div>

        {watchlistEditor}

        {items.length > 0 ? (
          <ul
            aria-label={labels.watchlist}
            className="grid min-w-0 auto-cols-[minmax(15rem,85%)] snap-x snap-mandatory grid-flow-col divide-x divide-[var(--app-divider)] overflow-x-auto overscroll-x-contain scroll-px-3 sm:auto-cols-[minmax(15rem,48%)] md:block md:max-h-[calc(100dvh-39rem)] md:snap-none md:divide-x-0 md:divide-y md:overflow-x-visible md:overflow-y-auto md:overscroll-y-contain lg:max-h-[min(62vh,42rem)]"
            data-mobile-layout="horizontal-rail"
            data-testid="market-instrument-list"
          >
            {items.map((item) => {
              const quote = healthBySymbol.get(item.symbol) ?? null;
              const isActive = item.symbol === activeSymbol;
              const statusLabel = quote?.quote_status
                ? formatPublicStatus(quote.quote_status, locale)
                : labels.unknown;
              const statusId = `market-instrument-state-${encodeURIComponent(item.symbol)}`;
              const ageLabel = formatAge(quote?.quote_age_seconds, locale);
              const researchCountLabel = formatResearchCount(
                item.research_count,
                locale,
              );
              const dailyMove = quote?.daily_change ?? null;
              return (
                <li
                  key={item.symbol}
                  className={`group flex min-w-0 snap-start border-l-[3px] transition-colors motion-reduce:transition-none md:snap-none ${
                    isActive
                      ? 'border-l-[var(--app-accent)] bg-[var(--app-accent-bg)]'
                      : 'border-l-transparent hover:bg-[var(--app-surface-raised)]'
                  }`}
                  data-market-instrument-row={item.symbol}
                >
                  <button
                    type="button"
                    aria-controls="market-instrument-detail"
                    aria-describedby={statusId}
                    aria-pressed={isActive}
                    aria-label={`${item.name || item.symbol} ${item.symbol}`}
                    className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] gap-3 px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--app-focus-ring)]"
                    onClick={() => {
                      onSelect(item.symbol);
                      if (
                        typeof window === 'undefined' ||
                        !window.matchMedia('(max-width: 1279px)').matches
                      ) {
                        return;
                      }
                      window.requestAnimationFrame(() => {
                        document
                          .getElementById('market-instrument-detail')
                          ?.scrollIntoView({
                            block: 'start',
                            behavior: window.matchMedia(
                              '(prefers-reduced-motion: reduce)',
                            ).matches
                              ? 'auto'
                              : 'smooth',
                          });
                      });
                    }}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-[var(--app-text)]">
                        {item.name || item.symbol}
                      </span>
                      <span className="app-type-micro mt-0.5 block truncate font-mono tabular-nums text-[var(--app-text-tertiary)]">
                        {item.symbol} ·{' '}
                        {formatAssetClassLabel(item.asset_class, copy.common)}
                      </span>
                      <span
                        className="app-type-micro mt-1 grid gap-0.5 leading-4 text-[var(--app-text-tertiary)]"
                        data-testid={`market-instrument-status-${item.symbol}`}
                        id={statusId}
                      >
                        <span className="block break-words">
                          {statusLabel} · {ageLabel}
                        </span>
                        <span className="block break-words">
                          {researchCountLabel}
                        </span>
                      </span>
                    </span>
                    <span className="text-right">
                      <span
                        className="block text-sm font-semibold tabular-nums text-[var(--app-text)]"
                        data-testid={`market-instrument-price-${item.symbol}`}
                      >
                        {formatCurrency(item.price)}
                      </span>
                      <span
                        className={`app-type-micro mt-1 block font-semibold tabular-nums ${moveTone(dailyMove)}`}
                      >
                        {dailyMove == null ? '--' : formatCurrency(dailyMove)}
                      </span>
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`${labels.remove}: ${item.name || item.symbol} ${item.symbol}`}
                    className="mr-1 grid h-10 w-10 shrink-0 place-items-center self-center rounded-[var(--app-radius-control)] text-[var(--app-text-tertiary)] opacity-70 transition-opacity hover:bg-[var(--app-surface-overlay)] hover:text-[var(--app-text)] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)] motion-reduce:transition-none xl:h-8 xl:w-8 xl:opacity-0 xl:group-hover:opacity-100"
                    onClick={() => void onRemove(item.symbol)}
                  >
                    <X aria-hidden="true" size={14} strokeWidth={1.8} />
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <EvidenceState
            className="border-0"
            kind="empty"
            title={labels.noSelection}
            description={labels.scopeBoundary}
          />
        )}
      </aside>

      <section
        id="market-instrument-detail"
        className="min-w-0 scroll-mt-20"
        data-testid="market-selected-instrument"
      >
        {selectedItem ? (
          <>
            <header className="flex min-w-0 items-end justify-between gap-4 border-b border-[var(--app-divider)] pb-4">
              <div className="min-w-0">
                <div className="app-kicker app-type-overline">
                  {formatAssetClassLabel(selectedItem.asset_class, copy.common)}{' '}
                  · {selectedItem.symbol}
                </div>
                <h2 className="app-page-title mt-1 truncate text-[var(--app-text)]">
                  {selectedItem.name || selectedItem.symbol}
                </h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--app-text-secondary)]">
                  <StatusBadge tone={quoteTone(selectedQuoteStatus)}>
                    {selectedQuoteStatus
                      ? formatPublicStatus(selectedQuoteStatus, locale)
                      : labels.unknown}
                  </StatusBadge>
                  <span className="tabular-nums">
                    {formatTimestamp(selectedHealthQuote?.timestamp)}
                  </span>
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
                  tone: isUnconfirmedMarketDataStatus(selectedQuoteStatus)
                    ? 'warning'
                    : 'neutral',
                },
                {
                  id: 'research-count',
                  label: labels.researchCount,
                  value: selectedItem.research_count,
                  detail: formatTimestamp(selectedItem.last_research_at),
                },
              ]}
            />

            <dl className="mt-3 grid min-w-0 border-t border-[var(--app-divider)] text-xs sm:grid-cols-2">
              {[
                [labels.quoteSource, selectedHealthQuote?.quote_source ?? '--'],
                [
                  labels.snapshotLabel,
                  formatTimestamp(selectedItem.last_snapshot_at),
                ],
                [
                  labels.staleReason,
                  formatStaleReason(
                    selectedHealthQuote?.stale_reason,
                    copy.common.staleReasons,
                  ),
                ],
                [labels.providerNextAction, selectedQuoteNextAction ?? '--'],
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
          </>
        ) : (
          <EvidenceState kind="empty" title={labels.noSelection} />
        )}
      </section>
    </div>
  );
}
