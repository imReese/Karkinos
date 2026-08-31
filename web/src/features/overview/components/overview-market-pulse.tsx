import { useMemo } from 'react';

import {
  formatPercent as formatPercentValue,
  formatPrice,
  formatTimestamp,
} from '../../../shared/format';
import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import {
  usePreferences,
  type Locale,
} from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { EvidenceState, MetricStrip } from '../../../shared/ui/workbench';
import type {
  MarketDataHealthResponse,
  MarketHealthQuote,
} from '../overview-feature-boundary';

const MARKET_INDEX_DISPLAY_NAMES: Record<string, { en: string; zh: string }> = {
  '000001': { en: 'Shanghai Composite', zh: '上证指数' },
  '399001': { en: 'Shenzhen Component', zh: '深证成指' },
  '399006': { en: 'ChiNext Index', zh: '创业板指' },
  '000300': { en: 'CSI 300', zh: '沪深300' },
  '000905': { en: 'CSI 500', zh: '中证500' },
  '000016': { en: 'SSE 50', zh: '上证50' },
};

function marketPulseToneClass(value: number | null) {
  if (value == null || value === 0) {
    return 'text-[var(--app-pnl-neutral)]';
  }
  return value > 0
    ? 'text-[var(--app-pnl-positive)]'
    : 'text-[var(--app-pnl-negative)]';
}

function normalizeMarketPulsePercent(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return Math.abs(value) > 1.5 ? value / 100 : value;
}

function marketPulseChangePct(quote: MarketHealthQuote) {
  return normalizeMarketPulsePercent(
    quote.daily_change_pct ?? quote.change_pct ?? quote.pct_chg,
  );
}

function finiteMarketPulseNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function marketPulseChangeAmount(quote: MarketHealthQuote) {
  return finiteMarketPulseNumber(quote.daily_change ?? quote.change);
}

function marketPulseSignalValue(quote: MarketHealthQuote) {
  return marketPulseChangePct(quote) ?? marketPulseChangeAmount(quote);
}

function formatMarketPulseSignedValue(value: number, locale: Locale) {
  const absolute = new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  if (value > 0) return `+${absolute}`;
  if (value < 0) return `-${absolute}`;
  return absolute;
}

function marketPulseMoveLabel(
  quote: MarketHealthQuote,
  labels: AppCopy['overview']['dashboard'],
  locale: Locale,
) {
  const changePct = marketPulseChangePct(quote);
  if (changePct !== null) {
    return formatPercentValue(changePct, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  const changeAmount = marketPulseChangeAmount(quote);
  if (changeAmount !== null) {
    return formatMarketPulseSignedValue(changeAmount, locale);
  }
  return labels.marketPulseMoveMissing;
}

function isMarketIndexQuote(quote: MarketHealthQuote) {
  const symbol = quote.symbol.trim();
  const assetClass = quote.asset_class.toLowerCase();
  const text = `${quote.display_name ?? ''} ${quote.name ?? ''}`.toLowerCase();
  return (
    assetClass === 'index' ||
    symbol in MARKET_INDEX_DISPLAY_NAMES ||
    text.includes('index') ||
    text.includes('指数') ||
    text.includes('上证') ||
    text.includes('深证') ||
    text.includes('创业板') ||
    text.includes('沪深') ||
    text.includes('中证')
  );
}

function marketIndexDisplayName(quote: MarketHealthQuote, locale: Locale) {
  const fallback = MARKET_INDEX_DISPLAY_NAMES[quote.symbol];
  return (
    quote.display_name?.trim() ||
    quote.name?.trim() ||
    (fallback ? fallback[locale] : null) ||
    quote.symbol
  );
}

function marketPulseSignalLabel(
  quotes: MarketHealthQuote[],
  labels: AppCopy['overview']['dashboard'],
) {
  const changes = quotes
    .map((quote) => marketPulseSignalValue(quote))
    .filter((value): value is number => value !== null);
  if (quotes.length === 0) return labels.marketPulsePending;
  if (changes.length === 0) return labels.marketPulseNoSignal;
  const positiveCount = changes.filter((value) => value > 0).length;
  const negativeCount = changes.filter((value) => value < 0).length;
  if (positiveCount > negativeCount) return labels.marketPulsePositive;
  if (negativeCount > positiveCount) return labels.marketPulseNegative;
  return labels.marketPulseMixed;
}

export function OverviewMarketPulse({
  marketHealth,
  isLoading,
  isError,
}: {
  marketHealth?: MarketDataHealthResponse;
  isLoading: boolean;
  isError: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const indexQuotes = useMemo(
    () =>
      (marketHealth?.quotes ?? [])
        .filter(isMarketIndexQuote)
        .sort((left, right) => {
          const leftKnown = left.symbol in MARKET_INDEX_DISPLAY_NAMES ? 0 : 1;
          const rightKnown = right.symbol in MARKET_INDEX_DISPLAY_NAMES ? 0 : 1;
          return (
            leftKnown - rightKnown || left.symbol.localeCompare(right.symbol)
          );
        })
        .slice(0, 4),
    [marketHealth?.quotes],
  );
  const signalLabel = marketPulseSignalLabel(indexQuotes, labels);
  const changeValues = indexQuotes
    .map((quote) => marketPulseSignalValue(quote))
    .filter((value): value is number => value !== null);
  const missingChangeCount = indexQuotes.length - changeValues.length;
  const coverageLabel =
    missingChangeCount > 0
      ? labels.marketPulseMissingChanges(missingChangeCount)
      : labels.marketPulseChangeCoverage(
          changeValues.length,
          indexQuotes.length,
        );
  const sourceStatus = formatPublicStatus(
    marketHealth?.source_health ?? marketHealth?.provider_status,
    locale,
  );

  return (
    <section
      className="min-w-0 overflow-hidden border-y border-[var(--app-divider)] bg-transparent"
      data-testid="overview-market-pulse"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--app-divider)] py-2.5">
        <div className="min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {labels.marketPulse}
          </h2>
          <div className="mt-1 max-w-3xl text-xs text-[var(--app-text-secondary)]">
            {labels.marketPulseDetail}
          </div>
        </div>
        <a
          href="/market"
          className="app-button-secondary rounded-[var(--app-radius-control)] px-2.5 py-1.5 text-xs font-semibold"
        >
          {labels.viewMarket}
        </a>
      </div>

      <div className="min-w-0 py-3">
        {isLoading ? (
          <EvidenceState kind="loading" title={copy.states.loading} />
        ) : isError ? (
          <EvidenceState kind="error" title={copy.states.error} />
        ) : indexQuotes.length === 0 ? (
          <EvidenceState
            kind="missing"
            title={labels.marketPulsePending}
            description={labels.marketPulseMissing}
          />
        ) : (
          <div className="grid min-w-0 gap-3">
            <MetricStrip
              ariaLabel={labels.marketPulse}
              items={[
                {
                  id: 'signal',
                  label: labels.marketPulseDisclosure,
                  value: (
                    <span
                      className="block whitespace-normal break-words"
                      title={signalLabel}
                    >
                      {signalLabel}
                    </span>
                  ),
                },
                {
                  id: 'source',
                  label: labels.dataStatus,
                  value: sourceStatus,
                  detail: coverageLabel,
                  tone: missingChangeCount > 0 ? 'warning' : 'neutral',
                },
              ]}
            />
            <div className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
              {indexQuotes.map((quote) => (
                <MarketPulseQuoteRow
                  key={quote.symbol}
                  quote={quote}
                  copy={copy}
                  locale={locale}
                />
              ))}
            </div>
            <div
              className="border-l-2 border-[var(--app-warning-indicator)] bg-[var(--app-warning-bg)] px-3 py-2"
              data-testid="market-breadth-heatmap-unavailable"
            >
              <div className="text-xs font-semibold text-[var(--app-warning-text)]">
                {labels.marketHeatmapUnavailable}
              </div>
              <div className="app-type-compact mt-1 text-[var(--app-text-secondary)]">
                {labels.marketHeatmapUnavailableDetail}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function MarketPulseQuoteRow({
  quote,
  copy,
  locale,
}: {
  quote: MarketHealthQuote;
  copy: AppCopy;
  locale: Locale;
}) {
  const labels = copy.overview.dashboard;
  const changeValue = marketPulseSignalValue(quote);
  const changeMissing = changeValue === null;
  const changeAmount = marketPulseChangeAmount(quote);
  const changePct = marketPulseChangePct(quote);
  return (
    <a
      href={`/market?symbol=${encodeURIComponent(quote.symbol)}`}
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-2 py-2 hover:bg-[var(--app-accent-bg)]"
    >
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-[var(--app-text)]">
          {marketIndexDisplayName(quote, locale)}
        </div>
        <div className="app-type-micro mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[var(--app-text-tertiary)]">
          <span className="font-mono">{quote.symbol}</span>
          <span>{formatPublicStatus(quote.quote_status, locale)}</span>
          <span>{formatTimestamp(quote.timestamp)}</span>
        </div>
      </div>
      <div className="grid shrink-0 justify-items-end gap-1">
        <span className="font-mono text-sm font-semibold text-[var(--app-soft)] tabular-nums">
          {formatPrice(quote.price)}
        </span>
        <span
          data-testid={`market-pulse-change-amount-${quote.symbol}`}
          className={`font-mono text-xs font-semibold tabular-nums ${marketPulseToneClass(
            changeValue,
          )} ${changeMissing ? 'text-[var(--app-warning-text)]' : ''}`}
        >
          {changeAmount === null
            ? marketPulseMoveLabel(quote, labels, locale)
            : formatMarketPulseSignedValue(changeAmount, locale)}
        </span>
        {changePct !== null && changeAmount !== null ? (
          <span
            data-testid={`market-pulse-change-pct-${quote.symbol}`}
            className={`font-mono text-[length:var(--app-font-size-micro)] font-semibold tabular-nums ${marketPulseToneClass(
              changePct,
            )}`}
          >
            {formatPercentValue(changePct, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        ) : null}
      </div>
    </a>
  );
}
