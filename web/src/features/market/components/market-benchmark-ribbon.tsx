import { useMemo } from 'react';

import { formatAmount, formatPercent } from '../../../shared/format';
import type { MarketPageController } from '../pages/market-page-controller';

type BenchmarkConfig = {
  id: string;
  code: string;
  nameEn: string;
  nameZh: string;
  symbolMatches: string[];
};

const BENCHMARKS: BenchmarkConfig[] = [
  {
    id: 'sse',
    code: '000001',
    nameEn: 'SSE Composite',
    nameZh: '上证指数',
    symbolMatches: ['000001', 'sh000001', 'sh.000001', '1.000001'],
  },
  {
    id: 'csi300',
    code: '000300',
    nameEn: 'CSI 300',
    nameZh: '沪深300',
    symbolMatches: ['000300', 'sh000300', 'sh.000300', '1.000300'],
  },
  {
    id: 'chinext',
    code: '399006',
    nameEn: 'ChiNext',
    nameZh: '创业板指',
    symbolMatches: ['399006', 'sz399006', 'sz.399006', '0.399006'],
  },
];

type MatchedBenchmark = {
  id: string;
  code: string;
  name: string;
  price: number | null;
  change: number | null;
  changePct: number | null;
  hasItem: boolean;
  actualSymbol?: string;
};

export function MarketBenchmarkRibbon({
  controller,
}: {
  controller: MarketPageController;
}) {
  const { copy, health, items, locale, selectedSymbol, setSelectedSymbol } =
    controller;

  const isZh = locale.toLowerCase().startsWith('zh');

  // Match benchmarks from health quotes or items
  const benchmarks = useMemo<MatchedBenchmark[]>(() => {
    const quotes = health?.quotes ?? [];
    return BENCHMARKS.map((b) => {
      const name = isZh ? b.nameZh : b.nameEn;
      const matchedQuote = quotes.find(
        (q) =>
          b.symbolMatches.includes(q.symbol.toLowerCase()) ||
          q.name?.includes(b.nameZh) ||
          q.display_name?.includes(b.nameZh),
      );
      const matchedItem = items.find(
        (i) =>
          b.symbolMatches.includes(i.symbol.toLowerCase()) ||
          i.name?.includes(b.nameZh),
      );

      const price = matchedQuote?.price ?? matchedItem?.price ?? null;
      let changePct =
        matchedQuote?.daily_change_pct ??
        matchedQuote?.pct_chg ??
        matchedQuote?.change_pct ??
        null;
      let change = matchedQuote?.daily_change ?? matchedQuote?.change ?? null;
      const prevClose =
        matchedQuote?.previous_close ??
        (price !== null && change !== null ? price - change : null);

      if (
        changePct === null &&
        price !== null &&
        prevClose !== null &&
        prevClose !== 0
      ) {
        changePct = ((price - prevClose) / prevClose) * 100;
      }
      if (change === null && price !== null && prevClose !== null) {
        change = price - prevClose;
      }
      const actualSymbol = matchedItem?.symbol ?? matchedQuote?.symbol;

      return {
        id: b.id,
        code: b.code,
        name,
        price,
        change,
        changePct,
        hasItem: Boolean(matchedItem),
        actualSymbol,
      };
    });
  }, [health?.quotes, items, isZh]);

  // Calculate market breadth across all tracked instruments with quote changes
  const breadth = useMemo(() => {
    const quotes = health?.quotes ?? [];
    let advances = 0;
    let declines = 0;
    let flat = 0;
    let totalWithQuote = 0;

    quotes.forEach((q) => {
      const pct = q.daily_change_pct ?? q.pct_chg ?? q.change_pct;
      if (pct !== undefined && pct !== null && Number.isFinite(pct)) {
        totalWithQuote++;
        if (pct > 0) {
          advances++;
        } else if (pct < 0) {
          declines++;
        } else {
          flat++;
        }
      }
    });

    // If health quotes didn't yield change data, inspect items if any have pnl/gain
    const totalTracked = Math.max(items.length, quotes.length);
    const hasData = totalWithQuote > 0;
    const advPercent = hasData ? (advances / totalWithQuote) * 100 : 50;
    const decPercent = hasData ? (declines / totalWithQuote) * 100 : 50;
    const flatPercent = hasData ? (flat / totalWithQuote) * 100 : 0;
    const ratio =
      declines > 0
        ? (advances / declines).toFixed(2)
        : advances > 0
          ? `${advances}`
          : '1.00';

    return {
      advances,
      declines,
      flat,
      totalWithQuote,
      totalTracked,
      hasData,
      advPercent,
      decPercent,
      flatPercent,
      ratio,
    };
  }, [health?.quotes, items.length]);

  return (
    <div
      data-testid="market-benchmark-ribbon"
      aria-label={copy.market.marketBenchmarkRibbon}
      className="flex min-w-0 flex-col gap-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-raised)_65%,transparent)] p-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between"
    >
      {/* Benchmark Indices */}
      <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
        {health && !health.market_open ? (
          <span
            data-testid="market-closed-badge"
            className="inline-flex items-center gap-1 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] px-2 py-0.5 text-[length:var(--app-font-size-micro)] font-medium text-[var(--app-text-tertiary)]"
            title={
              isZh
                ? '市场休市中 · 显示最近交易日收盘数据'
                : 'Market closed. Showing previous session closing data.'
            }
          >
            <span className="inline-block size-1.5 rounded-full bg-[var(--app-text-tertiary)] opacity-60" />
            {isZh ? '休市' : 'Closed'}
          </span>
        ) : null}
        {benchmarks.map((bm) => {
          const isPositive = (bm.changePct ?? 0) > 0;
          const isNegative = (bm.changePct ?? 0) < 0;
          const toneClass = isPositive
            ? 'text-[var(--app-pnl-positive)]'
            : isNegative
              ? 'text-[var(--app-pnl-negative)]'
              : 'text-[var(--app-text-tertiary)]';
          const isSelected =
            bm.actualSymbol && bm.actualSymbol === selectedSymbol;

          const content = (
            <div className="flex items-center gap-2">
              <div className="flex flex-col">
                <span className="app-type-micro font-medium text-[var(--app-text)]">
                  {bm.name}
                </span>
                <span className="app-type-micro font-mono text-[var(--app-text-tertiary)]">
                  {bm.code}
                </span>
              </div>
              <div className="flex flex-col items-end font-mono tabular-nums">
                <span className="text-xs font-semibold text-[var(--app-text)]">
                  {bm.price !== null ? formatAmount(bm.price) : '--'}
                </span>
                <span className={`app-type-micro font-medium ${toneClass}`}>
                  {bm.changePct !== null
                    ? `${isPositive ? '+' : ''}${formatPercent(
                        bm.changePct / 100,
                        {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        },
                      )}`
                    : health && !health.market_open
                      ? isZh
                        ? '-- (休市)'
                        : '-- (Closed)'
                      : '--'}
                </span>
              </div>
            </div>
          );

          if (bm.hasItem && bm.actualSymbol) {
            return (
              <button
                key={bm.id}
                type="button"
                data-testid={`benchmark-card-${bm.id}`}
                aria-label={`${bm.name} ${bm.code}`}
                onClick={() => setSelectedSymbol(bm.actualSymbol!)}
                className={`rounded-[calc(var(--app-radius-control)-2px)] border px-2.5 py-1.5 transition-colors ${
                  isSelected
                    ? 'border-[color-mix(in_srgb,var(--app-accent)_60%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_14%,transparent)]'
                    : 'border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-overlay)_40%,transparent)] hover:border-[color-mix(in_srgb,var(--app-accent)_36%,transparent)]'
                }`}
              >
                {content}
              </button>
            );
          }

          return (
            <div
              key={bm.id}
              data-testid={`benchmark-card-${bm.id}`}
              className="rounded-[calc(var(--app-radius-control)-2px)] border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-overlay)_28%,transparent)] px-2.5 py-1.5"
            >
              {content}
            </div>
          );
        })}
      </div>

      {/* Market Breadth Indicator */}
      <div
        data-testid="market-breadth-summary"
        className="flex min-w-0 flex-wrap items-center gap-3 border-t border-[var(--app-divider)] pt-2 lg:border-t-0 lg:pt-0"
      >
        <div className="flex items-center gap-2">
          <span className="app-type-micro font-medium text-[var(--app-muted)]">
            {copy.market.marketBreadth}
          </span>
          {breadth.hasData ? (
            <div className="flex items-center gap-1.5 font-mono text-xs tabular-nums">
              <span
                data-testid="breadth-advances"
                className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-semibold text-[var(--app-pnl-positive)] bg-[color-mix(in_srgb,var(--app-pnl-positive)_12%,transparent)]"
              >
                ↑ {breadth.advances}
              </span>
              <span
                data-testid="breadth-flat"
                className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[var(--app-muted)] bg-[color-mix(in_srgb,var(--app-surface-overlay)_50%,transparent)]"
              >
                - {breadth.flat}
              </span>
              <span
                data-testid="breadth-declines"
                className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-semibold text-[var(--app-pnl-negative)] bg-[color-mix(in_srgb,var(--app-pnl-negative)_12%,transparent)]"
              >
                ↓ {breadth.declines}
              </span>
            </div>
          ) : (
            <span className="app-type-micro font-mono text-[var(--app-muted)]">
              {copy.market.breadthTrackedCount(breadth.totalTracked)}
            </span>
          )}
        </div>

        {breadth.hasData ? (
          <div className="flex items-center gap-2">
            <div
              className="flex h-2 w-24 sm:w-28 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--app-surface-overlay)_60%,transparent)]"
              aria-label={`${copy.market.breadthRatio}: ${breadth.ratio}`}
            >
              <div
                style={{ width: `${breadth.advPercent}%` }}
                className="bg-[var(--app-pnl-positive)]"
              />
              <div
                style={{ width: `${breadth.flatPercent}%` }}
                className="bg-[var(--app-muted)] opacity-40"
              />
              <div
                style={{ width: `${breadth.decPercent}%` }}
                className="bg-[var(--app-pnl-negative)]"
              />
            </div>
            <span className="font-mono app-type-micro text-[var(--app-muted)]">
              {breadth.ratio}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
