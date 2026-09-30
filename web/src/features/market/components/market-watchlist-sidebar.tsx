import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, RotateCcw, X } from 'lucide-react';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatCurrency } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import {
  usePreferences,
  type Locale,
} from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { EvidenceState } from '../../../shared/ui/workbench';
import type { MarketHealthQuote, ResearchBoardItem } from '../api';

export type MarketSortKey =
  'default' | 'symbol' | 'price' | 'change' | 'change_pct' | 'change_amount';
export type SortDirection = 'asc' | 'desc';

function formatAge(seconds: number | null | undefined, locale: Locale) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '--';
  if (seconds < 60)
    return `${Math.max(0, Math.round(seconds))}${locale === 'zh' ? '秒' : 's'}`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}${locale === 'zh' ? '分钟' : 'm'}`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}${locale === 'zh' ? '小时' : 'h'}`;
  return `${Math.round(hours / 24)}${locale === 'zh' ? '天' : 'd'}`;
}

function formatResearchCount(count: number, locale: Locale) {
  return locale === 'zh'
    ? `${count} 条研究记录`
    : `${count} research ${count === 1 ? 'record' : 'records'}`;
}

function moveTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return 'text-[var(--app-pnl-neutral)]';
  }
  return value > 0
    ? 'text-[var(--app-pnl-positive)]'
    : 'text-[var(--app-pnl-negative)]';
}

function resolveDailyChangePct(
  quote: MarketHealthQuote | null | undefined,
  price: number | null | undefined,
): number | null {
  if (!quote) return null;
  const directPct = quote.daily_change_pct ?? quote.pct_chg ?? quote.change_pct;
  if (typeof directPct === 'number' && Number.isFinite(directPct)) {
    return directPct;
  }
  const move = quote.daily_change ?? quote.change;
  const p = price ?? quote.price;
  if (
    typeof move === 'number' &&
    Number.isFinite(move) &&
    typeof p === 'number' &&
    Number.isFinite(p)
  ) {
    const prev = p - move;
    if (prev > 0) {
      return (move / prev) * 100;
    }
  }
  return null;
}

function SortIndicator({
  active,
  direction,
}: {
  active: boolean;
  direction: 'asc' | 'desc';
}) {
  if (!active) {
    return (
      <ArrowUpDown
        aria-hidden="true"
        size={11}
        strokeWidth={1.8}
        className="shrink-0 text-[var(--app-text-tertiary)] opacity-40 transition-opacity group-hover/btn:opacity-75"
      />
    );
  }
  return direction === 'asc' ? (
    <ArrowUp
      aria-hidden="true"
      size={11}
      strokeWidth={2.2}
      className="shrink-0 text-[var(--app-accent)] motion-safe:transition-transform"
    />
  ) : (
    <ArrowDown
      aria-hidden="true"
      size={11}
      strokeWidth={2.2}
      className="shrink-0 text-[var(--app-accent)] motion-safe:transition-transform"
    />
  );
}

function useWatchlistKeyboardNavigation({
  items,
  activeSymbol,
  onSelect,
}: {
  items: ResearchBoardItem[];
  activeSymbol: string;
  onSelect: (symbol: string) => void;
}) {
  useEffect(() => {
    if (items.length === 0) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (document.querySelector('[role="dialog"]')) {
        return;
      }
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable ||
          target.getAttribute('role') === 'textbox')
      ) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      if (event.key === 'ArrowDown' || event.key === 'j') {
        event.preventDefault();
        const currentIndex = items.findIndex((i) => i.symbol === activeSymbol);
        const nextIndex =
          currentIndex < 0 ? 0 : Math.min(items.length - 1, currentIndex + 1);
        const nextItem = items[nextIndex];
        if (nextItem && nextItem.symbol !== activeSymbol) {
          onSelect(nextItem.symbol);
          const row = document.querySelector<HTMLElement>(
            `[data-market-instrument-row="${nextItem.symbol}"]`,
          );
          if (typeof row?.scrollIntoView === 'function') {
            row.scrollIntoView({ block: 'nearest', inline: 'nearest' });
          }
        }
      } else if (event.key === 'ArrowUp' || event.key === 'k') {
        event.preventDefault();
        const currentIndex = items.findIndex((i) => i.symbol === activeSymbol);
        const prevIndex = currentIndex < 0 ? 0 : Math.max(0, currentIndex - 1);
        const prevItem = items[prevIndex];
        if (prevItem && prevItem.symbol !== activeSymbol) {
          onSelect(prevItem.symbol);
          const row = document.querySelector<HTMLElement>(
            `[data-market-instrument-row="${prevItem.symbol}"]`,
          );
          if (typeof row?.scrollIntoView === 'function') {
            row.scrollIntoView({ block: 'nearest', inline: 'nearest' });
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [items, activeSymbol, onSelect]);
}

interface WatchlistCategoryFilterProps {
  label: string;
  totalCount: number;
  availableAssetClasses: string[];
  assetClassCounts: Record<string, number>;
  activeCategory: string;
  allLabel: string;
  commonCopy: ReturnType<typeof useCopy>['common'];
  onSelectCategory: (category: string) => void;
}

function WatchlistCategoryFilter({
  label,
  totalCount,
  availableAssetClasses,
  assetClassCounts,
  activeCategory,
  allLabel,
  commonCopy,
  onSelectCategory,
}: WatchlistCategoryFilterProps) {
  return (
    <div
      role="group"
      aria-label={label}
      className="app-inline-segmented mx-3 my-2 flex flex-wrap"
      data-testid="market-watchlist-category-filter"
    >
      <button
        type="button"
        aria-pressed={activeCategory === 'all'}
        onClick={() => onSelectCategory('all')}
        className={`app-inline-segmented-btn ${
          activeCategory === 'all' ? 'app-inline-segmented-btn-active' : ''
        }`}
      >
        {allLabel} ({totalCount})
      </button>
      {availableAssetClasses.map((ac) => (
        <button
          key={ac}
          type="button"
          aria-pressed={activeCategory === ac}
          onClick={() => onSelectCategory(ac)}
          className={`app-inline-segmented-btn ${
            activeCategory === ac ? 'app-inline-segmented-btn-active' : ''
          }`}
        >
          {formatAssetClassLabel(ac, commonCopy)} ({assetClassCounts[ac]})
        </button>
      ))}
    </div>
  );
}

interface WatchlistSortHeaderProps {
  sortKey: MarketSortKey;
  sortDirection: SortDirection;
  labels: ReturnType<typeof useCopy>['market'];
  onSortSymbol: () => void;
  onSortPrice: () => void;
  onSortChangePct: () => void;
  onSortChangeAmount: () => void;
  onResetSort: () => void;
}

function WatchlistSortHeader({
  sortKey,
  sortDirection,
  labels,
  onSortSymbol,
  onSortPrice,
  onSortChangePct,
  onSortChangeAmount,
  onResetSort,
}: WatchlistSortHeaderProps) {
  const isChangePctActive = sortKey === 'change_pct' || sortKey === 'change';
  const isChangeAmountActive = sortKey === 'change_amount';

  return (
    <div
      role="row"
      className="flex items-center justify-between border-b border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 px-3 py-1.5 text-xs text-[var(--app-text-tertiary)] select-none overflow-x-auto"
      data-testid="market-watchlist-sort-header"
    >
      <div className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={onSortSymbol}
          className={`group/btn inline-flex items-center gap-1 whitespace-nowrap shrink-0 rounded px-1.5 py-0.5 font-medium transition-all hover:bg-[var(--app-surface-overlay)] active:scale-[0.98] ${
            sortKey === 'symbol'
              ? 'text-[var(--app-accent)] font-semibold'
              : 'hover:text-[var(--app-text)]'
          }`}
          aria-label={`${labels.sortSymbol}: ${
            sortKey === 'symbol'
              ? sortDirection === 'asc'
                ? labels.asc
                : labels.desc
              : labels.sortDefault
          }`}
        >
          <span>{labels.sortSymbol}</span>
          <SortIndicator
            active={sortKey === 'symbol'}
            direction={sortDirection}
          />
        </button>
        {sortKey !== 'default' ? (
          <button
            type="button"
            onClick={onResetSort}
            className="app-type-micro inline-flex items-center gap-1 whitespace-nowrap shrink-0 rounded border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-1.5 py-0.5 text-[var(--app-text-tertiary)] transition-all hover:bg-[var(--app-surface)] hover:text-[var(--app-text)] active:scale-[0.97]"
            title={labels.resetSort}
          >
            <RotateCcw size={10} strokeWidth={2} aria-hidden="true" />
            <span>{labels.resetSort}</span>
          </button>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-1 sm:gap-1.5 text-right">
        <button
          type="button"
          onClick={onSortPrice}
          className={`group/btn inline-flex items-center gap-1 whitespace-nowrap shrink-0 rounded px-1.5 py-0.5 font-medium transition-all hover:bg-[var(--app-surface-overlay)] active:scale-[0.98] ${
            sortKey === 'price'
              ? 'text-[var(--app-accent)] font-semibold'
              : 'hover:text-[var(--app-text)]'
          }`}
          aria-label={`${labels.sortPrice}: ${
            sortKey === 'price'
              ? sortDirection === 'asc'
                ? labels.asc
                : labels.desc
              : labels.sortDefault
          }`}
        >
          <span>{labels.sortPrice}</span>
          <SortIndicator
            active={sortKey === 'price'}
            direction={sortDirection}
          />
        </button>
        <button
          type="button"
          onClick={onSortChangePct}
          className={`group/btn inline-flex items-center gap-1 whitespace-nowrap shrink-0 rounded px-1.5 py-0.5 font-medium transition-all hover:bg-[var(--app-surface-overlay)] active:scale-[0.98] ${
            isChangePctActive
              ? 'text-[var(--app-accent)] font-semibold'
              : 'hover:text-[var(--app-text)]'
          }`}
          aria-label={`${labels.sortChangePct ?? labels.sortChange}: ${
            isChangePctActive
              ? sortDirection === 'asc'
                ? labels.asc
                : labels.desc
              : labels.sortDefault
          }`}
        >
          <span>{labels.sortChangePct ?? labels.sortChange}</span>
          <SortIndicator active={isChangePctActive} direction={sortDirection} />
        </button>
        <button
          type="button"
          onClick={onSortChangeAmount}
          className={`group/btn inline-flex items-center gap-1 whitespace-nowrap shrink-0 rounded px-1.5 py-0.5 font-medium transition-all hover:bg-[var(--app-surface-overlay)] active:scale-[0.98] ${
            isChangeAmountActive
              ? 'text-[var(--app-accent)] font-semibold'
              : 'hover:text-[var(--app-text)]'
          }`}
          aria-label={`${labels.sortChangeAmount}: ${
            isChangeAmountActive
              ? sortDirection === 'asc'
                ? labels.asc
                : labels.desc
              : labels.sortDefault
          }`}
        >
          <span>{labels.sortChangeAmount}</span>
          <SortIndicator
            active={isChangeAmountActive}
            direction={sortDirection}
          />
        </button>
      </div>
    </div>
  );
}

interface WatchlistRowProps {
  item: ResearchBoardItem;
  quote: MarketHealthQuote | null;
  isActive: boolean;
  locale: Locale;
  commonCopy: ReturnType<typeof useCopy>['common'];
  labels: ReturnType<typeof useCopy>['market'];
  onSelect: (symbol: string) => void;
  onRemove: (symbol: string) => Promise<void>;
}

function WatchlistRow({
  item,
  quote,
  isActive,
  locale,
  commonCopy,
  labels,
  onSelect,
  onRemove,
}: WatchlistRowProps) {
  const statusLabel = quote?.quote_status
    ? formatPublicStatus(quote.quote_status, locale)
    : labels.unknown;
  const statusId = `market-instrument-state-${encodeURIComponent(item.symbol)}`;
  const ageLabel = formatAge(quote?.quote_age_seconds, locale);
  const researchCountLabel = formatResearchCount(item.research_count, locale);
  const dailyMove = quote?.daily_change ?? null;
  const dailyPct = resolveDailyChangePct(quote, item.price);

  const handleRowClick = () => {
    onSelect(item.symbol);
    if (
      typeof window === 'undefined' ||
      !window.matchMedia('(max-width: 1279px)').matches
    ) {
      return;
    }
    window.requestAnimationFrame(() => {
      document.getElementById('market-instrument-detail')?.scrollIntoView({
        block: 'start',
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'auto'
          : 'smooth',
      });
    });
  };

  return (
    <li
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
        onClick={handleRowClick}
      >
        <span className="min-w-0">
          <span
            className="block whitespace-normal text-sm leading-5 font-semibold text-[var(--app-text)] [overflow-wrap:anywhere]"
            data-testid={`market-instrument-name-${item.symbol}`}
          >
            {item.name || item.symbol}
          </span>
          <span className="app-type-micro mt-0.5 flex flex-wrap items-center gap-1.5 truncate font-mono tabular-nums text-[var(--app-text-tertiary)]">
            <span>{item.symbol}</span>
            <span aria-hidden="true">·</span>
            <span>{formatAssetClassLabel(item.asset_class, commonCopy)}</span>
            {item.is_holding ? (
              <span
                data-testid={`market-instrument-holding-badge-${item.symbol}`}
                className="app-type-micro rounded px-1 py-0.2 font-sans font-medium bg-[color-mix(in_srgb,var(--app-accent)_15%,transparent)] text-[var(--app-accent)] border border-[color-mix(in_srgb,var(--app-accent)_30%,transparent)]"
              >
                {labels.holdingBadge}
              </span>
            ) : null}
          </span>
          <span
            className="app-type-micro mt-1 grid gap-0.5 leading-4 text-[var(--app-text-tertiary)]"
            data-testid={`market-instrument-status-${item.symbol}`}
            id={statusId}
          >
            <span className="block break-words">
              {statusLabel} · {ageLabel}
            </span>
            <span className="block break-words">{researchCountLabel}</span>
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
            className={`app-type-micro mt-0.5 block font-semibold tabular-nums ${moveTone(dailyPct ?? dailyMove)}`}
            data-testid={`market-instrument-change-${item.symbol}`}
          >
            {dailyPct != null
              ? `${dailyPct > 0 ? '+' : ''}${dailyPct.toFixed(2)}%`
              : dailyMove != null
                ? formatCurrency(dailyMove)
                : '--'}
          </span>
          {dailyMove != null && dailyPct != null ? (
            <span className="app-type-micro block font-mono tabular-nums text-[var(--app-text-tertiary)]">
              {dailyMove > 0 ? '+' : ''}
              {formatCurrency(dailyMove)}
            </span>
          ) : null}
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
}

export type MarketWatchlistSidebarProps = {
  items: ResearchBoardItem[];
  healthBySymbol: Map<string, MarketHealthQuote>;
  activeSymbol: string;
  watchlistEditor?: ReactNode;
  onSelect: (symbol: string) => void;
  onRemove: (symbol: string) => Promise<void>;
};

export function MarketWatchlistSidebar({
  items,
  healthBySymbol,
  activeSymbol,
  watchlistEditor,
  onSelect,
  onRemove,
}: MarketWatchlistSidebarProps) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.market;

  const [selectedAssetClass, setSelectedAssetClass] = useState<string>('all');
  const [sortKey, setSortKey] = useState<MarketSortKey>('default');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  const assetClassCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of items) {
      const ac = (item.asset_class || 'unknown').trim().toLowerCase();
      counts[ac] = (counts[ac] ?? 0) + 1;
    }
    return counts;
  }, [items]);

  const availableAssetClasses = useMemo(() => {
    const classes = Object.keys(assetClassCounts);
    const preferredOrder = ['stock', 'fund', 'etf', 'bond', 'gold', 'cash'];
    return classes.sort((a, b) => {
      const idxA = preferredOrder.indexOf(a);
      const idxB = preferredOrder.indexOf(b);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return a.localeCompare(b);
    });
  }, [assetClassCounts]);

  const activeCategory =
    selectedAssetClass === 'all' ||
    availableAssetClasses.includes(selectedAssetClass)
      ? selectedAssetClass
      : 'all';

  const filteredItems = useMemo(() => {
    if (activeCategory === 'all') {
      return items;
    }
    return items.filter(
      (item) =>
        (item.asset_class || 'unknown').trim().toLowerCase() === activeCategory,
    );
  }, [items, activeCategory]);

  const sortedItems = useMemo(() => {
    if (sortKey === 'default') {
      return filteredItems;
    }
    return [...filteredItems].sort((left, right) => {
      if (sortKey === 'change_pct' || sortKey === 'change') {
        const quoteLeft = healthBySymbol.get(left.symbol);
        const quoteRight = healthBySymbol.get(right.symbol);
        const pctLeft = resolveDailyChangePct(quoteLeft, left.price);
        const pctRight = resolveDailyChangePct(quoteRight, right.price);

        const leftMissing = pctLeft === null;
        const rightMissing = pctRight === null;
        if (leftMissing && rightMissing) {
          const moveLeft = quoteLeft?.daily_change;
          const moveRight = quoteRight?.daily_change;
          const mLeftMissing = moveLeft == null || !Number.isFinite(moveLeft);
          const mRightMissing =
            moveRight == null || !Number.isFinite(moveRight);
          if (mLeftMissing && mRightMissing)
            return left.symbol.localeCompare(right.symbol);
          if (mLeftMissing) return 1;
          if (mRightMissing) return -1;
          return sortDirection === 'desc'
            ? moveRight! - moveLeft!
            : moveLeft! - moveRight!;
        }
        if (leftMissing) return 1;
        if (rightMissing) return -1;
        if (pctRight !== pctLeft) {
          return sortDirection === 'desc'
            ? pctRight! - pctLeft!
            : pctLeft! - pctRight!;
        }
        return left.symbol.localeCompare(right.symbol);
      }

      if (sortKey === 'change_amount') {
        const quoteLeft = healthBySymbol.get(left.symbol);
        const quoteRight = healthBySymbol.get(right.symbol);
        const moveLeft = quoteLeft?.daily_change ?? quoteLeft?.change;
        const moveRight = quoteRight?.daily_change ?? quoteRight?.change;

        const leftMissing = moveLeft == null || !Number.isFinite(moveLeft);
        const rightMissing = moveRight == null || !Number.isFinite(moveRight);
        if (leftMissing && rightMissing)
          return left.symbol.localeCompare(right.symbol);
        if (leftMissing) return 1;
        if (rightMissing) return -1;
        if (moveRight !== moveLeft) {
          return sortDirection === 'desc'
            ? moveRight! - moveLeft!
            : moveLeft! - moveRight!;
        }
        return left.symbol.localeCompare(right.symbol);
      }

      if (sortKey === 'price') {
        const priceLeft = left.price ?? healthBySymbol.get(left.symbol)?.price;
        const priceRight =
          right.price ?? healthBySymbol.get(right.symbol)?.price;

        const leftMissing = priceLeft == null || !Number.isFinite(priceLeft);
        const rightMissing = priceRight == null || !Number.isFinite(priceRight);
        if (leftMissing && rightMissing)
          return left.symbol.localeCompare(right.symbol);
        if (leftMissing) return 1;
        if (rightMissing) return -1;
        if (priceRight !== priceLeft) {
          return sortDirection === 'desc'
            ? priceRight! - priceLeft!
            : priceLeft! - priceRight!;
        }
        return left.symbol.localeCompare(right.symbol);
      }

      if (sortKey === 'symbol') {
        const cmp = left.symbol.localeCompare(right.symbol);
        return sortDirection === 'asc' ? cmp : -cmp;
      }

      return 0;
    });
  }, [filteredItems, sortKey, sortDirection, healthBySymbol]);

  const toggleSort = (
    key: MarketSortKey,
    initialDir: SortDirection = 'desc',
  ) => {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDirection(initialDir);
    } else if (sortDirection === initialDir) {
      setSortDirection(initialDir === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey('default');
    }
  };

  useWatchlistKeyboardNavigation({
    items: sortedItems,
    activeSymbol,
    onSelect,
  });

  return (
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
        <div className="flex shrink-0 items-center gap-1.5">
          <span
            className="app-type-micro hidden items-center gap-0.5 rounded border border-[var(--app-divider)] px-1.5 py-0.5 font-mono text-[var(--app-text-tertiary)] md:inline-flex"
            title="↑ / ↓ / j / k"
          >
            <span>↑↓</span>
          </span>
          <span className="text-xs tabular-nums text-[var(--app-text-secondary)]">
            {sortedItems.length === items.length
              ? items.length
              : `${sortedItems.length}/${items.length}`}
          </span>
        </div>
      </div>

      {watchlistEditor}

      {items.length > 0 && availableAssetClasses.length > 1 ? (
        <WatchlistCategoryFilter
          label={labels.assetClass}
          totalCount={items.length}
          availableAssetClasses={availableAssetClasses}
          assetClassCounts={assetClassCounts}
          activeCategory={activeCategory}
          allLabel={labels.allAssetClasses}
          commonCopy={copy.common}
          onSelectCategory={setSelectedAssetClass}
        />
      ) : null}

      {items.length > 0 ? (
        <WatchlistSortHeader
          sortKey={sortKey}
          sortDirection={sortDirection}
          labels={labels}
          onSortSymbol={() => toggleSort('symbol', 'asc')}
          onSortPrice={() => toggleSort('price', 'desc')}
          onSortChangePct={() => toggleSort('change_pct', 'desc')}
          onSortChangeAmount={() => toggleSort('change_amount', 'desc')}
          onResetSort={() => setSortKey('default')}
        />
      ) : null}

      {sortedItems.length > 0 ? (
        <ul
          aria-label={labels.watchlist}
          className="grid min-w-0 auto-cols-[minmax(15rem,85%)] snap-x snap-mandatory grid-flow-col divide-x divide-[var(--app-divider)] overflow-x-auto overscroll-x-contain scroll-px-3 sm:auto-cols-[minmax(15rem,48%)] md:block md:max-h-[calc(100dvh-39rem)] md:snap-none md:divide-x-0 md:divide-y md:overflow-x-visible md:overflow-y-auto md:overscroll-y-contain lg:max-h-[min(62vh,42rem)]"
          data-mobile-layout="horizontal-rail"
          data-testid="market-instrument-list"
        >
          {sortedItems.map((item) => (
            <WatchlistRow
              key={item.symbol}
              item={item}
              quote={healthBySymbol.get(item.symbol) ?? null}
              isActive={item.symbol === activeSymbol}
              locale={locale}
              commonCopy={copy.common}
              labels={labels}
              onSelect={onSelect}
              onRemove={onRemove}
            />
          ))}
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
  );
}
