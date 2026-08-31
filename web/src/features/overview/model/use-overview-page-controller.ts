import { useMemo, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useAccountOverviewQuery,
  useAccountStrategyContributionQuery,
  useCurrentHoldingMarketEvidenceReviewQuery,
  useDailyTradingPlanQuery,
  useEquityCurveSeriesQuery,
  useExplainabilityQuery,
  useLedgerEntriesQuery,
  useMarketCalendarQuery,
  useMarketDataHealthQuery,
  useOperationsTodayQuery,
  usePendingManualOrdersQuery,
  usePortfolioSnapshotQuery,
  useTodayDecisionQuery,
  type EquityCurveRange,
} from '../overview-feature-boundary';
import {
  formatShanghaiDateKey,
  isTradingDayForOverviewPnl,
  type OverviewAnalysisView,
} from './overview-page-model';

export type OverviewWorkspaceQueries = {
  overview: ReturnType<typeof useAccountOverviewQuery>;
  snapshot: ReturnType<typeof usePortfolioSnapshotQuery>;
  equityCurve: ReturnType<typeof useEquityCurveSeriesQuery>;
  explainability: ReturnType<typeof useExplainabilityQuery>;
  ledgerEntries: ReturnType<typeof useLedgerEntriesQuery>;
  pendingOrders: ReturnType<typeof usePendingManualOrdersQuery>;
  marketHealth: ReturnType<typeof useMarketDataHealthQuery>;
  holdingMarketEvidenceReview: ReturnType<
    typeof useCurrentHoldingMarketEvidenceReviewQuery
  >;
  strategyContribution: ReturnType<typeof useAccountStrategyContributionQuery>;
  todayDecision: ReturnType<typeof useTodayDecisionQuery>;
  tradingPlan: ReturnType<typeof useDailyTradingPlanQuery>;
  operationsToday: ReturnType<typeof useOperationsTodayQuery>;
  marketCalendar: ReturnType<typeof useMarketCalendarQuery>;
};

export function useOverviewPageController() {
  const copy = useCopy();
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('all');
  const [analysisView, setAnalysisView] =
    useState<OverviewAnalysisView>('performance');
  const snapshot = usePortfolioSnapshotQuery();
  const overview = useAccountOverviewQuery();
  const secondaryQueriesEnabled = Boolean(overview.data && snapshot.data);
  const calendarAnalysisEnabled =
    secondaryQueriesEnabled && analysisView === 'calendar';
  const equityCurve = useEquityCurveSeriesQuery(
    equityCurveRange,
    secondaryQueriesEnabled,
  );
  const explainability = useExplainabilityQuery(
    undefined,
    calendarAnalysisEnabled,
  );
  const ledgerEntries = useLedgerEntriesQuery(8, secondaryQueriesEnabled);
  const pendingOrders = usePendingManualOrdersQuery(secondaryQueriesEnabled);
  const marketHealth = useMarketDataHealthQuery(secondaryQueriesEnabled);
  const holdingMarketEvidenceReview =
    useCurrentHoldingMarketEvidenceReviewQuery(secondaryQueriesEnabled);
  const strategyContribution = useAccountStrategyContributionQuery(
    secondaryQueriesEnabled,
  );
  const todayDecision = useTodayDecisionQuery(secondaryQueriesEnabled);
  const tradingPlan = useDailyTradingPlanQuery(secondaryQueriesEnabled);
  const operationsToday = useOperationsTodayQuery(secondaryQueriesEnabled);
  const positions = useMemo(
    () => snapshot.data?.positions ?? [],
    [snapshot.data],
  );
  const assetClassBySymbol = useMemo(
    () =>
      Object.fromEntries(
        positions.map((position) => [
          position.symbol,
          position.asset_class ??
            snapshot.data?.allocation.find(
              (item) => item.symbol === position.symbol,
            )?.asset_class ??
            '--',
        ]),
      ),
    [positions, snapshot.data],
  );
  const marketCalendarYear = useMemo(() => {
    const years = Array.from(
      new Set(
        (explainability.data?.timeline ?? [])
          .map((row) => row.date?.slice(0, 4))
          .filter((year): year is string => /^\d{4}$/.test(year ?? '')),
      ),
    ).sort();
    return years[years.length - 1] ?? null;
  }, [explainability.data]);
  const marketCalendar = useMarketCalendarQuery(marketCalendarYear);
  const currentShanghaiDate = useMemo(
    () => formatShanghaiDateKey(new Date()),
    [],
  );
  const isCurrentMarketTradingDay = useMemo(
    () => isTradingDayForOverviewPnl(marketCalendar.data, currentShanghaiDate),
    [currentShanghaiDate, marketCalendar.data],
  );
  const todayPnlLabel = isCurrentMarketTradingDay
    ? copy.overview.cards.todayPnl
    : copy.overview.cards.latestTradingDayPnl;
  const todayPnlContext = isCurrentMarketTradingDay
    ? null
    : copy.overview.cards.marketClosedPnlContext;
  const hasOverviewProjection = overview.data !== undefined;
  const hasPortfolioProjection = snapshot.data !== undefined;
  const hasAnyPrimaryProjection =
    hasOverviewProjection || hasPortfolioProjection;
  const isInitialOverviewLoad =
    !hasAnyPrimaryProjection && (overview.isLoading || snapshot.isLoading);
  const isInitialOverviewError =
    !hasAnyPrimaryProjection && (overview.isError || snapshot.isError);
  const queries: OverviewWorkspaceQueries = {
    overview,
    snapshot,
    equityCurve,
    explainability,
    ledgerEntries,
    pendingOrders,
    marketHealth,
    holdingMarketEvidenceReview,
    strategyContribution,
    todayDecision,
    tradingPlan,
    operationsToday,
    marketCalendar,
  };
  return {
    copy,
    queries,
    positions,
    assetClassBySymbol,
    todayPnlLabel,
    todayPnlContext,
    hasAnyPrimaryProjection,
    isInitialOverviewLoad,
    isInitialOverviewError,
    analysisView,
    setAnalysisView,
    equityCurveRange,
    setEquityCurveRange,
  };
}
