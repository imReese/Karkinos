import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatTimestamp } from '../../../shared/format';
import type {
  useAccountStrategyContributionQuery,
  useDailyTradingPlanQuery,
} from '../portfolio-feature-boundary';
import type {
  useLiveHoldingsQuery,
  usePortfolioCockpitQuery,
  usePortfolioSnapshotQuery,
} from '../api';
import type {
  EvidenceFilter,
  PositionSort,
  QuoteFilter,
} from '../components/workspace-toolbar';
import {
  filterAndSortPortfolioPositions,
  quoteNeedsReview,
} from '../position-observation';

export type PortfolioMode = 'account' | 'strategy';

export type PortfolioPageState = {
  mode: PortfolioMode;
  quoteFilter: QuoteFilter;
  evidenceFilter: EvidenceFilter;
  sortBy: PositionSort;
  sortDirection: 'asc' | 'desc';
};

export type PortfolioPageModelSource = {
  copy: ReturnType<typeof useCopy>;
  locale: Locale;
  search: string;
  assetClassFilter: string;
  pnlFilter: 'all' | 'winners' | 'losers';
  state: PortfolioPageState;
  snapshot: ReturnType<typeof usePortfolioSnapshotQuery>;
  cockpit: ReturnType<typeof usePortfolioCockpitQuery>;
  liveHoldings: ReturnType<typeof useLiveHoldingsQuery>;
  strategyContribution: ReturnType<typeof useAccountStrategyContributionQuery>;
  tradingPlan?: ReturnType<typeof useDailyTradingPlanQuery>;
};

export function buildPortfolioPageModel(source: PortfolioPageModelSource) {
  const { copy, snapshot, state } = source;
  const portfolioPositions = snapshot.data?.positions ?? [];
  const primaryPortfolioQueriesSettled = snapshot.data !== undefined;
  const allocation = snapshot.data?.allocation ?? [];
  const evidenceReviewItems = snapshot.data?.position_review_items ?? [];
  const evidenceReviewSymbols = new Set(
    evidenceReviewItems.map((item) => item.position.symbol),
  );
  const assetClassBySymbol = Object.fromEntries([
    ...allocation.map((item) => [item.symbol, item.asset_class]),
    ...portfolioPositions
      .filter((position) => position.asset_class != null)
      .map((position) => [position.symbol, position.asset_class]),
  ]);
  const assetClasses = Array.from(
    new Set(
      portfolioPositions.map(
        (position) => assetClassBySymbol[position.symbol] ?? 'unknown',
      ),
    ),
  );
  const filteredPositions = filterAndSortPortfolioPositions({
    positions: portfolioPositions,
    allocation,
    search: source.search,
    assetClassFilter: source.assetClassFilter,
    pnlFilter: source.pnlFilter,
    quoteFilter: state.quoteFilter,
    evidenceFilter: state.evidenceFilter,
    evidenceReviewSymbols,
    sortBy: state.sortBy,
    sortDirection: state.sortDirection,
  });
  const weightBySymbol = Object.fromEntries(
    allocation.map((item) => [item.symbol, item.weight]),
  );

  const totalMarketValue = snapshot.data?.total_market_value ?? null;
  const totalTodayChange = snapshot.data?.total_today_change ?? null;
  const totalUnrealizedPnl = snapshot.data?.total_unrealized_pnl ?? null;
  const totalUnrealizedPnlPct = snapshot.data?.total_unrealized_pnl_pct ?? null;

  return {
    source,
    portfolioPositions,
    primaryPortfolioQueriesSettled,
    evidenceReviewItems,
    assetClasses,
    filteredPositions,
    assetClassBySymbol,
    weightBySymbol,
    totalMarketValue,
    totalTodayChange,
    totalUnrealizedPnl,
    totalUnrealizedPnlPct,
    hasQuotesNeedingReview: portfolioPositions.some((position) =>
      quoteNeedsReview(position.quote_status),
    ),
    closedPositions: snapshot.data?.closed_positions ?? [],
    portfolioIdentity: snapshot.data
      ? `${copy.common.valuationAsOf} ${formatTimestamp(
          snapshot.data.valuation_as_of,
        )}`
      : undefined,
    isInitialPortfolioLoad: !snapshot.data && snapshot.isLoading,
    portfolioPrimaryFailureDetail: copy.portfolio.summary.errorDetail,
    tradingPlan: source.tradingPlan?.data ?? null,
  };
}

export type PortfolioPageModel = ReturnType<typeof buildPortfolioPageModel>;

export type PortfolioPageActions = {
  onClearFilters: () => void;
  onAssetClassFilterChange: (value: string) => void;
  onEvidenceFilterChange: (value: EvidenceFilter) => void;
  onModeChange: (value: PortfolioMode) => void;
  onOpenPosition: (symbol: string) => void;
  onPnlFilterChange: (value: 'all' | 'winners' | 'losers') => void;
  onQuoteFilterChange: (value: QuoteFilter) => void;
  onRetryCockpit: () => void;
  onRetryLiveHoldings: () => void;
  onRetrySnapshot: () => void;
  onRetryStrategyContribution: () => void;
  onSearchChange: (value: string) => void;
  onSortByChange: (value: PositionSort, direction?: 'asc' | 'desc') => void;
};
