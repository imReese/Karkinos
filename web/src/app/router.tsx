import { useMemo, useState } from 'react';
import {
  createRoute,
  createRootRoute,
  createRouter,
  Outlet,
  useNavigate,
  useRouterState,
} from '@tanstack/react-router';
import { ChevronDown } from 'lucide-react';

import { useCopy, type AppCopy } from './copy';
import {
  EvidenceState,
  ExceptionList,
  MetricStrip,
  WorkspaceHeader,
  type ExceptionItem,
} from './components/workbench';
import { AppShell } from './layout/app-shell';
import { usePreferences, type Locale } from './preferences';
import {
  type AccountOverview,
  useAccountOverviewQuery,
  type EquityCurveRange,
  useExplainabilityQuery,
  useEquityCurveSeriesQuery,
} from '../features/account/api';
import {
  EquityCurveCard,
  EquityCurveSkeleton,
} from '../features/account/components/equity-curve-card';
import type { QuoteDiagnosticItem } from '../features/account/components/dashboard-quick-actions';
import { ReturnCalendarCard } from '../features/account/components/return-calendar-card';
import {
  useAccountStrategyContributionQuery,
  type AccountStrategyContributionReport,
} from '../features/account-strategy/api';
import { StrategyContributionGateCard } from '../features/account-strategy/components/strategy-contribution-gate-card';
import { AccountTruthReviewPage } from '../features/account-truth/components/account-truth-review-page';
import { AiResearchPage } from '../features/ai-research/components/ai-research-page';
import { BacktestPage } from '../features/backtest/components/backtest-page';
import {
  type DailyTradingPlanResponse,
  useTodayDecisionQuery,
  useDailyTradingPlanQuery,
  type DecisionCandidate,
  type DecisionResponse,
} from '../features/decision/api';
import { DecisionCockpitPage } from '../features/decision/components/decision-cockpit-page';
import {
  useOperationsTodayQuery,
  type OperationsTodayResponse,
} from '../features/operations/api';
import { OperationsPage } from '../features/operations/components/operations-page';
import {
  operationsAttentionResolutionLabel,
  operationsNextActionLabel,
  operationsTargetHref,
} from '../features/operations/presentation';
import {
  OverviewCards,
  OverviewSnapshotFallbackCards,
} from '../features/account/components/overview-cards';
import { PortfolioExposureSummary } from '../features/account/components/portfolio-exposure-summary';
import { TradingPage } from '../features/trading/components/trading-page';
import { PublicHomePage } from '../features/home/components/public-home-page';
import {
  usePendingManualOrdersQuery,
  type ManualOrder,
} from '../features/trading/api';
import { explainMarketCalendarDate } from '../shared/market-calendar';
import {
  useLedgerEntriesQuery,
  type LedgerEntry,
} from '../features/activity/api';
import {
  formatLedgerDashboardPresentation,
  formatLedgerOrderSideLabel,
} from '../shared/ledger-format';
import {
  type CurrentHoldingMarketEvidenceReview,
  type PortfolioSnapshot,
  useCurrentHoldingMarketEvidenceReviewQuery,
  usePortfolioSnapshotQuery,
} from '../features/portfolio/api';
import { HoldingDetailPage } from '../features/portfolio/components/holding-detail-page';
import { PositionsTable } from '../features/portfolio/components/positions-table';
import {
  useMarketCalendarQuery,
  useMarketDataHealthQuery,
  type MarketCalendarSnapshot,
  type MarketDataHealthResponse,
  type MarketHealthQuote,
} from '../features/market/api';
import { MarketRefreshButton } from '../features/market/components/market-refresh-button';
import { SettingsPage } from '../features/settings/components/settings-page';
import {
  formatCurrency as formatCurrencyValue,
  formatPercent as formatPercentValue,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../shared/format';
import { formatAssetClassLabel } from '../shared/asset-class';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../shared/public-labels';
import { getErrorMessage } from '../shared/error-message';
import { formatInstrumentDisplayLabelFromNameMap } from '../shared/instrument-display';

function RootLayout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });

  if (pathname === '/') {
    return <Outlet />;
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

const rootRoute = createRootRoute({
  component: RootLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: PublicHomePage,
});

const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/overview',
  component: OverviewPage,
});

const portfolioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/portfolio',
  validateSearch: (search: Record<string, unknown>) => ({
    assetClass:
      typeof search.assetClass === 'string' && search.assetClass.length > 0
        ? search.assetClass
        : 'all',
    pnl:
      search.pnl === 'winners' ||
      search.pnl === 'losers' ||
      search.pnl === 'all'
        ? search.pnl
        : 'all',
    q: typeof search.q === 'string' ? search.q : '',
  }),
}).lazy(() =>
  import('../features/portfolio/pages/portfolio-page').then(
    (module) => module.Route,
  ),
);

const holdingDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/portfolio/$symbol',
  component: HoldingDetailRoutePage,
});

const activityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/activity',
}).lazy(() =>
  import('../features/activity/pages/activity-page').then(
    (module) => module.Route,
  ),
);

const riskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/risk',
}).lazy(() =>
  import('../features/risk/pages/risk-page').then((module) => module.Route),
);

const accountTruthRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/account-truth',
  component: AccountTruthReviewPage,
});

const decisionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/decision',
  component: DecisionCockpitPage,
});

const operationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/operations',
  component: OperationsPage,
});

const marketRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/market',
}).lazy(() =>
  import('../features/market/pages/market-page').then((module) => module.Route),
);

const tradingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/trading',
  component: TradingPage,
});

const backtestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/backtest',
  component: BacktestPage,
});

const aiResearchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ai-research',
  component: AiResearchPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  overviewRoute,
  portfolioRoute,
  holdingDetailRoute,
  activityRoute,
  riskRoute,
  accountTruthRoute,
  decisionRoute,
  operationsRoute,
  marketRoute,
  tradingRoute,
  backtestRoute,
  aiResearchRoute,
  settingsRoute,
]);

export const router = createRouter({ routeTree });

function HoldingDetailRoutePage() {
  const { symbol } = holdingDetailRoute.useParams();
  return <HoldingDetailPage symbol={symbol} />;
}

function formatShanghaiDateKey(value: Date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).formatToParts(value);
  const byType = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${byType.year ?? '0000'}-${byType.month ?? '00'}-${byType.day ?? '00'}`;
}

function isTradingDayForOverviewPnl(
  calendar: Pick<MarketCalendarSnapshot, 'days'> | null | undefined,
  dateText: string,
) {
  const calendarDay = calendar?.days.find((day) => day.date === dateText);
  if (calendarDay) {
    return calendarDay.is_trading_day;
  }
  return explainMarketCalendarDate(dateText).isTradingDay;
}

export function OverviewPage() {
  const copy = useCopy();
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('all');
  const [analysisView, setAnalysisView] = useState<
    'performance' | 'allocation' | 'attribution' | 'calendar'
  >('performance');
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
  const assetClassBySymbol = useMemo(
    () =>
      Object.fromEntries(
        (snapshot.data?.positions ?? []).map((position) => [
          position.symbol,
          position.asset_class ??
            snapshot.data?.allocation.find(
              (item) => item.symbol === position.symbol,
            )?.asset_class ??
            '--',
        ]),
      ),
    [snapshot.data],
  );
  const positions = useMemo(
    () => snapshot.data?.positions ?? [],
    [snapshot.data],
  );
  const hasOverviewProjection = overview.data !== undefined;
  const hasPortfolioProjection = snapshot.data !== undefined;
  const hasAnyPrimaryProjection =
    hasOverviewProjection || hasPortfolioProjection;
  const isInitialOverviewLoad =
    !hasAnyPrimaryProjection && (overview.isLoading || snapshot.isLoading);
  const isInitialOverviewError =
    !hasAnyPrimaryProjection && (overview.isError || snapshot.isError);
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
  const analysisTabs = [
    {
      id: 'performance' as const,
      label: copy.overview.dashboard.equityPanel,
    },
    { id: 'allocation' as const, label: copy.portfolio.allocation.title },
    {
      id: 'attribution' as const,
      label: copy.backtest.page.accountStrategyContributionPublicTitle,
    },
    { id: 'calendar' as const, label: copy.explainability.returnCalendar },
  ];

  return (
    <section className="space-y-5">
      <WorkspaceHeader
        eyebrow={copy.overview.kicker}
        title={copy.overview.title}
        description={copy.overview.subtitle}
      />

      {isInitialOverviewLoad ? (
        <div
          className="min-w-0 space-y-4"
          data-testid="overview-loading-workspace"
        >
          <EvidenceState
            kind="loading"
            statusLabel={copy.states.loading}
            title={copy.overview.loading}
          />
          <section
            aria-hidden="true"
            className="account-overview-summary min-w-0"
            data-testid="overview-loading-summary"
          >
            <dl className="account-primary-metric min-w-0">
              <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
                {copy.overview.cards.totalAssets}
              </dt>
              <dd className="mt-2 h-7 w-44 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
              <div className="mt-2 h-2 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
            </dl>
            <div
              className="account-metric-strip account-support-metric-strip app-metric-strip grid min-w-0 sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-row lg:grid-cols-5"
              data-testid="overview-loading-supporting-metrics"
            >
              {[
                todayPnlLabel,
                copy.overview.cards.unrealizedPnl,
                copy.portfolio.table.realized,
                copy.overview.cards.availableCash,
                copy.overview.cards.currentDrawdown,
              ].map((label) => (
                <div
                  key={label}
                  className="app-metric-strip-item min-w-0 px-3 py-2.5"
                >
                  <span className="app-type-label block font-medium text-[var(--app-text-secondary)]">
                    {label}
                  </span>
                  <span className="mt-2 block h-4 w-24 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                </div>
              ))}
            </div>
          </section>
          <div
            className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(340px,0.85fr)]"
            data-testid="overview-loading-daily-workbench"
          >
            <section
              className="min-w-0 space-y-2 xl:order-2"
              data-testid="overview-loading-queue"
            >
              <div>
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.overview.dashboard.todayToReview}
                </h2>
                <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {copy.overview.dashboard.opsPanel}
                </p>
              </div>
              <div
                aria-hidden="true"
                className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
                data-testid="overview-loading-queue-rows"
              >
                {Array.from({ length: 2 }, (_, index) => (
                  <div key={index} className="min-w-0 px-3 py-3">
                    <span className="block h-3 w-28 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                    <span className="mt-2 block h-3 w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                  </div>
                ))}
              </div>
            </section>
            <section
              className="min-w-0 space-y-2 xl:order-1"
              data-testid="overview-loading-holdings"
            >
              <div>
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.overview.dashboard.positionsPanel}
                </h2>
                <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {copy.overview.dashboard.positionsDetail}
                </p>
              </div>
              <div
                aria-hidden="true"
                className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
                data-testid="overview-loading-holding-rows"
              >
                {Array.from({ length: 3 }, (_, index) => (
                  <div
                    key={index}
                    className="grid min-h-14 min-w-0 grid-cols-[minmax(0,1fr)_6rem] items-center gap-4 px-3 py-3 sm:grid-cols-[minmax(9rem,1fr)_repeat(3,minmax(5rem,0.55fr))]"
                  >
                    <span className="block h-3 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                    {Array.from({ length: 3 }, (_, metricIndex) => (
                      <span
                        key={metricIndex}
                        className={`h-3 rounded-[var(--app-radius-control)] bg-[var(--app-divider)] ${
                          metricIndex > 0 ? 'hidden sm:block' : 'block'
                        }`}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      ) : isInitialOverviewError ? (
        <StatusCard
          tone="danger"
          title={copy.states.error}
          detail={copy.overview.error}
          actionLabel={copy.states.retry}
          onAction={() => {
            void overview.refetch();
            void snapshot.refetch();
          }}
        />
      ) : hasAnyPrimaryProjection ? (
        <div className="space-y-5">
          {overview.data ? (
            <OverviewCards
              overview={overview.data}
              variant="workbench"
              todayPnlLabel={todayPnlLabel}
              todayPnlContext={todayPnlContext}
            />
          ) : snapshot.data ? (
            <OverviewSnapshotFallbackCards
              snapshot={snapshot.data}
              todayPnlLabel={todayPnlLabel}
            />
          ) : (
            <EvidenceState
              kind={overview.isError ? 'error' : 'loading'}
              title={
                overview.isError
                  ? copy.portfolio.summary.error
                  : copy.portfolio.summary.loading
              }
              description={
                overview.isError
                  ? copy.portfolio.summary.errorDetail
                  : copy.portfolio.summary.loadingDetail
              }
              action={
                overview.isError ? (
                  <button
                    type="button"
                    className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                    onClick={() => void overview.refetch()}
                  >
                    {copy.states.retry}
                  </button>
                ) : undefined
              }
            />
          )}

          {snapshot.data ? (
            overview.data ? (
              <div
                className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(340px,0.85fr)]"
                data-testid="overview-daily-workbench"
              >
                <div className="min-w-0 xl:order-2">
                  <DashboardTodayQueue
                    overview={overview.data}
                    marketHealth={marketHealth.data}
                    portfolioSnapshot={snapshot.data}
                    marketEvidenceReview={holdingMarketEvidenceReview.data}
                    marketEvidenceReviewLoading={
                      holdingMarketEvidenceReview.isLoading
                    }
                    marketEvidenceReviewError={
                      holdingMarketEvidenceReview.isError
                    }
                    quoteDiagnostics={positions}
                    pendingOrders={pendingOrders.data ?? []}
                    pendingOrdersLoading={pendingOrders.isLoading}
                    pendingOrdersError={pendingOrders.isError}
                    strategyContribution={strategyContribution.data}
                    strategyContributionLoading={strategyContribution.isLoading}
                    strategyContributionError={strategyContribution.isError}
                    todayDecision={todayDecision.data}
                    todayDecisionLoading={todayDecision.isLoading}
                    todayDecisionError={todayDecision.isError}
                    tradingPlan={tradingPlan.data}
                    tradingPlanLoading={tradingPlan.isLoading}
                    tradingPlanError={tradingPlan.isError}
                    operationsToday={operationsToday.data}
                    operationsTodayLoading={operationsToday.isLoading}
                    operationsTodayError={operationsToday.isError}
                  />
                </div>
                <OverviewHoldingsSection
                  positions={positions}
                  assetClassBySymbol={assetClassBySymbol}
                  className="xl:order-1"
                />
              </div>
            ) : (
              <OverviewHoldingsSection
                positions={positions}
                assetClassBySymbol={assetClassBySymbol}
              />
            )
          ) : (
            <section
              className="min-w-0 space-y-2"
              data-testid="overview-holdings-section"
            >
              <h2 className="app-type-section-title text-[var(--app-text)]">
                {copy.overview.dashboard.positionsPanel}
              </h2>
              <EvidenceState
                kind={snapshot.isError ? 'error' : 'loading'}
                title={
                  snapshot.isError
                    ? copy.portfolio.positionsError
                    : copy.portfolio.positionsLoading
                }
                description={copy.overview.dashboard.positionsDetail}
                action={
                  snapshot.isError ? (
                    <button
                      type="button"
                      className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                      onClick={() => void snapshot.refetch()}
                    >
                      {copy.states.retry}
                    </button>
                  ) : undefined
                }
              />
            </section>
          )}

          {overview.data && snapshot.data ? (
            <>
              <section
                data-testid="overview-performance-card"
                className="min-w-0 overflow-hidden border-y border-[var(--app-divider)] bg-transparent"
              >
                <div
                  role="tablist"
                  aria-label={copy.overview.dashboard.equityPanel}
                  className="flex max-w-full overflow-x-auto border-b border-[var(--app-divider)]"
                >
                  {analysisTabs.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={analysisView === tab.id}
                      onClick={() => setAnalysisView(tab.id)}
                      className={`h-9 shrink-0 border-b-2 px-3 text-xs font-semibold ${
                        analysisView === tab.id
                          ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                          : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div className="min-w-0 py-3 sm:py-4">
                  {analysisView === 'performance' ? (
                    equityCurve.isLoading && !equityCurve.data ? (
                      <EquityCurveSkeleton />
                    ) : equityCurve.isError && !equityCurve.data ? (
                      <StatusCard
                        tone="danger"
                        title={copy.states.error}
                        detail={getEquityCurveErrorDetail(
                          equityCurve.error,
                          copy,
                        )}
                        actionLabel={copy.states.retry}
                        onAction={() => void equityCurve.refetch()}
                      />
                    ) : (
                      <div className="space-y-3">
                        {equityCurve.isError ? (
                          <div
                            role="status"
                            data-testid="equity-curve-refresh-warning"
                            className="app-panel-danger rounded-[var(--app-radius-surface)] px-3 py-2 text-xs leading-5"
                          >
                            {copy.overview.curveRefreshError}
                          </div>
                        ) : null}
                        <EquityCurveCard
                          points={equityCurve.data ?? []}
                          range={equityCurveRange}
                          onRangeChange={setEquityCurveRange}
                        />
                      </div>
                    )
                  ) : analysisView === 'allocation' ? (
                    <PortfolioExposureSummary snapshot={snapshot.data} />
                  ) : analysisView === 'attribution' ? (
                    <StrategyContributionGateCard
                      report={strategyContribution.data}
                      isLoading={strategyContribution.isLoading}
                      isError={strategyContribution.isError}
                      onRetry={() => void strategyContribution.refetch()}
                      instruments={positions}
                      variant="compact"
                    />
                  ) : (
                    <ReturnCalendarCard
                      timeline={explainability.data?.timeline ?? []}
                      positions={positions}
                      marketCalendar={marketCalendar.data}
                      compact
                    />
                  )}
                </div>
              </section>

              <div
                className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]"
                data-testid="overview-review-strip"
              >
                <DashboardMarketPulse
                  marketHealth={marketHealth.data}
                  isLoading={marketHealth.isLoading}
                  isError={marketHealth.isError}
                />
                <section className="min-w-0 border-y border-[var(--app-divider)] bg-transparent py-3 sm:py-4">
                  <div className="mb-3 flex items-end justify-between gap-3">
                    <h2 className="app-type-section-title text-[var(--app-text)]">
                      {copy.overview.dashboard.pendingApprovals}
                    </h2>
                    <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
                      {copy.overview.dashboard.pendingCount(
                        pendingOrders.data?.length ?? 0,
                      )}
                    </span>
                  </div>
                  <DashboardPendingOrders
                    orders={pendingOrders.data ?? []}
                    isLoading={pendingOrders.isLoading}
                    isError={pendingOrders.isError}
                    copy={copy}
                  />
                  <DashboardLedger
                    entries={ledgerEntries.data ?? []}
                    isLoading={ledgerEntries.isLoading}
                    isError={ledgerEntries.isError}
                    copy={copy}
                  />
                </section>
              </div>
            </>
          ) : null}
        </div>
      ) : (
        <StatusCard title={copy.states.empty} detail={copy.overview.empty} />
      )}
    </section>
  );
}

function OverviewHoldingsSection({
  positions,
  assetClassBySymbol,
  className,
}: {
  positions: PortfolioSnapshot['positions'];
  assetClassBySymbol: Record<string, string>;
  className?: string;
}) {
  const copy = useCopy();
  const navigate = useNavigate();

  return (
    <section
      className={`min-w-0 ${className ?? ''}`.trim()}
      data-testid="overview-holdings-section"
    >
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.overview.dashboard.positionsPanel}
          </h2>
          <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {copy.overview.dashboard.positionsDetail}
          </p>
        </div>
        <span className="text-xs tabular-nums text-[var(--app-text-tertiary)]">
          {positions.length} {copy.overview.risk.positions}
        </span>
      </div>
      {positions.length === 0 ? (
        <StatusCard
          title={copy.states.empty}
          detail={copy.portfolio.positionsEmpty}
        />
      ) : (
        <PositionsTable
          positions={positions}
          assetClassBySymbol={assetClassBySymbol}
          variant="dashboard"
          onOpenPosition={(symbol) => {
            void navigate({
              to: '/portfolio/$symbol',
              params: { symbol },
            });
          }}
        />
      )}
    </section>
  );
}

type TodayQueueTone = 'success' | 'warning' | 'danger' | 'neutral';
type TodayQueuePriority = 'first' | 'watch' | 'normal';

type TodayQueueItem = {
  key: string;
  title: string;
  detail: string;
  meta: string;
  href: string;
  actionLabel: string;
  tone: TodayQueueTone;
  priority: TodayQueuePriority;
  resolution?: string;
};

const TODAY_QUEUE_PRIORITY_ORDER: TodayQueuePriority[] = [
  'first',
  'watch',
  'normal',
];

function todayQueuePriorityLabel(
  priority: TodayQueuePriority,
  labels: AppCopy['overview']['dashboard'],
) {
  if (priority === 'first') {
    return labels.queuePriorityFirst;
  }
  if (priority === 'watch') {
    return labels.queuePriorityWatch;
  }
  return labels.queuePriorityNormal;
}

function canUseStrategyContribution(
  report?: AccountStrategyContributionReport | null,
) {
  return Boolean(
    report &&
    report.schema_version === 'karkinos.account_strategy_contribution.v2' &&
    report.contribution_status === 'evidence_bound_from_posted_fills' &&
    report.evidence_binding_status === 'bound' &&
    report.linked_fill_count > 0 &&
    report.ledger_posted_fill_count === report.linked_fill_count &&
    report.unposted_linked_fill_count === 0 &&
    Boolean(report.valuation_snapshot_id) &&
    (report.ledger_cutoff_id ?? 0) > 0 &&
    Boolean(report.contribution_fingerprint) &&
    report.evidence_refs.length > 0 &&
    report.missing_valuation_symbols.length === 0 &&
    report.persisted_facts_only === true &&
    report.provider_contacted === false &&
    report.database_writes_performed === false &&
    report.authorizes_execution === false,
  );
}

function strategyContributionReviewHref(
  report?: AccountStrategyContributionReport | null,
) {
  const status = report?.contribution_status ?? '';
  if (status.startsWith('valuation_')) {
    return '/market';
  }
  if (status.startsWith('ledger_')) {
    return '/operations';
  }
  return '/backtest';
}

function currentHoldingMarketReviewSummary(
  report: CurrentHoldingMarketEvidenceReview,
  labels: AppCopy['overview']['dashboard'],
) {
  return labels.dataReviewSummary(
    report.fund_nav_review_count,
    report.stale_or_cached_review_count,
    report.missing_or_error_review_count,
    report.estimated_review_count,
    report.unknown_status_review_count,
  );
}

function currentHoldingMarketReviewContractIsValid(
  report?: CurrentHoldingMarketEvidenceReview | null,
  portfolioSnapshot?: PortfolioSnapshot | null,
) {
  if (!report || !portfolioSnapshot) {
    return false;
  }
  const identityContractValid =
    report.status === 'blocked_identity'
      ? report.source_blockers.length > 0
      : Boolean(
          report.valuation_snapshot_id &&
          report.ledger_fingerprint &&
          report.quote_set_fingerprint,
        );
  const crossResponseIdentityValid = Boolean(
    report.valuation_snapshot_id === portfolioSnapshot.valuation_snapshot_id &&
    report.ledger_cutoff_id === portfolioSnapshot.ledger_cutoff_id &&
    report.ledger_fingerprint === portfolioSnapshot.ledger_fingerprint &&
    report.quote_set_fingerprint === portfolioSnapshot.quote_set_fingerprint,
  );
  return Boolean(
    report.schema_version ===
      'karkinos.current_holding_market_evidence_review.v1' &&
    report.reads_persisted_facts_only === true &&
    report.provider_contact_performed === false &&
    report.runtime_connector_query_performed === false &&
    report.database_writes_performed === false &&
    report.does_not_mutate_oms === true &&
    report.does_not_mutate_production_ledger === true &&
    report.does_not_mutate_risk === true &&
    report.does_not_mutate_kill_switch === true &&
    report.does_not_change_capital_authority === true &&
    report.authorizes_execution === false &&
    report.review_fingerprint.startsWith('sha256:') &&
    report.current_holding_count ===
      report.confirmed_holding_count + report.review_required_count &&
    report.items.length === report.review_required_count &&
    identityContractValid &&
    crossResponseIdentityValid &&
    Number.isInteger(report.ledger_cutoff_id) &&
    report.ledger_cutoff_id >= 0,
  );
}

function decisionCandidateDisplayName(candidate: DecisionCandidate) {
  return (
    candidate.display_name ??
    candidate.name ??
    candidate.evidence.signal?.display_name ??
    candidate.evidence.signal?.name ??
    candidate.symbol
  );
}

function tradingPlanIntentInstrumentLabel(
  intent: DailyTradingPlanResponse['order_intents'][number],
  candidates: DecisionCandidate[],
  quoteDiagnostics: QuoteDiagnosticItem[],
) {
  const symbol = String(intent.symbol ?? '').trim();
  const candidate = candidates.find(
    (item) =>
      (intent.action_id !== null && item.action_id === intent.action_id) ||
      item.symbol === symbol,
  );
  const quote = quoteDiagnostics.find((item) => item.symbol === symbol);
  const displayName =
    quote?.display_name ??
    quote?.name ??
    (candidate ? decisionCandidateDisplayName(candidate) : null);
  if (!displayName || displayName === symbol) {
    return symbol || '--';
  }
  return `${displayName}（${symbol}）`;
}

function tradingPlanManualIntentSummary(
  tradingPlan: DailyTradingPlanResponse,
  candidates: DecisionCandidate[],
  quoteDiagnostics: QuoteDiagnosticItem[],
  locale: Locale,
) {
  const intents = tradingPlan.order_intents.filter(
    (intent) => intent.submission_status === 'manual_confirmation_required',
  );
  const visibleIntents = intents.slice(0, 3);
  const formatter = new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    maximumFractionDigits: 4,
  });
  const summaries = visibleIntents.map((intent) =>
    [
      formatPublicStatus(intent.side, locale),
      tradingPlanIntentInstrumentLabel(intent, candidates, quoteDiagnostics),
      formatter.format(intent.estimated_quantity),
    ].join(' · '),
  );
  const remaining = intents.length - visibleIntents.length;
  if (remaining > 0) {
    summaries.push(
      locale === 'zh'
        ? `另 ${remaining} 笔待确认`
        : `${remaining} more awaiting confirmation`,
    );
  }
  return summaries.join(locale === 'zh' ? '；' : '; ');
}

function primaryOperationsDailyPlanBlocker(
  operations: OperationsTodayResponse | null | undefined,
) {
  const summary = operations?.daily_plan.blocker_summary ?? [];
  if (!operations || operations.daily_plan.blocked_count <= 0) {
    return null;
  }
  return summary[0] ?? null;
}

function isAwaitingRiskGateBlocker(
  blocker: ReturnType<typeof primaryOperationsDailyPlanBlocker>,
) {
  if (!blocker) {
    return false;
  }
  const reasons = blocker.reasons ?? [];
  return (
    blocker.target === 'risk' &&
    (blocker.category === 'evidence_not_ready' ||
      reasons.includes('awaiting_risk_gate') ||
      reasons.includes('risk_gate_not_checked'))
  );
}

function isRiskBlockedBlocker(
  blocker: ReturnType<typeof primaryOperationsDailyPlanBlocker>,
) {
  if (!blocker) {
    return false;
  }
  const reasons = blocker.reasons ?? [];
  return (
    blocker.target === 'risk' &&
    (blocker.category === 'risk_blocked' ||
      reasons.includes('risk_gate_blocked') ||
      reasons.some((reason) =>
        [
          'cash reserve would fall below min_cash_reserve',
          'projected position weight exceeds max_position_weight',
          'cash_buffer_breached',
          'concentration_limit_breached',
        ].includes(reason),
      ))
  );
}

function operationsQueueTarget(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
) {
  const primaryTarget = primarySubsystem?.target ?? operations?.primary_target;
  if (primaryTarget === 'market' || primaryTarget === 'account-truth') {
    return primaryTarget;
  }
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (isAwaitingRiskGateBlocker(blocker) || isRiskBlockedBlocker(blocker)) {
    return 'risk';
  }
  return primaryTarget;
}

function operationsDuplicatesTradingPlanReview(
  operations: OperationsTodayResponse | null | undefined,
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
) {
  if (!operations || !tradingPlan) {
    return false;
  }
  const operationsManualReady = operations.daily_plan.manual_ready_count;
  const nextAction = operationsPrimaryNextAction(operations, primarySubsystem);
  return (
    operations.conclusion_status === 'manual_action_required' &&
    operationsQueueTarget(operations, primarySubsystem) === 'trading' &&
    (nextAction === 'review_manual_order_intents' ||
      nextAction === 'review_manual_confirmation') &&
    operations.daily_plan.blocked_count === 0 &&
    tradingPlan.blocked_count === 0 &&
    operationsManualReady > 0 &&
    tradingPlan.manual_ready_count === operationsManualReady
  );
}

function operationsStatusTitle(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const status = operations?.conclusion_status;
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (isAwaitingRiskGateBlocker(blocker)) {
    return locale === 'zh' ? '风险闸门待检查' : 'Risk gate checks pending';
  }
  if (isRiskBlockedBlocker(blocker)) {
    return locale === 'zh' ? '风控阻断待复核' : 'Risk blocks need review';
  }
  if (locale === 'zh') {
    if (!operations) return '运营状态加载中';
    if (status === 'blocked') return '今日待办存在阻断';
    if (status === 'manual_action_required') return '今日待办需要人工复核';
    if (status === 'degraded') return '今日待办存在降级项';
    return '今日运行状态正常';
  }
  if (!operations) return 'Operations status loading';
  if (status === 'blocked') return 'Today runbook has blockers';
  if (status === 'manual_action_required') {
    return 'Today runbook needs manual review';
  }
  if (status === 'degraded') return 'Today runbook has degraded checks';
  return 'Today runbook is healthy';
}

function riskBlockReasonLabel(reason: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    'cash reserve would fall below min_cash_reserve': {
      en: 'cash buffer would be breached',
      zh: '现金缓冲不足',
    },
    cash_buffer_breached: {
      en: 'cash buffer would be breached',
      zh: '现金缓冲不足',
    },
    'projected position weight exceeds max_position_weight': {
      en: 'single-name weight would exceed policy',
      zh: '单标的仓位过高',
    },
    concentration_limit_breached: {
      en: 'single-name weight would exceed policy',
      zh: '单标的仓位过高',
    },
    risk_gate_blocked: {
      en: 'risk gate blocked the action',
      zh: '风控闸门阻断动作',
    },
  };
  return labels[reason]?.[locale] ?? formatPublicStatus(reason, locale);
}

function riskBlockerDetailText(
  blocker: ReturnType<typeof primaryOperationsDailyPlanBlocker>,
  locale: Locale,
) {
  if (!blocker) {
    return null;
  }
  const reasons = Array.from(
    new Set(
      (blocker.reasons ?? []).map((reason) =>
        riskBlockReasonLabel(reason, locale),
      ),
    ),
  ).slice(0, 3);
  const symbols = (blocker.sample_symbols ?? []).slice(0, 3);
  const reasonText = reasons.length
    ? reasons.join(locale === 'zh' ? '、' : ', ')
    : locale === 'zh'
      ? '风控规则'
      : 'risk policy';
  if (locale === 'zh') {
    const symbolText = symbols.length ? `；涉及 ${symbols.join('、')}` : '';
    return `${blocker.count} 个候选被风控阻断：${reasonText}${symbolText}。先复核原因，不进入人工确认。`;
  }
  const symbolText = symbols.length ? ` Symbols: ${symbols.join(', ')}.` : '';
  return `${blocker.count} candidates are blocked by risk: ${reasonText}.${symbolText} Review the reasons before manual confirmation.`;
}

function numericPaperShadowValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function overviewCountLabel(count: number, singular: string, locale: Locale) {
  if (locale === 'zh') {
    return `${count} ${singular}`;
  }
  return `${count} ${singular}${count === 1 ? '' : 's'}`;
}

function paperShadowOverviewEvidenceSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const paperShadow = operations?.paper_shadow;
  if (!paperShadow) {
    return null;
  }
  const nextStep = paperShadow.next_manual_review_step;
  const shouldSummarize =
    Boolean(paperShadow.manual_handoff) ||
    nextStep === 'review_shadow_divergence' ||
    nextStep === 'resolve_shadow_divergence' ||
    paperShadow.status === 'review_required' ||
    paperShadow.status === 'diverged' ||
    paperShadow.divergence_status === 'review_required' ||
    paperShadow.divergence_status === 'diverged';
  if (!shouldSummarize) {
    return null;
  }
  const summary = paperShadow.divergence_summary;
  const labels =
    locale === 'zh'
      ? {
          prefix: 'Paper/shadow',
          orderIntent: '订单意图',
          simOrder: '模拟订单',
          simFill: '模拟成交',
          diverged: '偏差',
          slippage: '模拟滑点',
          noBrokerSubmission: '不会提交券商订单',
        }
      : {
          prefix: 'Paper/shadow',
          orderIntent: 'order intent',
          simOrder: 'sim order',
          simFill: 'sim fill',
          diverged: 'Diverged',
          slippage: 'Sim slippage',
          noBrokerSubmission: 'No broker submission',
        };
  const countText = [
    overviewCountLabel(
      paperShadow.order_intent_count,
      labels.orderIntent,
      locale,
    ),
    overviewCountLabel(
      paperShadow.simulated_order_count,
      labels.simOrder,
      locale,
    ),
    overviewCountLabel(
      paperShadow.simulated_fill_count,
      labels.simFill,
      locale,
    ),
  ].join(locale === 'zh' ? '，' : ', ');
  const divergedRefs = (
    summary?.execution_comparison?.diverged_order_refs ?? []
  )
    .slice(0, 2)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const slippage = numericPaperShadowValue(
    summary?.cost_summary?.simulated_slippage_cost,
  );
  return [
    `${labels.prefix}: ${countText}`,
    ...paperShadowInputSnapshotSummary(paperShadow, locale),
    divergedRefs.length
      ? `${labels.diverged}: ${divergedRefs.join(locale === 'zh' ? '；' : '; ')}`
      : '',
    paperShadowManualHandoffSummary(paperShadow, locale),
    paperShadowReviewQueueSummary(paperShadow, locale),
    slippage !== null
      ? `${labels.slippage}: ${formatCurrencyValue(slippage)}`
      : '',
    summary?.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowInputSnapshotSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const snapshot = paperShadow.input_snapshot;
  const orderIntentCount = numericPaperShadowValue(
    snapshot?.order_intent_count,
  );
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot?.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot?.input_fingerprint) ??
    stringPaperShadowSnapshotValue(paperShadow.input_fingerprint);
  const labels =
    locale === 'zh'
      ? {
          input: '输入快照',
          orderIntent: '订单意图',
          source: '源决策',
          fingerprint: '指纹',
          safety: '快照安全边界',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          input: 'Input snapshot',
          orderIntent: 'order intent',
          source: 'Source',
          fingerprint: 'Fingerprint',
          safety: 'Snapshot safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const inputParts = [
    orderIntentCount === null
      ? ''
      : `${orderIntentCount} ${labels.orderIntent}${
          locale === 'en' && orderIntentCount !== 1 ? 's' : ''
        }`,
    sourceDecision
      ? `${labels.source} ${formatPublicStatus(sourceDecision, locale)}`
      : '',
    fingerprint ? `${labels.fingerprint} ${fingerprint.slice(0, 12)}` : '',
  ].filter(Boolean);
  const safetyParts = [
    snapshot?.does_not_submit_broker_order === true
      ? labels.noBrokerSubmission
      : '',
    snapshot?.does_not_mutate_production_ledger === true
      ? labels.noLedgerMutation
      : '',
  ].filter(Boolean);
  return [
    inputParts.length ? `${labels.input}: ${inputParts.join(' · ')}` : '',
    safetyParts.length ? `${labels.safety}: ${safetyParts.join(' · ')}` : '',
  ].filter(Boolean);
}

function stringPaperShadowSnapshotValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function paperShadowManualHandoffSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const handoff = paperShadow.manual_handoff;
  if (!handoff) {
    return null;
  }
  const labels =
    locale === 'zh'
      ? {
          prefix: '人工确认交接',
          queue: '复核队列',
          item: '项',
          items: '项',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          prefix: 'Manual handoff',
          queue: 'Review queue',
          item: 'item',
          items: 'items',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const queueCount = handoff.review_queue_count ?? 0;
  return [
    `${labels.prefix}: ${paperShadowManualHandoffStatusLabel(
      handoff.status,
      locale,
    )}`,
    queueCount > 0
      ? `${labels.queue}: ${queueCount} ${
          queueCount === 1 ? labels.item : labels.items
        }`
      : '',
    handoff.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    handoff.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowManualHandoffStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    ready_after_accepted_review: {
      en: 'Ready after accepted simulation review',
      zh: '已接受模拟复核，可人工确认',
    },
    ready_after_clean_simulation: {
      en: 'Ready after clean simulation',
      zh: '模拟无偏差，可人工确认',
    },
    blocked_by_unresolved_divergence: {
      en: 'Blocked by unresolved simulation divergence',
      zh: '模拟偏差未处理，暂不可人工确认',
    },
    blocked_by_failed_run: {
      en: 'Blocked by failed simulation run',
      zh: '模拟运行失败，暂不可人工确认',
    },
    blocked_by_review_requested_rerun: {
      en: 'Blocked until simulation reruns',
      zh: '需要重新运行模拟后再确认',
    },
    paper_shadow_required: {
      en: 'Simulation required before manual confirmation',
      zh: '人工确认前需要模拟复核',
    },
    waiting_for_paper_shadow_run: {
      en: 'Waiting for simulation result',
      zh: '等待模拟复核结果',
    },
    not_required: {
      en: 'No manual handoff required',
      zh: '无需人工确认交接',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function paperShadowReviewQueueSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const queue = paperShadow.review_queue ?? [];
  if (queue.length === 0) {
    return null;
  }
  const firstAction = queue[0]?.required_action
    ? operationsNextActionLabel(queue[0].required_action, locale)
    : '';
  const firstDetail = paperShadowReviewQueueItemSummary(queue[0], locale);
  if (locale === 'zh') {
    return [`复核队列：${queue.length} 项`, firstAction, firstDetail]
      .filter(Boolean)
      .join(' · ');
  }
  return [
    `Review queue: ${queue.length} item${queue.length === 1 ? '' : 's'}`,
    firstAction,
    firstDetail,
  ]
    .filter(Boolean)
    .join(' · ');
}

type OverviewPaperShadowReviewQueueItem = NonNullable<
  OperationsTodayResponse['paper_shadow']['review_queue']
>[number];

function paperShadowReviewQueueItemSummary(
  item: OverviewPaperShadowReviewQueueItem | undefined,
  locale: Locale,
) {
  if (!item) {
    return '';
  }
  const labels =
    locale === 'zh'
      ? {
          risk: '风控',
          manual: '人工确认',
          manualReady: '可确认',
          accountTruth: '账户事实',
          cash: '现金',
          constraints: '约束',
          projectedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          queueSlippage: '队列滑点',
          expected: '预期',
          fill: '成交',
          terminalOutcome: '终态结果',
          omsPath: 'OMS 路径',
          omsTransition: 'OMS 状态变更',
          evidence: '证据',
        }
      : {
          risk: 'Risk',
          manual: 'Manual',
          manualReady: 'Ready',
          accountTruth: 'Account truth',
          cash: 'Cash',
          constraints: 'Constraints',
          projectedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          queueSlippage: 'Queue slippage',
          expected: 'Expected',
          fill: 'Fill',
          terminalOutcome: 'Terminal outcome',
          omsPath: 'OMS path',
          omsTransition: 'OMS transition',
          evidence: 'Evidence',
        };
  const riskManual = [
    item.risk_gate_status
      ? `${labels.risk} ${formatPublicStatus(item.risk_gate_status, locale)}`
      : '',
    item.manual_confirmation_status
      ? `${labels.manual} ${
          item.manual_confirmation_status === 'ready_for_manual_confirmation'
            ? labels.manualReady
            : formatPublicStatus(item.manual_confirmation_status, locale)
        }`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const accountCash = [
    item.account_truth?.gate_status
      ? `${labels.accountTruth} ${formatPublicStatus(
          item.account_truth.gate_status,
          locale,
        )}`
      : '',
    item.cash_status
      ? `${labels.cash} ${formatPublicStatus(item.cash_status, locale)}`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const constraints = paperShadowStatusCountSummary(
    item.constraint_status_counts,
    locale,
  );
  const costs = [
    paperShadowCurrencySummary(
      labels.projectedFee,
      item.cost_evidence?.estimated_total_fee,
    ),
    paperShadowCurrencySummary(
      labels.simulatedFeeTax,
      item.cost_evidence?.simulated_fee_tax_cost,
    ),
    paperShadowCurrencySummary(
      labels.queueSlippage,
      item.cost_evidence?.simulated_slippage_cost,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const marketContext = [
    paperShadowCurrencySummary(
      labels.expected,
      item.market_context?.expected_price,
    ),
    paperShadowFillPriceSummary(
      labels.fill,
      item.market_context?.simulated_fill_prices,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const omsStatusPath = paperShadowOmsStatusPath(item.oms_status_path, locale);
  const terminalOutcome = paperShadowTerminalOutcomeSummary(item, locale);
  const omsTransition = paperShadowLatestOmsTransition(item, locale);
  const evidence = (item.evidence_refs ?? [])
    .slice(0, 6)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean)
    .join(locale === 'zh' ? '；' : '; ');
  return [
    riskManual,
    accountCash,
    constraints ? `${labels.constraints} ${constraints}` : '',
    costs,
    marketContext,
    terminalOutcome ? `${labels.terminalOutcome}: ${terminalOutcome}` : '',
    omsStatusPath ? `${labels.omsPath}: ${omsStatusPath}` : '',
    omsTransition ? `${labels.omsTransition}: ${omsTransition}` : '',
    evidence ? `${labels.evidence}: ${evidence}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowTerminalOutcomeSummary(
  item: OverviewPaperShadowReviewQueueItem,
  locale: Locale,
) {
  const status = paperShadowOmsStatusLabel(
    item.terminal_status ?? undefined,
    locale,
  );
  const reason = paperShadowTerminalReasonLabel(
    item.terminal_reason ?? undefined,
    locale,
  );
  const transition = item.terminal_oms_transition_ref
    ? formatPublicEvidenceReference(item.terminal_oms_transition_ref, locale)
    : '';
  return [status, reason, transition].filter(Boolean).join(' · ');
}

function paperShadowTerminalReasonLabel(
  reason: string | undefined,
  locale: Locale,
) {
  const normalized = String(reason ?? '').trim();
  if (!normalized) {
    return '';
  }
  const labels: Record<string, Record<Locale, string>> = {
    operator_cancelled: {
      en: 'Operator cancelled simulation before fill',
      zh: '操作员在模拟成交前取消',
    },
    paper_session_closed: {
      en: 'Paper session closed before fill',
      zh: '模拟交易时段结束，未成交前过期',
    },
  };
  return labels[normalized]?.[locale] ?? formatPublicStatus(normalized, locale);
}

function paperShadowOmsStatusPath(
  values: string[] | undefined,
  locale: Locale,
) {
  if (!values || values.length === 0) {
    return '';
  }
  return values
    .map((value) => paperShadowOmsStatusLabel(value, locale))
    .filter(Boolean)
    .join(' > ');
}

function paperShadowLatestOmsTransition(
  item: OverviewPaperShadowReviewQueueItem,
  locale: Locale,
) {
  const transition = [...(item.oms_transitions ?? [])]
    .reverse()
    .find((entry) => entry.to_status);
  if (!transition?.to_status) {
    return '';
  }
  const orderId = item.order_id ? `${item.order_id} ` : '';
  const sequence =
    transition.sequence !== null && transition.sequence !== undefined
      ? `#${transition.sequence} `
      : '';
  return `${orderId}${sequence}${paperShadowOmsStatusLabel(
    transition.to_status,
    locale,
  )}`;
}

function paperShadowOmsStatusLabel(
  value: string | null | undefined,
  locale: Locale,
) {
  const status = String(value ?? '').trim();
  if (!status) {
    return '';
  }
  const labels: Record<string, Record<Locale, string>> = {
    staged: { en: 'Staged', zh: '已暂存' },
    submitted: { en: 'Submitted', zh: '已提交模拟' },
    accepted: { en: 'Accepted', zh: '已接受模拟' },
    partially_filled: { en: 'Partially Filled', zh: '部分成交' },
    filled: { en: 'Filled', zh: '已成交' },
    rejected: { en: 'Rejected', zh: '已拒绝' },
    cancelled: { en: 'Cancelled', zh: '已取消' },
    expired: { en: 'Expired', zh: '已过期' },
    reconciled: { en: 'Reconciled', zh: '已对账' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function paperShadowStatusCountSummary(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  return Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([key, value]) => `${formatPublicStatus(key, locale)}: ${value}`)
    .join(locale === 'zh' ? '；' : '; ');
}

function paperShadowCurrencySummary(label: string, value: unknown) {
  const numeric = numericPaperShadowValue(value);
  return numeric === null ? '' : `${label} ${formatCurrencyValue(numeric)}`;
}

function paperShadowFillPriceSummary(
  label: string,
  values: unknown[] | undefined,
) {
  const prices = (values ?? [])
    .map((value) => numericPaperShadowValue(value))
    .filter((value): value is number => value !== null)
    .map((value) => formatCurrencyValue(value));
  return prices.length ? `${label} ${prices.join(', ')}` : '';
}

function operationsDetailText(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
  fallback: string,
) {
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (blocker && isAwaitingRiskGateBlocker(blocker)) {
    if (locale === 'zh') {
      return `${blocker.count} 个候选等待风险闸门检查；当前 ${operations?.daily_plan.manual_ready_count ?? 0} 个可人工确认。`;
    }
    return `${blocker.count} candidates are waiting for risk-gate checks; ${operations?.daily_plan.manual_ready_count ?? 0} are ready for manual confirmation.`;
  }
  if (blocker && isRiskBlockedBlocker(blocker)) {
    return riskBlockerDetailText(blocker, locale) ?? fallback;
  }
  const schedulerSummary = operationsSchedulerEvidenceSummary(
    operations,
    locale,
  );
  if (schedulerSummary) {
    return `${fallback} · ${schedulerSummary}`;
  }
  const reconciliationSummary = executionReconciliationOverviewSummary(
    operations,
    locale,
  );
  if (reconciliationSummary) {
    return `${fallback} · ${reconciliationSummary}`;
  }
  const paperShadowSummary = paperShadowOverviewEvidenceSummary(
    operations,
    locale,
  );
  return paperShadowSummary ? `${fallback} · ${paperShadowSummary}` : fallback;
}

function executionReconciliationOverviewSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const reconciliation = operations?.execution_reconciliation;
  if (!reconciliation || reconciliation.open_item_count <= 0) {
    return '';
  }
  const first = reconciliation.first_open_item;
  const manualSummary = first?.manual_execution_evidence_summary;
  const labels =
    locale === 'zh'
      ? {
          reviewCount: '对账复核',
          item: '项',
          items: '项',
          manualExecution: '手工成交',
          preview: '预览',
          noBrokerSubmission: '不会提交券商订单',
          noOmsMutation: '不会修改 OMS',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          reviewCount: 'Reconciliation review',
          item: 'item',
          items: 'items',
          manualExecution: 'Manual execution',
          preview: 'Preview',
          noBrokerSubmission: 'No broker submission',
          noOmsMutation: 'No OMS mutation',
          noLedgerMutation: 'No production ledger mutation',
        };
  const countLabel =
    reconciliation.open_item_count === 1 ? labels.item : labels.items;
  return [
    `${labels.reviewCount}: ${reconciliation.open_item_count} ${countLabel}`,
    operationsNextActionLabel(
      reconciliation.next_review_step || first?.suggested_action || 'none',
      locale,
    ),
    first?.order_id ? `${labels.manualExecution}: ${first.order_id}` : '',
    manualSummary?.preview_fingerprint
      ? `${labels.preview} ${manualSummary.preview_fingerprint}`
      : '',
    reconciliation.does_not_submit_broker_order ||
    manualSummary?.submitted_to_broker === false
      ? labels.noBrokerSubmission
      : '',
    reconciliation.does_not_mutate_oms ||
    manualSummary?.does_not_mutate_oms === true
      ? labels.noOmsMutation
      : '',
    reconciliation.does_not_mutate_production_ledger ||
    manualSummary?.does_not_mutate_production_ledger === true
      ? labels.noLedgerMutation
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function operationsSchedulerEvidenceSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const scheduler = operations?.scheduler;
  if (!scheduler) {
    return '';
  }
  const status = String(scheduler.status ?? '')
    .trim()
    .toLowerCase();
  const isFailure =
    status.endsWith('_failed') || status === 'failed' || status === 'error';
  if (!isFailure && operations?.primary_target !== 'scheduler') {
    return '';
  }

  const parts = [
    scheduler.run_id
      ? locale === 'zh'
        ? `运行 ${scheduler.run_id}`
        : `Run ${scheduler.run_id}`
      : '',
    schedulerInputSnapshotSummary(scheduler, locale),
    schedulerRerunKeySummary(scheduler.idempotency_key, locale),
    schedulerRetrySummary(scheduler.retry_state, locale),
    schedulerErrorSummary(scheduler.error),
    scheduler.does_not_submit_broker_order
      ? locale === 'zh'
        ? '不会提交券商订单'
        : 'No broker submission'
      : '',
  ].filter(Boolean);
  return parts.join(locale === 'zh' ? ' · ' : ' · ');
}

function schedulerInputSnapshotSummary(
  scheduler: NonNullable<OperationsTodayResponse['scheduler']>,
  locale: Locale,
) {
  const snapshot = scheduler.input_snapshot;
  if (!snapshot) {
    return '';
  }
  const orderIntentCount = numericPaperShadowValue(snapshot.order_intent_count);
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot.input_fingerprint) ??
    stringPaperShadowSnapshotValue(scheduler.input_fingerprint);
  const labels =
    locale === 'zh'
      ? {
          input: '输入快照',
          orderIntent: '订单意图',
          source: '源决策',
          fingerprint: '指纹',
        }
      : {
          input: 'Input snapshot',
          orderIntent: 'order intent',
          source: 'Source',
          fingerprint: 'Fingerprint',
        };
  const parts = [
    orderIntentCount === null
      ? ''
      : `${orderIntentCount} ${labels.orderIntent}${
          locale === 'en' && orderIntentCount !== 1 ? 's' : ''
        }`,
    sourceDecision
      ? `${labels.source} ${formatPublicStatus(sourceDecision, locale)}`
      : '',
    fingerprint ? `${labels.fingerprint} ${fingerprint.slice(0, 12)}` : '',
  ].filter(Boolean);
  return parts.length ? `${labels.input}: ${parts.join(' · ')}` : '';
}

function schedulerRerunKeySummary(
  idempotencyKey: string | null | undefined,
  locale: Locale,
) {
  const key = stringPaperShadowSnapshotValue(idempotencyKey);
  if (!key) {
    return '';
  }
  return locale === 'zh' ? `重跑键: ${key}` : `Rerun key: ${key}`;
}

function schedulerRetrySummary(
  retryState: Record<string, unknown> | undefined,
  locale: Locale,
) {
  if (!retryState) {
    return '';
  }
  const attempt = numericRetryValue(retryState.attempt);
  if (attempt <= 0) {
    return '';
  }
  const maxAttempts = Math.max(
    numericRetryValue(retryState.max_attempts),
    attempt,
  );
  const previousAttempts = numericRetryValue(retryState.previous_attempts);
  if (locale === 'zh') {
    return previousAttempts > 0
      ? `重试 ${attempt}/${maxAttempts}；此前 ${previousAttempts} 次`
      : `重试 ${attempt}/${maxAttempts}`;
  }
  return previousAttempts > 0
    ? `Retry ${attempt}/${maxAttempts}; previous attempts ${previousAttempts}`
    : `Retry ${attempt}/${maxAttempts}`;
}

function schedulerErrorSummary(error: Record<string, unknown> | undefined) {
  if (!error) {
    return '';
  }
  const type = String(error.type ?? '').trim();
  const message = String(error.message ?? '').trim();
  if (type && message) {
    return `${type}: ${message}`;
  }
  return type || message;
}

function numericRetryValue(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? Math.trunc(numberValue) : 0;
}

function operationsPrimaryNextAction(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
) {
  if (
    operations?.paper_shadow.review_status ===
      'accepted_for_manual_confirmation' ||
    operations?.paper_shadow.status === 'within_expectations' ||
    operations?.paper_shadow.divergence_status === 'within_expectations'
  ) {
    return operations.paper_shadow.next_manual_review_step;
  }
  return (
    primarySubsystem?.next_action ??
    operations?.paper_shadow.next_manual_review_step
  );
}

function operationsStatusMeta(
  operations: OperationsTodayResponse,
  locale: Locale,
) {
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (blocker && isAwaitingRiskGateBlocker(blocker)) {
    return locale === 'zh'
      ? `${blocker.count} 待检查`
      : `${blocker.count} pending checks`;
  }
  if (blocker && isRiskBlockedBlocker(blocker)) {
    return locale === 'zh'
      ? `${blocker.count} 风控阻断`
      : `${blocker.count} risk blocked`;
  }
  const { blocked, manual_action_required, degraded, pass, total } =
    operations.health;
  if (locale === 'zh') {
    if (blocked > 0) return `${blocked} 阻断`;
    if (operations.conclusion_status === 'degraded' && degraded > 0) {
      return `${degraded} 降级`;
    }
    if (manual_action_required > 0) return `${manual_action_required} 人工复核`;
    if (degraded > 0) return `${degraded} 降级`;
    return `${pass}/${total} 通过`;
  }
  if (blocked > 0) return `${blocked} blocked`;
  if (operations.conclusion_status === 'degraded' && degraded > 0) {
    return `${degraded} degraded`;
  }
  if (manual_action_required > 0) {
    return `${manual_action_required} manual review`;
  }
  if (degraded > 0) return `${degraded} degraded`;
  return `${pass}/${total} passed`;
}

function operationsActionLabel(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
  labels: AppCopy['overview']['dashboard'],
  locale: Locale,
) {
  const target = operationsQueueTarget(operations, primarySubsystem);
  if (target === 'risk') {
    return labels.operationsViewRisk;
  }
  if (target === 'account-truth') {
    return labels.operationsViewAccountTruth;
  }
  if (target === 'market') {
    return labels.operationsViewMarket;
  }
  if (target === 'trading') {
    return labels.operationsViewTrading;
  }
  if (target === 'paper-shadow') {
    return labels.operationsViewPaperShadow;
  }
  return locale === 'zh' ? '查看运行证据' : 'View run evidence';
}

function tradingPlanBlockerCategoryLabel(category: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    account_truth: { en: 'Account truth', zh: '账户事实' },
    market_data: { en: 'Market/NAV data', zh: '行情/净值' },
    portfolio: { en: 'Portfolio constraints', zh: '组合约束' },
    risk: { en: 'Risk gate', zh: '风控闸门' },
    evidence_not_ready: {
      en: 'Evidence not ready',
      zh: '证据未就绪',
    },
    other: { en: 'Other blockers', zh: '其他阻断' },
  };
  return labels[category]?.[locale] ?? formatPublicStatus(category, locale);
}

function tradingPlanBlockerSummaryText(
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  locale: Locale,
) {
  const summary = tradingPlan?.blocker_summary ?? [];
  if (!tradingPlan || tradingPlan.blocked_count <= 0) {
    return null;
  }
  if (summary.length === 0) {
    return locale === 'zh'
      ? `${tradingPlan.blocked_count} 个阻断待归因`
      : `${tradingPlan.blocked_count} blockers need classification`;
  }
  return summary
    .slice(0, 3)
    .map(
      (item) =>
        `${tradingPlanBlockerCategoryLabel(item.category, locale)} ${item.count}`,
    )
    .join(locale === 'zh' ? ' · ' : ' · ');
}

function tradingPlanBlockedDetailText(
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  locale: Locale,
  fallback: string,
) {
  const summary = tradingPlan?.blocker_summary ?? [];
  if (!tradingPlan || tradingPlan.blocked_count <= 0 || summary.length === 0) {
    return fallback;
  }
  const primary = summary[0];
  const primaryLabel = tradingPlanBlockerCategoryLabel(
    primary.category,
    locale,
  );
  if (locale === 'zh') {
    if (primary.category === 'evidence_not_ready') {
      return `${primary.count} 个候选尚未通过风控/证据闸门；当前 ${tradingPlan.manual_ready_count} 个需要人工确认。`;
    }
    return `先处理 ${primaryLabel} ${primary.count} 项，再重新生成今日交易计划。`;
  }
  if (primary.category === 'evidence_not_ready') {
    return `${primary.count} candidates are still waiting on risk/evidence gates; ${tradingPlan.manual_ready_count} need manual confirmation now.`;
  }
  return `Resolve ${primary.count} ${primaryLabel.toLowerCase()} items first, then regenerate today's trading plan.`;
}

function DashboardTodayQueue({
  overview,
  marketHealth,
  portfolioSnapshot,
  marketEvidenceReview,
  marketEvidenceReviewLoading,
  marketEvidenceReviewError,
  quoteDiagnostics,
  pendingOrders,
  pendingOrdersLoading,
  pendingOrdersError,
  strategyContribution,
  strategyContributionLoading,
  strategyContributionError,
  todayDecision,
  todayDecisionLoading,
  todayDecisionError,
  tradingPlan,
  tradingPlanLoading,
  tradingPlanError,
  operationsToday,
  operationsTodayLoading,
  operationsTodayError,
}: {
  overview: AccountOverview;
  marketHealth?: MarketDataHealthResponse;
  portfolioSnapshot: PortfolioSnapshot;
  marketEvidenceReview?: CurrentHoldingMarketEvidenceReview | null;
  marketEvidenceReviewLoading: boolean;
  marketEvidenceReviewError: boolean;
  quoteDiagnostics: QuoteDiagnosticItem[];
  pendingOrders: ManualOrder[];
  pendingOrdersLoading: boolean;
  pendingOrdersError: boolean;
  strategyContribution?: AccountStrategyContributionReport | null;
  strategyContributionLoading: boolean;
  strategyContributionError: boolean;
  todayDecision?: DecisionResponse | null;
  todayDecisionLoading: boolean;
  todayDecisionError: boolean;
  tradingPlan?: DailyTradingPlanResponse | null;
  tradingPlanLoading: boolean;
  tradingPlanError: boolean;
  operationsToday?: OperationsTodayResponse | null;
  operationsTodayLoading: boolean;
  operationsTodayError: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const instrumentDiagnostics = [
    ...quoteDiagnostics,
    ...(marketHealth?.quotes ?? []),
  ];
  const marketReviewContractValid = currentHoldingMarketReviewContractIsValid(
    marketEvidenceReview,
    portfolioSnapshot,
  );
  const marketReviewUnavailable =
    marketEvidenceReviewError ||
    (!marketEvidenceReviewLoading && !marketReviewContractValid);
  const marketReviewIdentityBlocked =
    marketReviewContractValid &&
    marketEvidenceReview?.status === 'blocked_identity';
  const dataNeedsReview = Boolean(
    marketReviewUnavailable ||
    marketReviewIdentityBlocked ||
    marketEvidenceReview?.status === 'review_required',
  );
  const dataDetail = marketEvidenceReviewLoading
    ? labels.dataReviewLoading
    : marketReviewUnavailable
      ? labels.dataReviewUnavailable
      : marketReviewIdentityBlocked
        ? labels.dataReviewIdentityBlocked
        : marketEvidenceReview?.status === 'review_required'
          ? currentHoldingMarketReviewSummary(marketEvidenceReview, labels)
          : `${labels.valuationTime}: ${formatTimestamp(
              marketEvidenceReview?.valuation_as_of ??
                overview.valuation_timestamp,
            )}`;
  const dataMeta = marketEvidenceReviewLoading
    ? copy.states.loading
    : marketReviewUnavailable
      ? '--'
      : marketEvidenceReview?.status === 'review_required'
        ? labels.affectedCount(marketEvidenceReview.review_required_count)
        : labels.dataReviewConfirmedCount(
            marketEvidenceReview?.confirmed_holding_count ?? 0,
          );
  const dataTone: TodayQueueTone = marketReviewUnavailable
    ? 'danger'
    : dataNeedsReview
      ? 'warning'
      : marketEvidenceReviewLoading
        ? 'neutral'
        : 'success';
  const dataPriority: TodayQueuePriority = marketReviewUnavailable
    ? 'first'
    : dataNeedsReview
      ? 'first'
      : 'normal';
  const dataRefreshSymbols =
    marketReviewContractValid &&
    marketEvidenceReview?.status === 'review_required'
      ? marketEvidenceReview.refreshable_symbols
      : [];
  const strategyReady = canUseStrategyContribution(strategyContribution);
  const strategyHasNoLinkedFills =
    strategyContribution?.contribution_status === 'no_linked_fills' &&
    strategyContribution.linked_fill_count === 0 &&
    (strategyContribution.unattributed_fill_count ?? 0) === 0;
  const strategyStatus = strategyContribution?.contribution_status
    ? (copy.backtest.page.accountStrategyContributionStatusMap[
        strategyContribution.contribution_status as keyof typeof copy.backtest.page.accountStrategyContributionStatusMap
      ] ?? formatPublicStatus(strategyContribution.contribution_status, locale))
    : copy.backtest.page.accountStrategyContributionStatusMap.no_linked_fills;
  const strategyNextAction = strategyContribution?.next_manual_action
    ? (copy.backtest.page.accountStrategyNextActionMap[
        strategyContribution.next_manual_action as keyof typeof copy.backtest.page.accountStrategyNextActionMap
      ] ?? formatPublicStatus(strategyContribution.next_manual_action, locale))
    : copy.backtest.page.accountStrategyContributionHiddenUntilEvidence;
  const strategyHref = strategyContributionReviewHref(strategyContribution);
  const strategyActionLabel = strategyHref.startsWith('/market')
    ? labels.viewData
    : strategyHref.startsWith('/operations')
      ? labels.viewOperations
      : labels.viewStrategy;
  const candidates = todayDecision?.candidates ?? [];
  const leadingCandidate = candidates[0];
  const decisionActionLabel = leadingCandidate
    ? (labels.decisionActionLabels[leadingCandidate.action] ??
      formatPublicStatus(leadingCandidate.action, locale))
    : null;
  const decisionCandidateDetail = leadingCandidate
    ? `${decisionActionLabel} · ${decisionCandidateDisplayName(leadingCandidate)}`
    : labels.strategyCandidateEmptyDetail;
  const cashShortfall =
    tradingPlan?.order_intents.find(
      (intent) => (intent.cash_shortfall ?? 0) > 0,
    )?.cash_shortfall ?? 0;
  const tradingPlanTitle = tradingPlanError
    ? labels.tradingPlanUnavailable
    : tradingPlan?.conclusion_status === 'cash_shortfall'
      ? labels.tradingPlanCashShortfall
      : (tradingPlan?.manual_ready_count ?? 0) > 0
        ? labels.tradingPlanManualReady(tradingPlan?.manual_ready_count ?? 0)
        : (tradingPlan?.blocked_count ?? 0) > 0
          ? labels.tradingPlanNeedsReview
          : (tradingPlan?.candidate_pool_count ?? candidates.length) > 0
            ? labels.strategyCandidateAction
            : labels.strategyCandidateClear;
  const tradingPlanDetail = tradingPlanError
    ? labels.tradingPlanUnavailable
    : tradingPlanLoading
      ? labels.tradingPlanLoading
      : tradingPlan?.conclusion_status === 'cash_shortfall'
        ? labels.tradingPlanCashShortfallDetail(
            formatCurrencyValue(cashShortfall),
          )
        : (tradingPlan?.manual_ready_count ?? 0) > 0
          ? tradingPlan && tradingPlan.order_intents.length > 0
            ? tradingPlanManualIntentSummary(
                tradingPlan,
                candidates,
                instrumentDiagnostics,
                locale,
              )
            : labels.tradingPlanManualReadyDetail(
                tradingPlan?.manual_ready_count ?? 0,
              )
          : (tradingPlan?.blocked_count ?? 0) > 0
            ? tradingPlanBlockedDetailText(
                tradingPlan,
                locale,
                labels.tradingPlanBlockedDetail(
                  tradingPlan?.blocked_count ?? 0,
                ),
              )
            : decisionCandidateDetail;
  const tradingPlanBlockerSummary = tradingPlanBlockerSummaryText(
    tradingPlan,
    locale,
  );
  const tradingPlanMeta = tradingPlanLoading
    ? copy.states.loading
    : tradingPlan
      ? tradingPlanBlockerSummary
        ? labels.tradingPlanMeta(
            tradingPlan.manual_ready_count,
            tradingPlan.candidate_pool_count,
            tradingPlanBlockerSummary,
          )
        : labels.tradingPlanMeta(
            tradingPlan.manual_ready_count,
            tradingPlan.candidate_pool_count,
            tradingPlan.blocked_count,
          )
      : labels.candidateCount(candidates.length);
  const tradingPlanTone: TodayQueueTone = tradingPlanError
    ? 'danger'
    : (tradingPlan?.manual_ready_count ?? 0) > 0 ||
        (tradingPlan?.blocked_count ?? 0) > 0 ||
        candidates.length > 0
      ? 'warning'
      : 'success';
  const tradingPlanPriority: TodayQueuePriority =
    tradingPlanError ||
    tradingPlan?.conclusion_status === 'cash_shortfall' ||
    (tradingPlan?.manual_ready_count ?? 0) > 0
      ? 'first'
      : (tradingPlan?.blocked_count ?? 0) > 0 || candidates.length > 0
        ? 'watch'
        : 'normal';
  const operationsPrimarySubsystem =
    operationsToday?.subsystems.find(
      (item) =>
        item.target === operationsToday.primary_target &&
        item.status === operationsToday.conclusion_status,
    ) ??
    operationsToday?.subsystems.find(
      (item) => item.status === operationsToday.conclusion_status,
    );
  const operationsPrimaryTarget = operationsQueueTarget(
    operationsToday,
    operationsPrimarySubsystem,
  );
  const operationsPrimaryAttention =
    operationsToday?.attention_items?.find(
      (item) => item.subsystem_id === operationsPrimarySubsystem?.id,
    ) ??
    operationsToday?.attention_items?.find(
      (item) => item.target === operationsPrimaryTarget,
    );
  const operationsResolution = operationsPrimaryAttention
    ? labels.resolutionCondition(
        operationsAttentionResolutionLabel(
          operationsPrimaryAttention.resolution_condition,
          locale,
        ),
      )
    : undefined;
  const decisionAttention =
    operationsToday?.attention_items?.find(
      (item) => item.subsystem_id === 'daily_trading_plan',
    ) ??
    operationsToday?.attention_items?.find(
      (item) => item.subsystem_id === 'strategy_candidates',
    );
  const decisionResolution = decisionAttention
    ? labels.resolutionCondition(
        operationsAttentionResolutionLabel(
          decisionAttention.resolution_condition,
          locale,
        ),
      )
    : undefined;
  const operationsTone: TodayQueueTone = operationsTodayError
    ? 'danger'
    : operationsToday?.conclusion_status === 'blocked'
      ? 'danger'
      : operationsToday?.conclusion_status === 'manual_action_required' ||
          operationsToday?.conclusion_status === 'degraded'
        ? 'warning'
        : 'success';
  const operationsPriority: TodayQueuePriority =
    operationsTodayError ||
    operationsToday?.conclusion_status === 'blocked' ||
    operationsToday?.conclusion_status === 'manual_action_required'
      ? 'first'
      : operationsToday?.conclusion_status === 'degraded'
        ? 'watch'
        : 'normal';
  const hideDuplicateOperationsReview =
    (dataNeedsReview && operationsPrimaryTarget === 'market') ||
    operationsDuplicatesTradingPlanReview(
      operationsToday,
      tradingPlan,
      operationsPrimarySubsystem,
    );

  const allItems: TodayQueueItem[] = [
    {
      key: 'operations',
      title: operationsTodayError
        ? locale === 'zh'
          ? '运营状态不可用'
          : 'Operations status unavailable'
        : operationsStatusTitle(operationsToday, locale),
      detail: operationsTodayLoading
        ? copy.states.loading
        : operationsToday
          ? operationsDetailText(
              operationsToday,
              locale,
              operationsNextActionLabel(
                operationsPrimaryNextAction(
                  operationsToday,
                  operationsPrimarySubsystem,
                ),
                locale,
              ),
            )
          : copy.states.loading,
      meta: operationsTodayLoading
        ? copy.states.loading
        : operationsToday
          ? operationsStatusMeta(operationsToday, locale)
          : '--',
      href: operationsTargetHref(operationsPrimaryTarget),
      actionLabel: operationsActionLabel(
        operationsToday,
        operationsPrimarySubsystem,
        labels,
        locale,
      ),
      tone: operationsTone,
      priority: operationsPriority,
      resolution: operationsResolution,
    },
    {
      key: 'data',
      title: marketEvidenceReviewLoading
        ? labels.dataReviewLoading
        : dataNeedsReview
          ? labels.dataNeedsReview
          : labels.dataUsable,
      detail: dataDetail,
      meta: dataMeta,
      href: '/market#current-holding-evidence-review',
      actionLabel: labels.viewData,
      tone: dataTone,
      priority: dataPriority,
      resolution:
        dataNeedsReview && !marketEvidenceReviewLoading
          ? labels.dataResolutionCondition
          : undefined,
    },
    {
      key: 'decision',
      title: todayDecisionError
        ? labels.strategyDecisionUnavailable
        : tradingPlanTitle,
      detail:
        todayDecisionLoading || tradingPlanLoading
          ? labels.strategyCandidateLoading
          : tradingPlanDetail,
      meta:
        todayDecisionLoading || tradingPlanLoading
          ? copy.states.loading
          : tradingPlanMeta,
      href: '/decision',
      actionLabel: labels.viewDecision,
      tone: todayDecisionError ? 'danger' : tradingPlanTone,
      priority: todayDecisionError ? 'watch' : tradingPlanPriority,
      resolution:
        todayDecisionLoading || tradingPlanLoading
          ? undefined
          : decisionResolution,
    },
    {
      key: 'orders',
      title: pendingOrdersError
        ? copy.trading.orders.loadFailed
        : pendingOrders.length > 0
          ? labels.pendingOrdersReady
          : labels.pendingOrdersClear,
      detail: pendingOrdersLoading
        ? copy.trading.orders.loading
        : pendingOrders.length > 0
          ? labels.pendingCount(pendingOrders.length)
          : labels.pendingEmptyDetail,
      meta: pendingOrdersLoading
        ? copy.states.loading
        : labels.pendingCount(pendingOrders.length),
      href: '/trading',
      actionLabel: labels.viewTrading,
      tone: pendingOrdersError
        ? 'danger'
        : pendingOrders.length > 0
          ? 'warning'
          : 'success',
      priority:
        pendingOrdersError || pendingOrders.length > 0 ? 'first' : 'normal',
    },
    {
      key: 'strategy',
      title: strategyContributionLoading
        ? copy.backtest.page.accountStrategyContributionLoading
        : strategyContributionError
          ? labels.strategyUnavailable
          : strategyReady
            ? labels.strategyEvidenceLinked
            : strategyHasNoLinkedFills
              ? labels.strategyNoLinkedFills
              : labels.strategyEvidenceRequired,
      detail: strategyContributionLoading
        ? copy.backtest.page.accountStrategyContributionLoading
        : strategyReady && strategyContribution
          ? `${copy.backtest.page.accountStrategyNetContribution}: ${formatCurrencyValue(
              strategyContribution.net_contribution,
            )}`
          : strategyNextAction,
      meta: strategyContributionLoading ? copy.states.loading : strategyStatus,
      href: strategyHref,
      actionLabel: strategyActionLabel,
      tone: strategyContributionError
        ? 'danger'
        : strategyContributionLoading
          ? 'neutral'
          : strategyReady || strategyHasNoLinkedFills
            ? 'success'
            : 'warning',
      priority: strategyContributionError
        ? 'watch'
        : strategyContributionLoading
          ? 'normal'
          : strategyReady || strategyHasNoLinkedFills
            ? 'normal'
            : 'watch',
      resolution: strategyContributionLoading
        ? undefined
        : strategyHasNoLinkedFills
          ? labels.strategyNoLinkedFillsResolution
          : strategyReady
            ? undefined
            : labels.strategyEvidenceResolution,
    },
  ];
  const items = allItems.filter(
    (item) => !(hideDuplicateOperationsReview && item.key === 'operations'),
  );
  const actionableCount = items.filter(
    (item) => item.priority !== 'normal',
  ).length;
  const exceptionItems: ExceptionItem[] = items
    .filter((item) => item.priority !== 'normal')
    .sort(
      (left, right) =>
        TODAY_QUEUE_PRIORITY_ORDER.indexOf(left.priority) -
        TODAY_QUEUE_PRIORITY_ORDER.indexOf(right.priority),
    )
    .map((item) => ({
      id: item.key,
      severity:
        item.tone === 'danger'
          ? 'danger'
          : item.tone === 'warning'
            ? 'warning'
            : 'info',
      statusLabel: todayQueuePriorityLabel(item.priority, labels),
      title: item.title,
      reason: item.detail,
      unblockCondition: item.resolution,
      nextAction:
        item.key === 'data' && dataRefreshSymbols.length > 0 ? (
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
            <MarketRefreshButton compact symbols={dataRefreshSymbols} />
            <a
              href={item.href}
              className="inline-flex min-h-8 items-center font-semibold text-[var(--app-accent)] hover:underline"
            >
              {item.actionLabel}
            </a>
          </div>
        ) : (
          <a
            href={item.href}
            className="font-semibold text-[var(--app-accent)] hover:underline"
          >
            {item.actionLabel}
          </a>
        ),
      evidence: item.meta,
    }));
  const normalCount = items.length - actionableCount;
  const primaryExceptionItems = exceptionItems.slice(0, 1);
  const additionalExceptionItems = exceptionItems.slice(1);
  const exceptionLabels =
    locale === 'zh'
      ? {
          reason: '阻断原因',
          unblockCondition: '解除条件',
          nextAction: '安全下一步',
          evidence: '证据',
        }
      : {
          reason: 'Reason',
          unblockCondition: 'Unblock condition',
          nextAction: 'Safe next step',
          evidence: 'Evidence',
        };

  return (
    <section className="min-w-0" data-testid="overview-today-queue">
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {labels.dailyWorkbench}
          </div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {labels.todayToReview}
          </h2>
        </div>
        <span className="text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]">
          {actionableCount}
        </span>
      </div>
      <ExceptionList
        items={primaryExceptionItems}
        ariaLabel={labels.todayToReview}
        emptyState={labels.noActionItems}
        density="compact"
        className="app-overview-primary-exception"
        labels={exceptionLabels}
      />
      {additionalExceptionItems.length > 0 ? (
        <details
          data-testid="overview-today-queue-more"
          className="group border-b border-[var(--app-divider)]"
        >
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
            <span>
              {labels.additionalReviewItems(additionalExceptionItems.length)}
            </span>
            <ChevronDown
              className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"
              aria-hidden="true"
            />
          </summary>
          <ExceptionList
            items={additionalExceptionItems}
            ariaLabel={labels.additionalReviewItems(
              additionalExceptionItems.length,
            )}
            emptyState={labels.noActionItems}
            density="compact"
            className="border-b-0"
            labels={exceptionLabels}
          />
        </details>
      ) : null}
      {normalCount > 0 ? (
        <div
          data-testid="overview-today-queue-normal"
          className="mt-2 border-y border-[var(--app-divider)] px-3 py-2 text-xs text-[var(--app-text-tertiary)]"
        >
          {todayQueuePriorityLabel('normal', labels)} · {normalCount}
        </div>
      ) : null}
    </section>
  );
}

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
  if (value > 0) {
    return `+${absolute}`;
  }
  if (value < 0) {
    return `-${absolute}`;
  }
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
  if (quotes.length === 0) {
    return labels.marketPulsePending;
  }
  if (changes.length === 0) {
    return labels.marketPulseNoSignal;
  }
  const positiveCount = changes.filter((value) => value > 0).length;
  const negativeCount = changes.filter((value) => value < 0).length;
  if (positiveCount > negativeCount) {
    return labels.marketPulsePositive;
  }
  if (negativeCount > positiveCount) {
    return labels.marketPulseNegative;
  }
  return labels.marketPulseMixed;
}

function DashboardMarketPulse({
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
  const marketPulseCoverageLabel =
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
                  detail: marketPulseCoverageLabel,
                  tone: missingChangeCount > 0 ? 'warning' : 'neutral',
                },
              ]}
            />
            <div className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
              {indexQuotes.map((quote) => {
                const changeValue = marketPulseSignalValue(quote);
                const changeMissing = changeValue === null;
                const changeAmount = marketPulseChangeAmount(quote);
                const changePct = marketPulseChangePct(quote);
                const displayName = marketIndexDisplayName(quote, locale);
                const quoteStatus = formatPublicStatus(
                  quote.quote_status,
                  locale,
                );
                return (
                  <a
                    href={`/market?symbol=${encodeURIComponent(quote.symbol)}`}
                    key={quote.symbol}
                    className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-2 py-2 hover:bg-[var(--app-accent-bg)]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                        {displayName}
                      </div>
                      <div className="app-type-micro mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[var(--app-text-tertiary)]">
                        <span className="font-mono">{quote.symbol}</span>
                        <span>{quoteStatus}</span>
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
              })}
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

function DashboardPendingOrders({
  orders,
  isLoading,
  isError,
  copy,
}: {
  orders: ManualOrder[];
  isLoading: boolean;
  isError: boolean;
  copy: AppCopy;
}) {
  const { locale } = usePreferences();
  if (isLoading) {
    return <EvidenceState kind="loading" title={copy.trading.orders.loading} />;
  }

  if (isError) {
    return (
      <EvidenceState kind="error" title={copy.trading.orders.loadFailed} />
    );
  }

  if (orders.length === 0) {
    return (
      <EvidenceState
        kind="empty"
        title={copy.overview.dashboard.pendingEmpty}
        description={copy.overview.dashboard.pendingEmptyDetail}
      />
    );
  }

  return (
    <div className="max-h-[270px] divide-y divide-[var(--app-divider)] overflow-y-auto border-y border-[var(--app-divider)]">
      {orders.map((order) => {
        const normalizedSide = order.side.toLowerCase();
        const isBuy = normalizedSide === 'buy';
        const isSell = normalizedSide === 'sell';
        const sideToneClass = isBuy
          ? 'border-[color-mix(in_srgb,var(--app-chart-buy)_56%,transparent)] text-[var(--app-chart-buy)]'
          : isSell
            ? 'border-[color-mix(in_srgb,var(--app-chart-sell)_56%,transparent)] text-[var(--app-chart-sell)]'
            : 'border-[var(--app-warning-border)] text-[var(--app-warning-text)]';
        const sideLabel = formatLedgerOrderSideLabel(order.side, locale);
        const displayName = order.display_name ?? order.name ?? null;
        const instrumentNames = displayName
          ? new Map([[order.symbol.toLowerCase(), displayName]])
          : undefined;
        const instrumentLabel = formatInstrumentDisplayLabelFromNameMap(
          order.symbol,
          instrumentNames,
        );
        return (
          <div
            key={order.order_id}
            className="px-2 py-2.5 transition-colors hover:bg-[var(--app-accent-bg)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="app-type-subsection-title truncate">
                  {instrumentLabel}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {formatTimestamp(order.timestamp)}
                </div>
              </div>
              <div
                className={`rounded-[var(--app-radius-control)] border bg-transparent px-2 py-1 text-xs font-semibold ${sideToneClass}`}
              >
                {sideLabel}
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3 text-xs tabular-nums">
              <MetricLine
                label={copy.trading.orders.quantity}
                value={formatQuantity(order.quantity)}
              />
              <MetricLine
                label={copy.trading.orders.price}
                value={formatPrice(order.price)}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DashboardLedger({
  entries,
  isLoading,
  isError,
  copy,
}: {
  entries: LedgerEntry[];
  isLoading: boolean;
  isError: boolean;
  copy: AppCopy;
}) {
  const { locale } = usePreferences();
  return (
    <div className="mt-4 border-t border-[var(--app-divider)] pt-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {copy.overview.dashboard.ledgerPanel}
        </div>
        <div className="shrink-0 text-xs font-medium text-[var(--app-text-tertiary)] tabular-nums">
          {copy.overview.dashboard.ledgerCount(entries.length)}
        </div>
      </div>
      {isLoading ? (
        <EvidenceState kind="loading" title={copy.states.loading} />
      ) : isError ? (
        <EvidenceState kind="error" title={copy.states.error} />
      ) : entries.length === 0 ? (
        <EvidenceState
          kind="empty"
          title={copy.overview.dashboard.ledgerEmpty}
        />
      ) : (
        <div className="max-h-[340px] divide-y divide-[var(--app-divider)] overflow-y-auto border-y border-[var(--app-divider)]">
          {entries.map((entry) => {
            const presentation = formatLedgerDashboardPresentation(
              entry,
              copy.activity.feed.detailFields,
              locale,
              formatAssetClassLabel(entry.asset_class, copy.common),
            );
            return (
              <div
                key={entry.id}
                className="px-2 py-2.5 transition-colors hover:bg-[var(--app-accent-bg)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">
                      {presentation.title}
                    </div>
                    <div className="app-muted mt-1 text-xs">
                      {formatTimestamp(entry.timestamp)}
                    </div>
                    <div className="app-muted mt-2 flex flex-wrap gap-x-2 gap-y-1 text-xs">
                      {presentation.details.map((detail) => (
                        <span key={detail}>{detail}</span>
                      ))}
                    </div>
                    {presentation.publicNote ? (
                      <div className="app-muted mt-2 break-words text-xs leading-5">
                        {presentation.publicNote}
                      </div>
                    ) : null}
                  </div>
                  <div
                    className="shrink-0 whitespace-nowrap text-right font-mono text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]"
                    data-testid={`dashboard-ledger-amount-${entry.id}`}
                  >
                    {presentation.amount}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <dl className="min-w-0">
      <dt className="text-[length:var(--app-font-size-micro)] font-medium text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd className="mt-0.5 truncate font-mono font-semibold text-[var(--app-text)]">
        {value}
      </dd>
    </dl>
  );
}

function StatusCard({
  title,
  detail,
  tone = 'default',
  actionLabel,
  onAction,
}: {
  title: string;
  detail: string;
  tone?: 'default' | 'danger';
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div
      className={
        tone === 'danger'
          ? 'app-panel-danger rounded-3xl p-4 sm:p-5'
          : 'app-terminal-panel rounded-3xl p-4 sm:p-5'
      }
    >
      <div className="app-type-subsection-title">{title}</div>
      <div className="mt-2 text-sm opacity-80">{detail}</div>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="app-button-secondary mt-4 rounded-2xl px-4 py-2 text-sm"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function getEquityCurveErrorDetail(error: unknown, copy: AppCopy) {
  const detail = getErrorMessage(error);
  if (
    detail.includes(
      'Current valuation facts have not been published as an immutable snapshot',
    )
  ) {
    return copy.overview.curveSnapshotPending;
  }
  return `${copy.overview.curveError} ${detail}`;
}
