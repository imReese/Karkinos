import type { AllocationItem, Position } from './api';
import type {
  EvidenceFilter,
  PositionSort,
  QuoteFilter,
} from './components/workspace-toolbar';

function quoteNeedsReview(status: string | null | undefined) {
  return !['live', 'confirmed', 'cache'].includes(status ?? 'unknown');
}

function sortValue(
  position: Position,
  sortBy: PositionSort,
  allocationBySymbol: Map<string, AllocationItem>,
) {
  if (sortBy === 'weight') {
    return (
      allocationBySymbol.get(position.symbol)?.weight ??
      Number.NEGATIVE_INFINITY
    );
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
}) {
  const allocationBySymbol = new Map(
    allocation.map((item) => [item.symbol, item]),
  );
  const normalizedSearch = search.trim().toLowerCase();

  return positions
    .filter((position) => {
      const assetClass =
        allocationBySymbol.get(position.symbol)?.asset_class ?? 'unknown';
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
        (pnlFilter === 'winners' && position.unrealized_pnl >= 0) ||
        (pnlFilter === 'losers' && position.unrealized_pnl < 0);
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
    .sort(
      (left, right) =>
        sortValue(right, sortBy, allocationBySymbol) -
          sortValue(left, sortBy, allocationBySymbol) ||
        left.symbol.localeCompare(right.symbol),
    );
}
