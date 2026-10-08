import type { AllocationItem, Position } from './api';
import type {
  EvidenceFilter,
  PositionSort,
  QuoteFilter,
} from './components/workspace-toolbar';

export function quoteNeedsReview(status: string | null | undefined) {
  return !['live', 'confirmed', 'cache'].includes(status ?? 'unknown');
}

function sortValue(
  position: Position,
  sortBy: Exclude<PositionSort, 'default'>,
  allocationBySymbol: Map<string, AllocationItem>,
) {
  if (sortBy === 'weight') {
    return (
      allocationBySymbol.get(position.symbol)?.weight ??
      Number.NEGATIVE_INFINITY
    );
  }
  if (sortBy === 'today_change_pct') {
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
        return (position.today_change / priorValue) * 100;
      }
    }
    if (
      position.latest_price != null &&
      position.baseline_price != null &&
      position.baseline_price > 0
    ) {
      return (
        ((position.latest_price - position.baseline_price) /
          position.baseline_price) *
        100
      );
    }
    return Number.NEGATIVE_INFINITY;
  }
  if (sortBy === 'unrealized_pnl_pct') {
    const pnl = position.unrealized_pnl ?? position.indicative_unrealized_pnl;
    if (typeof pnl !== 'number' || !Number.isFinite(pnl)) {
      return Number.NEGATIVE_INFINITY;
    }
    const costBasis =
      position.quantity > 0 && position.avg_cost > 0
        ? position.quantity * position.avg_cost
        : position.market_value != null &&
            Number.isFinite(position.market_value)
          ? position.market_value - pnl
          : null;
    if (costBasis != null && costBasis > 0) {
      return (pnl / costBasis) * 100;
    }
    return Number.NEGATIVE_INFINITY;
  }
  if (sortBy === 'symbol') {
    return 0;
  }
  const value = position[sortBy];
  return typeof value === 'number' && Number.isFinite(value)
    ? value
    : Number.NEGATIVE_INFINITY;
}

export function filterAndSortPortfolioPositions({
  positions,
  allocation,
  search,
  assetClassFilter,
  pnlFilter,
  quoteFilter,
  evidenceFilter,
  evidenceReviewSymbols,
  sortBy,
  sortDirection = sortBy === 'symbol' ? 'asc' : 'desc',
}: {
  positions: Position[];
  allocation: AllocationItem[];
  search: string;
  assetClassFilter: string;
  pnlFilter: 'all' | 'winners' | 'losers';
  quoteFilter: QuoteFilter;
  evidenceFilter: EvidenceFilter;
  evidenceReviewSymbols: Set<string>;
  sortBy: PositionSort;
  sortDirection?: 'asc' | 'desc';
}) {
  const allocationBySymbol = new Map(
    allocation.map((item) => [item.symbol, item]),
  );
  const normalizedSearch = search.trim().toLowerCase();
  // Cancelling an explicit sort restores the page's original market-value order.
  const effectiveSortBy = sortBy === 'default' ? 'market_value' : sortBy;
  const effectiveDirection = sortBy === 'default' ? 'desc' : sortDirection;

  return positions
    .filter((position) => {
      const assetClass =
        position.asset_class ??
        allocationBySymbol.get(position.symbol)?.asset_class ??
        'unknown';
      const matchesSearch =
        normalizedSearch.length === 0 ||
        position.symbol.toLowerCase().includes(normalizedSearch) ||
        (position.display_name ?? position.name ?? '')
          .toLowerCase()
          .includes(normalizedSearch);
      const matchesAssetClass =
        assetClassFilter === 'all' || assetClass === assetClassFilter;
      const matchesPnl =
        pnlFilter === 'all' ||
        (typeof position.unrealized_pnl === 'number' &&
          ((pnlFilter === 'winners' && position.unrealized_pnl >= 0) ||
            (pnlFilter === 'losers' && position.unrealized_pnl < 0)));
      const needsQuoteReview = quoteNeedsReview(position.quote_status);
      const matchesQuote =
        quoteFilter === 'all' ||
        (quoteFilter === 'healthy' && !needsQuoteReview) ||
        (quoteFilter === 'review' && needsQuoteReview);
      const needsEvidenceReview = evidenceReviewSymbols.has(position.symbol);
      const matchesEvidence =
        evidenceFilter === 'all' ||
        (evidenceFilter === 'review' && needsEvidenceReview) ||
        (evidenceFilter === 'clear' && !needsEvidenceReview);
      return (
        matchesSearch &&
        matchesAssetClass &&
        matchesPnl &&
        matchesQuote &&
        matchesEvidence
      );
    })
    .sort((left, right) => {
      if (effectiveSortBy === 'symbol') {
        const comparison = left.symbol.localeCompare(right.symbol);
        return effectiveDirection === 'asc' ? comparison : -comparison;
      }
      const leftValue = sortValue(left, effectiveSortBy, allocationBySymbol);
      const rightValue = sortValue(right, effectiveSortBy, allocationBySymbol);
      if (
        leftValue === rightValue ||
        (!Number.isFinite(leftValue) && !Number.isFinite(rightValue))
      ) {
        return left.symbol.localeCompare(right.symbol);
      }
      if (!Number.isFinite(leftValue)) return 1;
      if (!Number.isFinite(rightValue)) return -1;
      const comparison = leftValue - rightValue;
      return effectiveDirection === 'asc' ? comparison : -comparison;
    });
}
