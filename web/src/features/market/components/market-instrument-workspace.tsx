import type { ReactNode } from 'react';
import { X } from 'lucide-react';

import { useCopy } from '../../../app/copy';
import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
} from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
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
import { PriceStructureChart } from './price-structure-chart';

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
            <div className="app-kicker hidden text-[11px] uppercase tracking-[0.16em] md:block">
              {labels.personalUniverse}
            </div>
            <h2 className="text-sm font-semibold text-[var(--app-text)] md:mt-1 md:text-base">
              {labels.watchlist}
            </h2>
            <p className="mt-1 hidden text-[11px] leading-4 text-[var(--app-text-tertiary)] md:block">
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
                      <span className="mt-0.5 block truncate font-mono text-[11px] tabular-nums text-[var(--app-text-tertiary)]">
                        {item.symbol} ·{' '}
                        {formatAssetClassLabel(item.asset_class, copy.common)}
                      </span>
                      <span className="mt-1 block truncate text-[11px] text-[var(--app-text-tertiary)]">
                        {statusLabel} · {formatAge(quote?.quote_age_seconds)} ·{' '}
                        {labels.researchCount} {item.research_count}
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
                        className={`mt-1 block text-[11px] font-semibold tabular-nums ${moveTone(dailyMove)}`}
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
            <header className="flex min-w-0 items-end justify-between gap-3 border-b border-[var(--app-divider)] pb-3">
              <div className="min-w-0">
                <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                  {formatAssetClassLabel(selectedItem.asset_class, copy.common)}{' '}
                  · {selectedItem.symbol}
                </div>
                <h2 className="mt-1 truncate text-xl font-semibold tracking-[-0.02em] text-[var(--app-text)] sm:text-2xl">
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
                  className="text-xl font-semibold tabular-nums text-[var(--app-text)] sm:text-2xl"
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
                <EvidenceState
                  kind="loading"
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
                  value: formatAge(selectedHealthQuote?.quote_age_seconds),
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
