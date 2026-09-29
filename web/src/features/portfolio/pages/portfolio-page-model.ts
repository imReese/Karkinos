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
  const assetClasses = Array.from(
    new Set(allocation.map((item) => item.asset_class)),
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
  });
  const assetClassBySymbol = Object.fromEntries(
    allocation.map((item) => [item.symbol, item.asset_class]),
  );
  const weightBySymbol = Object.fromEntries(
    allocation.map((item) => [item.symbol, item.weight]),
  );

  const totalMarketValue = portfolioPositions.reduce(
    (sum, p) =>
      sum +
      (p.market_value != null && Number.isFinite(p.market_value)
        ? p.market_value
        : 0),
    0,
  );
  const totalTodayChange = portfolioPositions.reduce(
    (sum, p) =>
      sum +
      (p.today_change != null && Number.isFinite(p.today_change)
        ? p.today_change
        : 0),
    0,
  );
  const priorTotalValue = totalMarketValue - totalTodayChange;
  const totalTodayChangePct =
    priorTotalValue > 0 ? totalTodayChange / priorTotalValue : null;
  const totalUnrealizedPnl = portfolioPositions.reduce(
    (sum, p) =>
      sum +
      (p.unrealized_pnl != null && Number.isFinite(p.unrealized_pnl)
        ? p.unrealized_pnl
        : 0),
    0,
  );
  const totalCostBasis = portfolioPositions.reduce((sum, p) => {
    if (p.quantity > 0 && p.avg_cost > 0) return sum + p.quantity * p.avg_cost;
    if (p.market_value != null && p.unrealized_pnl != null) {
      return sum + (p.market_value - p.unrealized_pnl);
    }
    return sum;
  }, 0);
  const totalUnrealizedPnlPct =
    totalCostBasis > 0 ? totalUnrealizedPnl / totalCostBasis : null;

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
    totalTodayChangePct,
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
  onSortByChange: (value: PositionSort) => void;
};
