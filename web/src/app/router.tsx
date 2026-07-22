import { useCallback, useMemo, useState, type ReactNode } from 'react';
import {
  createRoute,
  createRootRoute,
  createRouter,
  Outlet,
  useNavigate,
  useRouterState,
} from '@tanstack/react-router';
import {
  BarChart3,
  CalendarDays,
  CircleDollarSign,
  Percent,
  Table2,
} from 'lucide-react';

import { useCopy, type AppCopy } from './copy';
import { ToastStack, type ToastItem } from './components/toast-stack';
import {
  ControlledActionZone,
  EvidenceIdentityDisclosure,
  EvidenceState,
  ExceptionList,
  FilterBar,
  MetricStrip,
  StatusBadge,
  Timeline,
  WorkspaceHeader,
  type ExceptionItem,
} from './components/workbench';
import { AppShell } from './layout/app-shell';
import { usePreferences, type Locale } from './preferences';
import {
  type AccountOverview,
  useAccountOverviewQuery,
  type EquityCurveRange,
  useAccountStateQuery,
  useExplainabilityQuery,
  useEquityCurveSeriesQuery,
  useRiskSummaryQuery,
  useRiskWorkspaceQuery,
} from '../features/account/api';
import {
  EquityCurveCard,
  EquityCurveSkeleton,
} from '../features/account/components/equity-curve-card';
import type { QuoteDiagnosticItem } from '../features/account/components/dashboard-quick-actions';
import {
  useAccountStrategyContributionQuery,
  type AccountStrategyContributionReport,
} from '../features/account-strategy/api';
import { StrategyContributionGateCard } from '../features/account-strategy/components/strategy-contribution-gate-card';
import { AccountTruthReviewPage } from '../features/account-truth/components/account-truth-review-page';
import { BacktestPage } from '../features/backtest/components/backtest-page';
import {
  type DailyTradingPlanResponse,
  useTodayDecisionQuery,
  useDailyTradingPlanQuery,
  useBatchPreTradeRiskMutation,
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
  OverviewCardsSkeleton,
} from '../features/account/components/overview-cards';
import { PortfolioExposureSummary } from '../features/account/components/portfolio-exposure-summary';
import { KillSwitchPanel } from '../features/trading/components/kill-switch-panel';
import { OrderApprovalTable } from '../features/trading/components/order-approval-table';
import { TradingPage } from '../features/trading/components/trading-page';
import { PublicHomePage } from '../features/home/components/public-home-page';
import {
  usePendingManualOrdersQuery,
  type ManualOrder,
} from '../features/trading/api';
import {
  MARKET_CALENDAR_SCHEMA_VERSION,
  explainMarketCalendarDate,
  type MarketCalendarDay,
} from '../shared/market-calendar';
import { useSettingsQuery } from '../features/settings/api';
import {
  useCreateAdjustmentMutation,
  useCreateCashFlowMutation,
  useCreateDividendMutation,
  useCreateTradeMutation,
  useLedgerEntriesQuery,
  usePendingFundOrdersQuery,
  useTradePreviewMutation,
  type LedgerEntry,
} from '../features/activity/api';
import {
  formatLedgerDashboardPresentation,
  formatLedgerExplainabilityDetail,
  formatLedgerExplainabilityTitle,
  formatLedgerOrderSideLabel,
} from '../shared/ledger-format';
import { ActivityFeed } from '../features/activity/components/activity-feed';
import {
  CashFlowForm,
  type CashFlowFormValues,
} from '../features/activity/components/cash-flow-form';
import {
  DividendForm,
  type DividendFormValues,
} from '../features/activity/components/dividend-form';
import {
  ManualAdjustmentForm,
  type ManualAdjustmentFormValues,
} from '../features/activity/components/manual-adjustment-form';
import {
  TradeForm,
  type TradeFormValues,
} from '../features/activity/components/trade-form';
import {
  FundBatchForm,
  type FundBatchCandidate,
  type FundBatchFormValues,
} from '../features/activity/components/fund-batch-form';
import {
  type CurrentHoldingMarketEvidenceReview,
  type PortfolioSnapshot,
  type PositionEvidenceReview,
  useCurrentHoldingMarketEvidenceReviewQuery,
  useLiveHoldingsQuery,
  usePortfolioCockpitQuery,
  usePortfolioSnapshotQuery,
  usePositionsQuery,
} from '../features/portfolio/api';
import { AllocationCard } from '../features/portfolio/components/allocation-card';
import { AllocationGroupsCard } from '../features/portfolio/components/allocation-groups-card';
import { LiveHoldingsBoard } from '../features/portfolio/components/live-holdings-board';
import { PortfolioConstructionRecommendationsCard } from '../features/portfolio/components/portfolio-construction-recommendations-card';
import { filterAndSortPortfolioPositions } from '../features/portfolio/position-observation';
import { HoldingDetailPage } from '../features/portfolio/components/holding-detail-page';
import { PositionsTable } from '../features/portfolio/components/positions-table';
import {
  WorkspaceToolbar,
  type EvidenceFilter,
  type PositionSort,
  type QuoteFilter,
} from '../features/portfolio/components/workspace-toolbar';
import {
  useAddWatchlistItemMutation,
  useCreateResearchNoteMutation,
  useUpdateResearchNoteMutation,
  useDeleteResearchNoteMutation,
  useInstrumentMetadataBackfillMutation,
  useKlineQuery,
  useMarketBarsBackfillMutation,
  useMarketCalendarQuery,
  useMarketDataHealthQuery,
  type MarketCalendarSnapshot,
  type MarketDataHealthResponse,
  type MarketHealthQuote,
  useQuoteFetchRunsQuery,
  useResearchBoardQuery,
  useResearchNotesQuery,
  useRemoveWatchlistItemMutation,
  type QuoteFetchRun,
} from '../features/market/api';
import { CurrentHoldingMarketEvidenceReviewPanel } from '../features/market/components/current-holding-market-evidence-review-panel';
import { MarketRefreshButton } from '../features/market/components/market-refresh-button';
import { PriceStructureChart } from '../features/market/components/price-structure-chart';
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
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicStatus,
} from '../shared/public-labels';
import { formatStaleReason } from '../shared/stale-reason';
import {
  formatMarketDataStatusNextAction,
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  isUnconfirmedMarketDataStatus,
} from '../shared/market-data-status';

type PortfolioSearchState = {
  assetClass: string;
  pnl: 'all' | 'winners' | 'losers';
  q: string;
};

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
  component: PortfolioPage,
});

const holdingDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/portfolio/$symbol',
  component: HoldingDetailRoutePage,
});

const activityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/activity',
  component: ActivityPage,
});

const riskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/risk',
  component: RiskPage,
});

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
  component: MarketPage,
});

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
  const overview = useAccountOverviewQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const equityCurve = useEquityCurveSeriesQuery(equityCurveRange);
  const explainability = useExplainabilityQuery();
  const ledgerEntries = useLedgerEntriesQuery(8);
  const pendingOrders = usePendingManualOrdersQuery();
  const marketHealth = useMarketDataHealthQuery();
  const holdingMarketEvidenceReview =
    useCurrentHoldingMarketEvidenceReviewQuery();
  const strategyContribution = useAccountStrategyContributionQuery();
  const todayDecision = useTodayDecisionQuery();
  const tradingPlan = useDailyTradingPlanQuery();
  const operationsToday = useOperationsTodayQuery();
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

      {overview.isLoading || snapshot.isLoading ? (
        <div className="space-y-5">
          <OverviewCardsSkeleton />
          <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[2rem] p-1.5">
            <div className="app-terminal-inner min-w-0 p-4 sm:p-5">
              <EquityCurveSkeleton />
            </div>
          </section>
        </div>
      ) : overview.isError || snapshot.isError ? (
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
      ) : overview.data && snapshot.data ? (
        <div className="space-y-5">
          <OverviewCards
            overview={overview.data}
            variant="workbench"
            todayPnlLabel={todayPnlLabel}
            todayPnlContext={todayPnlContext}
          />

          <div
            className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,0.7fr)]"
            data-testid="overview-daily-workbench"
          >
            <section
              className="min-w-0"
              data-testid="overview-holdings-section"
            >
              <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h2 className="text-base font-semibold text-[var(--app-text)]">
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
                />
              )}
            </section>
            <div className="min-w-0">
              <DashboardTodayQueue
                overview={overview.data}
                marketHealth={marketHealth.data}
                portfolioSnapshot={snapshot.data}
                marketEvidenceReview={holdingMarketEvidenceReview.data}
                marketEvidenceReviewLoading={
                  holdingMarketEvidenceReview.isLoading
                }
                marketEvidenceReviewError={holdingMarketEvidenceReview.isError}
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
          </div>

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
                equityCurve.isLoading ? (
                  <EquityCurveSkeleton />
                ) : equityCurve.isError ? (
                  <StatusCard
                    tone="danger"
                    title={copy.states.error}
                    detail={copy.overview.curveError}
                    actionLabel={copy.states.retry}
                    onAction={() => void equityCurve.refetch()}
                  />
                ) : (
                  <EquityCurveCard
                    points={equityCurve.data ?? []}
                    range={equityCurveRange}
                    onRangeChange={setEquityCurveRange}
                  />
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
                <h2 className="text-base font-semibold text-[var(--app-text)]">
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
        </div>
      ) : (
        <StatusCard title={copy.states.empty} detail={copy.overview.empty} />
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
      title: strategyContributionError
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
        : strategyReady || strategyHasNoLinkedFills
          ? 'success'
          : 'warning',
      priority: strategyContributionError
        ? 'watch'
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
      nextAction: (
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

  return (
    <section className="min-w-0" data-testid="overview-today-queue">
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
            {labels.dailyWorkbench}
          </div>
          <h2 className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {labels.todayToReview}
          </h2>
        </div>
        <span className="text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]">
          {actionableCount}
        </span>
      </div>
      <ExceptionList
        items={exceptionItems}
        ariaLabel={labels.todayToReview}
        emptyState={labels.noActionItems}
        labels={
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
              }
        }
      />
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
          <h2 className="text-sm font-semibold text-[var(--app-text)]">
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
                  value: signalLabel,
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
                      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--app-text-tertiary)]">
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
                          className={`font-mono text-[10px] font-semibold tabular-nums ${marketPulseToneClass(
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
              <div className="mt-1 text-[11px] leading-5 text-[var(--app-text-secondary)]">
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
        const instrumentLabel = formatInstrumentDisplayLabel(
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
                <div className="truncate text-base font-semibold tracking-[-0.02em]">
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
      <dt className="text-[10px] font-medium text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd className="mt-0.5 truncate font-mono font-semibold text-[var(--app-text)]">
        {value}
      </dd>
    </dl>
  );
}

function PortfolioEvidenceReviewPanel({
  items,
}: {
  items: PositionEvidenceReview[];
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  if (items.length === 0) {
    return null;
  }
  return (
    <section
      data-testid="portfolio-position-evidence-review"
      className="min-w-0"
    >
      <div className="mb-2 flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--app-text)]">
            {copy.portfolio.evidenceReview.title}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.portfolio.evidenceReview.detail}
          </p>
        </div>
        <span className="text-xs font-semibold tabular-nums text-[var(--app-warning-text)]">
          {copy.portfolio.evidenceReview.count(items.length)}
        </span>
      </div>
      <ExceptionList
        ariaLabel={copy.portfolio.evidenceReview.title}
        emptyState={copy.portfolio.evidenceReview.detail}
        items={items.map((item) => ({
          id: item.position.symbol,
          severity: 'warning',
          statusLabel: locale === 'zh' ? '待复核' : 'Review',
          title:
            item.position.display_name ??
            item.position.name ??
            item.position.symbol,
          reason: item.reason_codes
            .map((reason) => formatPublicCode(reason, locale))
            .join(' · '),
          nextAction: (
            <a
              href="/account-truth"
              className="font-semibold text-[var(--app-accent)] hover:underline"
            >
              {locale === 'zh' ? '复核账户事实' : 'Review account truth'}
            </a>
          ),
          evidence: item.position.symbol,
        }))}
        labels={
          locale === 'zh'
            ? {
                reason: '原因',
                unblockCondition: '解除条件',
                nextAction: '安全下一步',
                evidence: '标的',
              }
            : {
                reason: 'Reason',
                unblockCondition: 'Unblock condition',
                nextAction: 'Safe next step',
                evidence: 'Instrument',
              }
        }
      />
    </section>
  );
}

export function PortfolioPage() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const navigate = useNavigate();
  const searchState = portfolioRoute.useSearch();
  const [mode, setMode] = useState<'account' | 'strategy'>('account');
  const [quoteFilter, setQuoteFilter] = useState<QuoteFilter>('all');
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>('all');
  const [sortBy, setSortBy] = useState<PositionSort>('market_value');
  const positions = usePositionsQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const cockpit = usePortfolioCockpitQuery();
  const liveHoldings = useLiveHoldingsQuery();
  const strategyContribution = useAccountStrategyContributionQuery();
  const search = searchState.q;
  const assetClassFilter = searchState.assetClass;
  const pnlFilter = searchState.pnl as 'all' | 'winners' | 'losers';

  const allocationBySymbol = new Map(
    (snapshot.data?.allocation ?? []).map((item) => [item.symbol, item]),
  );
  const evidenceReviewItems = snapshot.data?.position_review_items ?? [];
  const evidenceReviewSymbols = new Set(
    evidenceReviewItems.map((item) => item.position.symbol),
  );
  const assetClasses = Array.from(
    new Set((snapshot.data?.allocation ?? []).map((item) => item.asset_class)),
  );
  const filteredPositions = filterAndSortPortfolioPositions({
    positions: positions.data ?? [],
    allocation: snapshot.data?.allocation ?? [],
    search,
    assetClassFilter,
    pnlFilter,
    quoteFilter,
    evidenceFilter,
    evidenceReviewSymbols,
    sortBy,
  });

  const closedPositions = snapshot.data?.closed_positions ?? [];
  const portfolioIdentity = snapshot.data
    ? copy.common.valuationEvidenceAsOf(
        formatTimestamp(snapshot.data.valuation_as_of),
        formatPublicStatus(snapshot.data.valuation_status, locale),
      )
    : undefined;

  return (
    <section className="space-y-4 sm:space-y-5">
      <WorkspaceHeader
        eyebrow={copy.portfolio.kicker}
        title={copy.portfolio.title}
        description={copy.portfolio.subtitle}
        context={portfolioIdentity}
        actions={
          snapshot.data ? (
            <EvidenceIdentityDisclosure
              triggerLabel={copy.common.viewEvidenceIdentity}
              title={copy.common.evidenceIdentityTitle}
              description={copy.common.evidenceIdentityDescription}
              closeLabel={copy.common.closeEvidenceIdentity}
              copyLabel={copy.common.copyEvidenceValue}
              copiedLabel={copy.common.evidenceValueCopied}
              fields={[
                {
                  label: copy.common.valuationSnapshot,
                  value: snapshot.data.valuation_snapshot_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.ledgerCutoff,
                  value: snapshot.data.ledger_cutoff_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.valuationAsOf,
                  value: formatTimestamp(snapshot.data.valuation_as_of),
                  mono: true,
                },
                {
                  label: copy.common.valuationStatus,
                  value: formatPublicStatus(
                    snapshot.data.valuation_status,
                    locale,
                  ),
                },
              ]}
            />
          ) : undefined
        }
      />

      <WorkspaceToolbar
        mode={mode}
        onModeChange={setMode}
        search={search}
        onSearchChange={(value) => {
          void navigate({
            to: '/portfolio',
            search: (current: PortfolioSearchState) => ({
              ...current,
              q: value,
            }),
            replace: true,
          });
        }}
        assetClassFilter={assetClassFilter}
        onAssetClassFilterChange={(value) => {
          void navigate({
            to: '/portfolio',
            search: (current: PortfolioSearchState) => ({
              ...current,
              assetClass: value,
            }),
          });
        }}
        pnlFilter={pnlFilter}
        onPnlFilterChange={(value) => {
          void navigate({
            to: '/portfolio',
            search: (current: PortfolioSearchState) => ({
              ...current,
              pnl: value,
            }),
          });
        }}
        assetClasses={assetClasses}
        quoteFilter={quoteFilter}
        onQuoteFilterChange={setQuoteFilter}
        evidenceFilter={evidenceFilter}
        onEvidenceFilterChange={setEvidenceFilter}
        sortBy={sortBy}
        onSortByChange={setSortBy}
        summary={`${copy.portfolio.currentHoldingsCount(
          (positions.data ?? []).length,
        )} · ${copy.portfolio.filteredHoldingsCount(filteredPositions.length)}`}
      />

      {evidenceFilter !== 'clear' ? (
        <PortfolioEvidenceReviewPanel items={evidenceReviewItems} />
      ) : null}

      <div data-testid="portfolio-current-holdings-count" className="sr-only">
        {copy.portfolio.currentHoldingsCount((positions.data ?? []).length)} ·{' '}
        {copy.portfolio.filteredHoldingsCount(filteredPositions.length)}
      </div>
      {positions.isLoading ? (
        <StatusCard
          title={copy.states.loading}
          detail={copy.portfolio.positionsLoading}
        />
      ) : positions.isError ? (
        <StatusCard
          tone="danger"
          title={copy.states.error}
          detail={copy.portfolio.positionsError}
          actionLabel={copy.states.retry}
          onAction={() => void positions.refetch()}
        />
      ) : filteredPositions.length === 0 ? (
        <StatusCard
          title={copy.states.empty}
          detail={
            (positions.data ?? []).length === 0
              ? copy.portfolio.positionsEmpty
              : copy.portfolio.filterEmpty
          }
        />
      ) : (
        <PositionsTable
          positions={filteredPositions}
          assetClassBySymbol={Object.fromEntries(
            Array.from(allocationBySymbol.entries()).map(([symbol, item]) => [
              symbol,
              item.asset_class,
            ]),
          )}
          weightBySymbol={Object.fromEntries(
            Array.from(allocationBySymbol.entries()).map(([symbol, item]) => [
              symbol,
              item.weight,
            ]),
          )}
        />
      )}

      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        {mode === 'account' ? (
          <div className="min-w-0 space-y-4">
            {liveHoldings.isLoading ? (
              <StatusCard
                title={copy.states.loading}
                detail={copy.portfolio.liveBoard.loading}
              />
            ) : liveHoldings.isError ? (
              <StatusCard
                tone="danger"
                title={copy.states.error}
                detail={copy.portfolio.liveBoard.error}
                actionLabel={copy.states.retry}
                onAction={() => void liveHoldings.refetch()}
              />
            ) : (
              <LiveHoldingsBoard groups={liveHoldings.data?.groups ?? []} />
            )}
            {snapshot.data ? (
              <AllocationGroupsCard groups={snapshot.data.allocation_grouped} />
            ) : null}
          </div>
        ) : (
          <div className="min-w-0 space-y-4">
            <StrategyContributionGateCard
              report={strategyContribution.data}
              isLoading={strategyContribution.isLoading}
              isError={strategyContribution.isError}
              onRetry={() => void strategyContribution.refetch()}
              instruments={positions.data ?? snapshot.data?.positions ?? []}
            />
            <PortfolioConstructionRecommendationsCard
              recommendations={cockpit.data?.construction_recommendations ?? []}
              isLoading={cockpit.isLoading}
              isError={cockpit.isError}
              onRetry={() => void cockpit.refetch()}
            />
          </div>
        )}

        <div className="min-w-0 space-y-4">
          {snapshot.isLoading ? (
            <StatusCard
              title={copy.states.loading}
              detail={copy.portfolio.sidebarLoading}
            />
          ) : snapshot.isError ? (
            <StatusCard
              tone="danger"
              title={copy.states.error}
              detail={copy.portfolio.sidebarError}
              actionLabel={copy.states.retry}
              onAction={() => void snapshot.refetch()}
            />
          ) : snapshot.data ? (
            <>
              <AllocationCard items={snapshot.data.allocation} />
            </>
          ) : (
            <StatusCard
              title={copy.states.empty}
              detail={copy.portfolio.sidebarEmpty}
            />
          )}
        </div>
      </div>

      <section className="min-w-0" data-testid="portfolio-history">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--app-text)]">
              {copy.portfolio.detail.closedHistoryOnly}
            </h2>
            <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
              {copy.portfolio.detail.realizedPnl}:{' '}
              {formatCurrencyValue(snapshot.data?.realized_pnl_total)}
            </p>
          </div>
          <a
            href="/activity"
            className="app-button-secondary inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold"
          >
            {copy.portfolio.detail.actionViewActivity}
          </a>
        </div>
        {closedPositions.length > 0 ? (
          <PositionsTable positions={closedPositions} variant="history" />
        ) : (
          <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
            {copy.portfolio.detail.noLedger}
          </div>
        )}
      </section>
    </section>
  );
}

export function RiskPage() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const state = useAccountStateQuery();
  const risks = useRiskSummaryQuery();
  const workspace = useRiskWorkspaceQuery();
  const todayDecision = useTodayDecisionQuery();
  const batchPreTradeRisk = useBatchPreTradeRiskMutation();
  const [timelineFromDate, setTimelineFromDate] = useState('');
  const [timelineToDate, setTimelineToDate] = useState('');
  const [timelineEventKind, setTimelineEventKind] = useState('');
  const [batchRiskMessage, setBatchRiskMessage] = useState<string | null>(null);
  const [batchRiskBlockedMessage, setBatchRiskBlockedMessage] = useState<
    string | null
  >(null);
  const [batchRiskError, setBatchRiskError] = useState<string | null>(null);
  const explainability = useExplainabilityQuery({
    from_date: timelineFromDate || undefined,
    to_date: timelineToDate || undefined,
    event_kind: timelineEventKind || undefined,
  });
  const instrumentNames = useMemo(() => {
    const names = new Map<string, string>();
    const remember = (
      symbol: string | null | undefined,
      displayName: string | null | undefined,
    ) => {
      const normalizedSymbol = symbol?.trim();
      const normalizedName = displayName?.trim();
      if (!normalizedSymbol || !normalizedName) {
        return;
      }
      names.set(normalizedSymbol.toLowerCase(), normalizedName);
    };
    const snapshot = state.data?.snapshot;
    snapshot?.allocation.forEach((item) => remember(item.symbol, item.name));
    snapshot?.allocation_grouped.forEach((group) =>
      group.items.forEach((item) => remember(item.symbol, item.name)),
    );
    snapshot?.positions.forEach((position) =>
      remember(position.symbol, position.display_name ?? position.name),
    );
    return names;
  }, [state.data?.snapshot]);
  const riskReviewTask = todayDecision.data?.summary.workflow_tasks?.find(
    (task) =>
      task.id === 'risk_review' &&
      task.required_actions.includes('run_pre_trade_risk_gate') &&
      task.status !== 'pass' &&
      task.status !== 'passed',
  );
  const riskReviewEvidence = riskReviewTask?.evidence as
    | {
        total_action_count?: number;
        risk_checked_count?: number;
        risk_blocked_count?: number;
      }
    | undefined;
  const riskCandidateCount =
    riskReviewEvidence?.total_action_count ??
    todayDecision.data?.summary.candidate_count ??
    0;
  const riskCheckedCount = riskReviewEvidence?.risk_checked_count ?? 0;
  const isInitialRiskLoad =
    (!state.data && state.isLoading) ||
    (!risks.data && risks.isLoading) ||
    (!workspace.data && workspace.isLoading);
  const isRiskWorkspaceUnavailable = !state.data || !workspace.data;
  const hasRiskRefreshError =
    !isRiskWorkspaceUnavailable &&
    (state.isError || risks.isError || workspace.isError);
  const representedRiskMetricKeys = new Set<string>();
  const activeRiskItems: ExceptionItem[] = [];
  for (const item of risks.data ?? []) {
    if (item.level !== 'high' && item.level !== 'medium') {
      continue;
    }
    switch (item.kind) {
      case 'cash_buffer':
        representedRiskMetricKeys.add('cash_ratio');
        break;
      case 'concentration':
        representedRiskMetricKeys.add('largest_weight');
        representedRiskMetricKeys.add('top3_weight');
        break;
      case 'largest_weight':
      case 'gross_exposure':
      case 'current_drawdown':
      case 'max_drawdown':
        representedRiskMetricKeys.add(item.kind);
        break;
      case 'capital_deployment':
        representedRiskMetricKeys.add('gross_exposure');
        break;
    }
    activeRiskItems.push({
      id: `${item.kind}-${item.title}`,
      severity: item.level === 'high' ? 'danger' : 'warning',
      statusLabel: formatRiskAlertLevel(item.level, locale),
      title: item.title,
      reason: formatRiskAlertDetail(item.detail, locale),
      unblockCondition: copy.riskPage.clearsWithNewProjection,
      nextAction: state.data?.next_step,
      evidence: `${getRiskAlertKindLabel(
        copy,
        item.kind,
      )} · ${formatRiskAlertLevel(item.level, locale)}`,
    });
  }
  for (const metric of workspace.data?.metrics ?? []) {
    if (
      (metric.level !== 'high' && metric.level !== 'medium') ||
      representedRiskMetricKeys.has(metric.key)
    ) {
      continue;
    }
    activeRiskItems.push({
      id: `metric-${metric.key}`,
      severity: metric.level === 'high' ? 'danger' : 'warning',
      statusLabel: formatRiskAlertLevel(metric.level, locale),
      title: getRiskMetricLabel(copy, metric.key),
      reason: `${metric.display_value} · ${getRiskMetricDetail(
        copy,
        metric.key,
      )}`,
      unblockCondition: copy.riskPage.clearsWithNewProjection,
      nextAction: state.data?.next_step,
      evidence: `${getRiskMetricLabel(
        copy,
        metric.key,
      )} · ${formatRiskAlertLevel(metric.level, locale)}`,
    });
  }
  activeRiskItems.sort(
    (left, right) =>
      Number(left.severity !== 'danger') - Number(right.severity !== 'danger'),
  );
  const runBatchRiskGate = async () => {
    setBatchRiskMessage(null);
    setBatchRiskBlockedMessage(null);
    setBatchRiskError(null);
    try {
      const result = await batchPreTradeRisk.mutateAsync();
      if (result.status === 'blocked_by_data_quality') {
        setBatchRiskBlockedMessage(
          locale === 'zh'
            ? `批量风控未运行：估值或行情证据尚未完整，已跳过 ${result.skipped_count} 个候选。未写入风险决策、订单或账本；请先处理数据状态后重试。`
            : `Batch risk did not run: valuation or market evidence is incomplete, so ${result.skipped_count} candidates were skipped. No risk decisions, orders, or ledger entries were written; resolve the data status before retrying.`,
        );
        return;
      }
      setBatchRiskMessage(
        copy.riskPage.batchRiskGateDone(
          result.passed_count,
          result.blocked_count,
        ),
      );
    } catch (error) {
      setBatchRiskError(
        `${copy.riskPage.batchRiskGateFailed} ${getErrorMessage(error)}`,
      );
    }
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <WorkspaceHeader
        eyebrow={copy.riskPage.kicker}
        title={copy.riskPage.title}
        description={copy.riskPage.subtitle}
        context={
          state.data
            ? copy.common.valuationEvidenceAsOf(
                formatTimestamp(
                  state.data.summary.valuation_as_of ??
                    state.data.summary.valuation_timestamp,
                ),
                formatPublicStatus(
                  state.data.summary.valuation_status ??
                    state.data.summary.quote_status,
                  locale,
                ),
              )
            : undefined
        }
        actions={
          state.data ? (
            <EvidenceIdentityDisclosure
              triggerLabel={copy.common.viewEvidenceIdentity}
              title={copy.common.evidenceIdentityTitle}
              description={copy.common.evidenceIdentityDescription}
              closeLabel={copy.common.closeEvidenceIdentity}
              copyLabel={copy.common.copyEvidenceValue}
              copiedLabel={copy.common.evidenceValueCopied}
              fields={[
                {
                  label: copy.common.valuationSnapshot,
                  value: state.data.summary.valuation_snapshot_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.ledgerCutoff,
                  value: state.data.summary.ledger_cutoff_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.valuationAsOf,
                  value: formatTimestamp(
                    state.data.summary.valuation_as_of ??
                      state.data.summary.valuation_timestamp,
                  ),
                  mono: true,
                },
                {
                  label: copy.common.valuationStatus,
                  value: formatPublicStatus(
                    state.data.summary.valuation_status ??
                      state.data.summary.quote_status,
                    locale,
                  ),
                },
              ]}
            />
          ) : undefined
        }
      />

      {isInitialRiskLoad ? (
        <EvidenceState
          kind="loading"
          title={copy.states.loading}
          description={copy.riskPage.loading}
        />
      ) : isRiskWorkspaceUnavailable ? (
        <EvidenceState
          kind="error"
          title={copy.states.error}
          description={copy.riskPage.error}
        />
      ) : (
        <div className="space-y-5 sm:space-y-6">
          {hasRiskRefreshError ? (
            <div
              role="status"
              className="rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm font-semibold leading-6 text-[var(--app-warning-text)]"
            >
              {copy.riskPage.refreshError}
            </div>
          ) : null}
          <section
            data-testid="risk-blocking-register"
            className="min-w-0 space-y-2"
          >
            <div>
              <h2 className="text-base font-semibold text-[var(--app-text)]">
                {copy.riskPage.blockingRegister}
              </h2>
              <p className="mt-0.5 max-w-3xl text-xs text-[var(--app-text-secondary)]">
                {copy.riskPage.blockingRegisterDetail}
              </p>
            </div>
            <ExceptionList
              ariaLabel={copy.riskPage.blockingRegister}
              emptyState={copy.riskPage.noBlockingItems}
              labels={{
                reason: locale === 'zh' ? '阻断原因' : 'Reason',
                unblockCondition:
                  locale === 'zh' ? '解除条件' : 'Unblock condition',
                nextAction: locale === 'zh' ? '安全下一步' : 'Safe next step',
                evidence: locale === 'zh' ? '证据' : 'Evidence',
              }}
              items={activeRiskItems}
              className="md:grid-cols-2 [&>li>dl]:grid-cols-2"
            />
          </section>

          <MetricStrip
            ariaLabel={copy.riskPage.metrics}
            items={workspace.data.metrics.map((metric) => ({
              id: metric.key,
              label: getRiskMetricLabel(copy, metric.key),
              value: metric.display_value,
              detail: formatRiskAlertLevel(metric.level, locale),
              tone:
                metric.level === 'high'
                  ? ('danger' as const)
                  : metric.level === 'medium'
                    ? ('warning' as const)
                    : ('neutral' as const),
            }))}
          />

          {riskReviewTask ? (
            <section
              data-testid="risk-decision-handoff"
              className="min-w-0 space-y-2"
            >
              <h2 className="text-base font-semibold text-[var(--app-text)]">
                {copy.riskPage.decisionHandoffKicker}
              </h2>
              <ExceptionList
                ariaLabel={copy.riskPage.decisionHandoffKicker}
                emptyState={copy.riskPage.noBlockingItems}
                labels={{
                  reason: locale === 'zh' ? '阻断原因' : 'Reason',
                  unblockCondition:
                    locale === 'zh' ? '解除条件' : 'Unblock condition',
                  nextAction: locale === 'zh' ? '安全下一步' : 'Safe next step',
                  evidence: locale === 'zh' ? '证据' : 'Evidence',
                }}
                items={[
                  {
                    id: riskReviewTask.id,
                    severity: 'warning',
                    statusLabel: formatPublicStatus(
                      riskReviewTask.status,
                      locale,
                    ),
                    title: copy.riskPage.decisionHandoffTitle,
                    reason: copy.riskPage.decisionHandoffDetail(
                      riskCandidateCount,
                      riskCheckedCount,
                    ),
                    unblockCondition: copy.riskPage.decisionHandoffHow,
                    nextAction: copy.riskPage.decisionHandoffWhat,
                    evidence: copy.riskPage.decisionHandoffDoNot,
                  },
                ]}
              />
              <div className="flex min-w-0 flex-col gap-2 border-b border-[var(--app-divider)] pb-3 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  className="app-button-primary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55 sm:min-h-9"
                  disabled={batchPreTradeRisk.isPending}
                  onClick={() => void runBatchRiskGate()}
                >
                  {batchPreTradeRisk.isPending
                    ? copy.riskPage.runningBatchRiskGate
                    : copy.riskPage.runBatchRiskGate}
                </button>
                <a
                  className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
                  href="/decision"
                >
                  {copy.riskPage.returnToDecision}
                </a>
              </div>
              {batchRiskMessage ? (
                <div className="mt-3 rounded-[var(--app-radius-surface)] border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-3 py-2 text-sm font-semibold text-[var(--app-success-text)]">
                  {batchRiskMessage}
                </div>
              ) : null}
              {batchRiskBlockedMessage ? (
                <div
                  role="status"
                  className="mt-3 rounded-[var(--app-radius-surface)] border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-2 text-sm font-semibold leading-6 text-[var(--app-warning-text)]"
                >
                  {batchRiskBlockedMessage}
                </div>
              ) : null}
              {batchRiskError ? (
                <div className="app-error-text mt-3 text-sm">
                  {batchRiskError}
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="min-w-0 space-y-2">
            <div>
              <h2 className="text-base font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '风险指标与阈值证据'
                  : 'Risk metric and threshold evidence'}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
                {locale === 'zh'
                  ? '仅展示 canonical 投影持久化的数值、等级和说明；未提供的阈值不会在 UI 中推导。'
                  : 'Shows only values, levels, and details persisted by the canonical projection; missing thresholds are not inferred in the UI.'}
              </p>
            </div>
            <div className="max-w-full overflow-x-auto border-y border-[var(--app-divider)]">
              <table
                className="w-full min-w-[620px] border-collapse text-left text-xs"
                data-testid="risk-threshold-table"
              >
                <caption className="sr-only">{copy.riskPage.metrics}</caption>
                <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
                  <tr>
                    {[
                      locale === 'zh' ? '指标' : 'Metric',
                      locale === 'zh' ? '投影值' : 'Projected value',
                      locale === 'zh' ? '等级' : 'Level',
                      locale === 'zh' ? '持久化说明' : 'Persisted detail',
                    ].map((label) => (
                      <th
                        key={label}
                        scope="col"
                        className="border-b border-[var(--app-divider)] px-3 py-2 font-semibold"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
                  {workspace.data.metrics.map((metric) => (
                    <tr key={metric.key}>
                      <th scope="row" className="px-3 py-2.5 font-semibold">
                        {getRiskMetricLabel(copy, metric.key)}
                      </th>
                      <td className="px-3 py-2.5 font-mono tabular-nums">
                        {metric.display_value}
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge
                          tone={
                            metric.level === 'high'
                              ? 'danger'
                              : metric.level === 'medium'
                                ? 'warning'
                                : 'neutral'
                          }
                        >
                          {formatRiskAlertLevel(metric.level, locale)}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-2.5 text-[var(--app-text-secondary)]">
                        {getRiskMetricDetail(copy, metric.key)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
            <section className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
                {copy.riskPage.drawdown}
              </div>
              <div className="mt-3">
                <DrawdownChart points={workspace.data.drawdown_series} />
              </div>
            </section>
            <div className="min-w-0 space-y-4">
              <section className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
                  {copy.riskPage.exposure}
                </div>
                <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
                  {workspace.data.exposure_buckets.map((bucket) => (
                    <div key={bucket.bucket} className="px-2 py-2.5">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold">
                          {getRiskBucketLabel(copy, bucket.bucket)}
                        </div>
                        <div className="text-sm font-semibold tabular-nums">
                          {formatPercentValue(bucket.weight)}
                        </div>
                      </div>
                      <div className="app-muted mt-2 text-sm">
                        {formatCurrency(bucket.value)} ·{' '}
                        {copy.overview.risk.positionsHint(
                          bucket.positions_count,
                        )}
                      </div>
                      {bucket.symbols.length > 0 ? (
                        <div className="mt-2 font-mono text-[11px] text-[var(--app-text-tertiary)]">
                          {bucket.symbols.join(' · ')}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>

              <section className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
                  {copy.riskPage.concentration}
                </div>
                <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
                  {workspace.data.concentration.length > 0 ? (
                    workspace.data.concentration.map((item) => (
                      <div key={item.symbol} className="px-2 py-2.5">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold">
                            {item.symbol}
                          </div>
                          <div className="text-sm font-semibold tabular-nums">
                            {formatPercentValue(item.weight)}
                          </div>
                        </div>
                        <div className="app-muted mt-2 text-sm">
                          {formatCurrency(item.market_value)} ·{' '}
                          {copy.portfolio.table.unrealized}{' '}
                          {formatCurrency(item.unrealized_pnl)}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="app-muted text-sm">
                      {copy.riskPage.noConcentration}
                    </div>
                  )}
                </div>
              </section>
            </div>
          </div>

          <section className="min-w-0 space-y-2">
            <div>
              <h2 className="text-base font-semibold text-[var(--app-text)]">
                {locale === 'zh' ? '受控操作' : 'Controlled actions'}
              </h2>
              <p className="mt-0.5 max-w-3xl text-xs text-[var(--app-text-secondary)]">
                {locale === 'zh'
                  ? '熔断与人工审批独立于风险事实展示；操作不会改变上方 canonical 风险证据。'
                  : 'Kill-switch and manual approval controls remain separate from risk facts and do not alter the canonical evidence above.'}
              </p>
            </div>
            <div
              className="grid min-w-0 gap-4"
              data-testid="risk-trading-control-grid"
            >
              <KillSwitchPanel />
              <OrderApprovalTable />
            </div>
          </section>

          <ExplainabilityWorkspace
            title={copy.riskPage.equityBridge}
            stateLabelRecent={copy.riskPage.recentDrivers}
            stateLabelPositions={copy.riskPage.positionDrivers}
            emptyLabel={copy.riskPage.emptyDrivers}
            explainability={explainability.data}
            loading={explainability.isLoading}
            instrumentNames={instrumentNames}
            filters={
              <div className="grid gap-3 md:grid-cols-3">
                <label className="grid gap-2">
                  <span className="text-sm font-medium">
                    {copy.market.noteDateFrom}
                  </span>
                  <input
                    type="date"
                    value={timelineFromDate}
                    onChange={(event) =>
                      setTimelineFromDate(event.target.value)
                    }
                    className="app-field rounded-2xl px-3 py-2 text-sm"
                    aria-label={copy.market.noteDateFrom}
                  />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">
                    {copy.market.noteDateTo}
                  </span>
                  <input
                    type="date"
                    value={timelineToDate}
                    onChange={(event) => setTimelineToDate(event.target.value)}
                    className="app-field rounded-2xl px-3 py-2 text-sm"
                    aria-label={copy.market.noteDateTo}
                  />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">
                    {copy.explainability.timelineEventKind}
                  </span>
                  <select
                    value={timelineEventKind}
                    onChange={(event) =>
                      setTimelineEventKind(event.target.value)
                    }
                    className="app-field rounded-2xl px-3 py-2 text-sm"
                    aria-label={copy.explainability.timelineEventKind}
                  >
                    <option value="">{copy.explainability.allEvents}</option>
                    <option value="cash_deposit">
                      {copy.explainability.deposits}
                    </option>
                    <option value="cash_withdrawal">
                      {copy.explainability.withdrawals}
                    </option>
                    <option value="dividend">
                      {copy.explainability.dividends}
                    </option>
                    <option value="trade_buy">
                      {copy.explainability.buys}
                    </option>
                    <option value="trade_sell">
                      {copy.explainability.sells}
                    </option>
                    <option value="manual_adjustment">
                      {copy.explainability.adjustments}
                    </option>
                  </select>
                </label>
              </div>
            }
          />
        </div>
      )}
    </section>
  );
}

export function MarketPage() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const board = useResearchBoardQuery();
  const addWatchlistItem = useAddWatchlistItemMutation();
  const removeWatchlistItem = useRemoveWatchlistItemMutation();
  const createResearchNote = useCreateResearchNoteMutation();
  const quoteFetchRuns = useQuoteFetchRunsQuery();
  const holdingMarketEvidenceReview =
    useCurrentHoldingMarketEvidenceReviewQuery();
  const metadataBackfill = useInstrumentMetadataBackfillMutation();
  const barsBackfill = useMarketBarsBackfillMutation();
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [newSymbol, setNewSymbol] = useState('');
  const [newAssetClass, setNewAssetClass] = useState('stock');
  const [noteFilterType, setNoteFilterType] = useState('');
  const [noteFilterPriority, setNoteFilterPriority] = useState('');
  const [noteFilterDateFrom, setNoteFilterDateFrom] = useState('');
  const [noteFilterDateTo, setNoteFilterDateTo] = useState('');
  const [noteType, setNoteType] = useState('note');
  const [notePriority, setNotePriority] = useState('normal');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteContent, setNoteContent] = useState('');
  const [noteDate, setNoteDate] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const items = board.data?.items ?? [];
  const health = board.data?.health;
  const healthBySymbol = useMemo(
    () => new Map((health?.quotes ?? []).map((quote) => [quote.symbol, quote])),
    [health?.quotes],
  );
  const activeSymbol = selectedSymbol || items[0]?.symbol || '';
  const updateResearchNote = useUpdateResearchNoteMutation(activeSymbol);
  const selectedItem =
    items.find((item) => item.symbol === activeSymbol) ?? null;
  const selectedHealthQuote = selectedItem
    ? (healthBySymbol.get(selectedItem.symbol) ?? null)
    : null;
  const providerReportedAction =
    health?.next_action && health.next_action in copy.market.providerActions
      ? copy.market.providerActions[
          health.next_action as keyof typeof copy.market.providerActions
        ]
      : health?.next_action
        ? formatPublicCode(health.next_action, locale)
        : null;
  const specificProviderAction =
    health?.next_action &&
    health.next_action !== 'refresh_quotes_or_check_source'
      ? providerReportedAction
      : null;
  const providerAction =
    specificProviderAction ??
    formatMarketDataStatusNextAction(health?.source_health, locale) ??
    formatMarketDataStatusNextAction(health?.refresh_policy, locale) ??
    providerReportedAction;
  const selectedQuoteNextAction =
    formatMarketDataStatusNextAction(
      selectedHealthQuote?.stale_reason,
      locale,
    ) ??
    formatMarketDataStatusNextAction(
      selectedHealthQuote?.quote_status,
      locale,
    ) ??
    providerAction;
  const sourceHealthLabel = health?.source_health
    ? formatPublicStatus(health.source_health, locale)
    : copy.market.unknown;
  const refreshPolicyLabel = health?.refresh_policy
    ? formatPublicStatus(health.refresh_policy, locale)
    : '--';
  const cacheBound = isCacheLikeMarketDataStatus(health?.refresh_policy);
  const evidenceModeLabel = cacheBound ? refreshPolicyLabel : sourceHealthLabel;
  const providerStatusLabel = health?.provider_status
    ? formatPublicStatus(health.provider_status, locale)
    : copy.market.unknown;
  const providerConfiguredLabel = health
    ? health.provider_configured
      ? copy.market.configured
      : copy.market.notConfigured
    : copy.market.unknown;
  const providerFundsLabel =
    health?.provider_supports_funds == null
      ? copy.market.unknown
      : health.provider_supports_funds
        ? copy.market.fundSupported
        : copy.market.fundUnsupported;
  const holdingItemsCount = items.filter((item) => item.is_holding).length;
  const unconfirmedQuoteCount = (health?.quotes ?? []).filter((quote) =>
    isUnconfirmedMarketDataStatus(quote.quote_status),
  ).length;
  const staleCount = Math.max(
    health?.stale_symbols_count ?? 0,
    unconfirmedQuoteCount,
  );
  const latestQuoteLabel = formatTimestamp(health?.latest_quote_timestamp);
  const marketStateLabel = health
    ? health.market_open
      ? copy.market.marketOpen
      : copy.market.marketClosed
    : copy.market.unknown;
  const holdingReviewNeedsAttention =
    holdingMarketEvidenceReview.isError ||
    holdingMarketEvidenceReview.data?.status === 'review_required' ||
    holdingMarketEvidenceReview.data?.status === 'blocked_identity';
  const kline = useKlineQuery(activeSymbol);
  const notes = useResearchNotesQuery(activeSymbol, {
    entry_kind: noteFilterType || undefined,
    priority: noteFilterPriority || undefined,
    event_date_from: noteFilterDateFrom || undefined,
    event_date_to: noteFilterDateTo || undefined,
  });
  const deleteResearchNote = useDeleteResearchNoteMutation(activeSymbol);
  const assetClassOptions = [
    ['stock', copy.common.assetClassStock],
    ['etf', copy.common.assetClassEtf],
    ['fund', copy.common.assetClassFund],
    ['gold', copy.common.assetClassGold],
    ['bond', copy.common.assetClassBond],
  ] as const;

  const pushToast = (
    tone: ToastItem['tone'],
    title: string,
    message: string,
  ) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, tone, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  };

  return (
    <>
      <ToastStack toasts={toasts} />
      <section
        className="app-workbench-route space-y-5 sm:space-y-6"
        data-workbench-route="market"
      >
        <WorkspaceHeader
          eyebrow={copy.market.kicker}
          title={copy.market.title}
          description={copy.market.subtitle}
          context={`${copy.market.latestQuote}: ${latestQuoteLabel}`}
          actions={
            <StatusBadge
              tone={
                cacheBound || staleCount > 0
                  ? 'warning'
                  : health
                    ? 'success'
                    : 'neutral'
              }
            >
              {evidenceModeLabel}
            </StatusBadge>
          }
        />

        {holdingReviewNeedsAttention ? (
          <CurrentHoldingMarketEvidenceReviewPanel
            report={holdingMarketEvidenceReview.data}
            loading={holdingMarketEvidenceReview.isLoading}
            error={holdingMarketEvidenceReview.isError}
          />
        ) : null}

        {board.isLoading ? (
          <EvidenceState
            kind="loading"
            title={copy.states.loading}
            description={copy.market.loading}
          />
        ) : board.isError ? (
          <EvidenceState
            kind="error"
            title={copy.states.error}
            description={copy.market.error}
          />
        ) : (
          <div className="space-y-5 sm:space-y-6">
            <MetricStrip
              ariaLabel={copy.market.title}
              items={[
                {
                  id: 'watchlist',
                  label: copy.market.watchlist,
                  value: items.length,
                  detail: copy.market.personalUniverse,
                },
                {
                  id: 'holdings',
                  label: copy.market.holdingsContext,
                  value: holdingItemsCount,
                  detail: `${items.length} ${copy.market.watchlist}`,
                },
                {
                  id: 'latest-quote',
                  label: copy.market.latestQuote,
                  value: latestQuoteLabel,
                  detail: `${copy.market.cacheAge} ${formatAge(health?.cache_age_seconds)}`,
                },
                {
                  id: 'market-state',
                  label: copy.market.marketOpen,
                  value: marketStateLabel,
                  detail: `${staleCount} ${copy.market.staleSymbols}`,
                  tone: staleCount > 0 ? 'warning' : 'neutral',
                },
              ]}
            />

            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.28fr)_minmax(320px,0.72fr)]">
              <div className="app-workbench-section min-w-0 overflow-hidden">
                <div className="border-b border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-4 py-4 sm:px-5">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                      <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                        {copy.market.personalUniverse}
                      </div>
                      <div className="mt-1 text-lg font-semibold text-[var(--app-text)]">
                        {copy.market.watchlist}
                      </div>
                      <p className="mt-1 max-w-2xl text-xs leading-5 text-[var(--app-text-secondary)]">
                        {copy.market.scopeBoundary}
                      </p>
                    </div>
                    <StatusBadge
                      tone={health?.market_open ? 'success' : 'neutral'}
                    >
                      {marketStateLabel}
                    </StatusBadge>
                  </div>
                </div>

                <form
                  className="grid gap-3 border-b border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] px-4 py-4 md:grid-cols-[minmax(0,1fr)_160px_96px] sm:px-5"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    if (!newSymbol.trim()) {
                      return;
                    }
                    await addWatchlistItem.mutateAsync({
                      symbol: newSymbol.trim(),
                      asset_class: newAssetClass,
                    });
                    setNewSymbol('');
                    setSelectedSymbol('');
                  }}
                >
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.symbolLabel}
                    </span>
                    <input
                      name="watchlist_symbol"
                      autoComplete="off"
                      value={newSymbol}
                      onChange={(event) => setNewSymbol(event.target.value)}
                      placeholder={copy.market.symbolPlaceholder}
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.assetClass}
                    </span>
                    <select
                      name="watchlist_asset_class"
                      value={newAssetClass}
                      onChange={(event) => setNewAssetClass(event.target.value)}
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                    >
                      {assetClassOptions.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="submit"
                    className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm"
                  >
                    {copy.market.add}
                  </button>
                </form>

                {items.length > 0 ? (
                  <div
                    className="max-w-full overflow-x-auto overscroll-x-contain"
                    data-testid="market-research-table-scroll"
                  >
                    <table
                      className="w-full min-w-[760px] border-collapse text-left text-xs"
                      data-testid="market-research-table"
                    >
                      <caption className="sr-only">
                        {copy.market.watchlist}
                      </caption>
                      <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
                        <tr>
                          {[
                            copy.market.symbolLabel,
                            copy.market.priceLabel,
                            copy.market.holdingsContext,
                            copy.market.evidenceMode,
                            copy.market.researchCount,
                            '',
                          ].map((label, index) => (
                            <th
                              key={`${label}-${index}`}
                              scope="col"
                              className="border-b border-[var(--app-divider)] px-3 py-2 font-semibold"
                            >
                              {label || (
                                <span className="sr-only">
                                  {copy.market.remove}
                                </span>
                              )}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
                        {items.map((item) => {
                          const itemHealth = healthBySymbol.get(item.symbol);
                          const isActive = activeSymbol === item.symbol;
                          const quoteStatus = itemHealth?.quote_status ?? null;
                          const quoteStatusLabel = itemHealth?.quote_status
                            ? formatPublicStatus(
                                itemHealth.quote_status,
                                locale,
                              )
                            : '--';
                          return (
                            <tr
                              key={item.symbol}
                              className={
                                isActive
                                  ? 'bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)]'
                                  : 'hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)]'
                              }
                            >
                              <th scope="row" className="px-3 py-2.5">
                                <button
                                  type="button"
                                  aria-pressed={isActive}
                                  aria-label={`${item.name || item.symbol} ${item.symbol}`}
                                  className="min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]"
                                  onClick={() => setSelectedSymbol(item.symbol)}
                                >
                                  <span className="block truncate text-sm font-semibold text-[var(--app-text)]">
                                    {item.name || item.symbol}
                                  </span>
                                  <span className="mt-0.5 block font-mono text-[11px] font-normal tabular-nums text-[var(--app-text-tertiary)]">
                                    {item.symbol} ·{' '}
                                    {getAssetClassLabel(copy, item.asset_class)}
                                  </span>
                                </button>
                              </th>
                              <td className="px-3 py-2.5 font-mono text-sm font-semibold tabular-nums">
                                {item.price == null
                                  ? '--'
                                  : formatCurrency(item.price)}
                              </td>
                              <td className="px-3 py-2.5 font-mono text-sm tabular-nums">
                                {item.is_holding && item.market_value != null
                                  ? formatCurrency(item.market_value)
                                  : '--'}
                              </td>
                              <td className="px-3 py-2.5">
                                <div className="flex items-center gap-2">
                                  <StatusBadge
                                    tone={
                                      isConfirmedMarketDataStatus(quoteStatus)
                                        ? 'success'
                                        : isUnconfirmedMarketDataStatus(
                                              quoteStatus,
                                            )
                                          ? 'warning'
                                          : 'neutral'
                                    }
                                  >
                                    {quoteStatusLabel}
                                  </StatusBadge>
                                  <span className="font-mono text-[11px] tabular-nums text-[var(--app-text-tertiary)]">
                                    {formatAge(itemHealth?.quote_age_seconds)}
                                  </span>
                                </div>
                              </td>
                              <td className="px-3 py-2.5">
                                <span className="font-mono text-sm tabular-nums">
                                  {item.research_count}
                                </span>
                                <span className="mt-0.5 block text-[11px] text-[var(--app-text-tertiary)]">
                                  {formatTimestamp(item.last_research_at)}
                                </span>
                              </td>
                              <td className="px-3 py-2.5 text-right">
                                <button
                                  type="button"
                                  className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1 text-xs"
                                  onClick={async () => {
                                    await removeWatchlistItem.mutateAsync(
                                      item.symbol,
                                    );
                                    if (activeSymbol === item.symbol) {
                                      setSelectedSymbol('');
                                    }
                                  }}
                                >
                                  {copy.market.remove}
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EvidenceState
                    kind="empty"
                    title={copy.market.noSelection}
                    description={copy.market.scopeBoundary}
                    className="border-0"
                  />
                )}
              </div>

              <div className="space-y-5">
                <section
                  className="min-w-0 border-y border-[var(--app-divider)] py-4"
                  data-testid="market-data-health-summary"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                        {copy.market.health}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-semibold text-[var(--app-text)]">
                          {copy.market.sourceHealth}
                        </h2>
                        <StatusBadge
                          tone={
                            cacheBound || staleCount > 0
                              ? 'warning'
                              : health
                                ? 'success'
                                : 'neutral'
                          }
                        >
                          {sourceHealthLabel}
                        </StatusBadge>
                      </div>
                    </div>
                    <MarketRefreshButton
                      onComplete={(response) => {
                        const title =
                          response.quote_status === 'live'
                            ? copy.market.quoteRefreshComplete
                            : response.quote_status === 'partial'
                              ? copy.market.quoteRefreshPartial
                              : response.quote_status === 'stale'
                                ? copy.market.quoteRefreshStale
                                : copy.market.quoteRefreshFailed;
                        pushToast(
                          response.quote_status === 'error'
                            ? 'error'
                            : 'success',
                          title,
                          response.message,
                        );
                      }}
                      onError={(error) => {
                        pushToast(
                          'error',
                          copy.market.quoteRefreshFailed,
                          error.message,
                        );
                      }}
                    />
                  </div>

                  <MetricStrip
                    className="mt-3"
                    ariaLabel={copy.market.health}
                    items={[
                      {
                        id: 'provider',
                        label: copy.market.provider,
                        value: health?.provider_name ?? copy.market.unknown,
                        detail: providerStatusLabel,
                      },
                      {
                        id: 'refresh-policy',
                        label: copy.market.refreshPolicy,
                        value: refreshPolicyLabel,
                        detail: providerConfiguredLabel,
                        tone: cacheBound ? 'warning' : 'neutral',
                      },
                      {
                        id: 'cache-age',
                        label: copy.market.cacheAge,
                        value: formatAge(health?.cache_age_seconds),
                        detail: latestQuoteLabel,
                      },
                      {
                        id: 'review-count',
                        label: copy.market.health,
                        value: staleCount,
                        detail: copy.market.staleSymbols,
                        tone: staleCount > 0 ? 'warning' : 'neutral',
                      },
                    ]}
                  />

                  {providerAction ? (
                    <div className="mt-3 border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5 text-[var(--app-text-secondary)]">
                      <span className="font-semibold text-[var(--app-text)]">
                        {copy.market.providerNextAction}:
                      </span>{' '}
                      {providerAction}
                    </div>
                  ) : null}

                  <details
                    className="group mt-3 border-t border-[var(--app-divider)] pt-2"
                    data-testid="market-provider-details"
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                      <span>{copy.market.providerStatus}</span>
                      <span
                        aria-hidden="true"
                        className="group-open:rotate-180"
                      >
                        ▾
                      </span>
                    </summary>
                    <dl className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-xs">
                      {[
                        [
                          copy.market.providerConfigured,
                          providerConfiguredLabel,
                        ],
                        [copy.market.providerSupportsFunds, providerFundsLabel],
                        [
                          copy.market.metadataConfiguredCount,
                          health == null
                            ? '--'
                            : String(health.metadata_configured_count),
                        ],
                        [
                          copy.market.providerTimeout,
                          health?.provider_timeout_seconds == null
                            ? '--'
                            : `${health.provider_timeout_seconds}s`,
                        ],
                        [
                          copy.market.lastRefreshAttempt,
                          formatTimestamp(health?.last_refresh_attempt),
                        ],
                        [
                          copy.market.lastRefreshError,
                          formatStaleReason(
                            health?.provider_last_error ??
                              health?.last_refresh_error,
                            copy.common.staleReasons,
                          ),
                        ],
                      ].map(([label, value]) => (
                        <div
                          key={label}
                          className="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-3 px-2 py-2"
                        >
                          <dt className="text-[var(--app-text-tertiary)]">
                            {label}
                          </dt>
                          <dd className="min-w-0 break-words text-right text-[var(--app-text-secondary)]">
                            {value}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                </section>
                <details className="group border-y border-[var(--app-divider)] py-2">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                    <span>{copy.market.promptsTitle}</span>
                    <span aria-hidden="true" className="group-open:rotate-180">
                      ▾
                    </span>
                  </summary>
                  <div className="mt-2 divide-y divide-[var(--app-divider)]">
                    {copy.market.prompts.map((prompt) => (
                      <div
                        key={prompt}
                        className="py-2 text-xs leading-5 text-[var(--app-text-secondary)]"
                      >
                        {prompt}
                      </div>
                    ))}
                  </div>
                </details>
                <details
                  className="group border-y border-[var(--app-divider)] py-2"
                  data-testid="market-data-operations-disclosure"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                    <span>{copy.market.dataOperations}</span>
                    <span className="flex items-center gap-2 font-mono text-xs font-normal tabular-nums text-[var(--app-text-tertiary)]">
                      {quoteFetchRuns.data?.length ?? 0}
                      <span
                        aria-hidden="true"
                        className="group-open:rotate-180"
                      >
                        ▾
                      </span>
                    </span>
                  </summary>
                  <div className="mt-3">
                    <MarketDataOperationsPanel
                      runs={quoteFetchRuns.data ?? []}
                      loading={quoteFetchRuns.isLoading}
                      error={quoteFetchRuns.isError}
                      metadataPending={metadataBackfill.isPending}
                      barsPending={barsBackfill.isPending}
                      onMetadataBackfill={async () => {
                        try {
                          const result = await metadataBackfill.mutateAsync();
                          pushToast(
                            'success',
                            copy.market.metadataBackfillComplete,
                            copy.market.backfillResult(
                              result.updated_count,
                              result.failed_count,
                            ),
                          );
                        } catch (error) {
                          pushToast(
                            'error',
                            copy.market.metadataBackfillFailed,
                            getErrorMessage(error),
                          );
                        }
                      }}
                      onBarsBackfill={async () => {
                        try {
                          const result = await barsBackfill.mutateAsync();
                          pushToast(
                            'success',
                            copy.market.barsBackfillComplete,
                            copy.market.backfillResult(
                              result.updated_count,
                              result.failed_count,
                            ),
                          );
                        } catch (error) {
                          pushToast(
                            'error',
                            copy.market.barsBackfillFailed,
                            getErrorMessage(error),
                          );
                        }
                      }}
                    />
                  </div>
                </details>
              </div>
            </div>

            {!holdingReviewNeedsAttention ? (
              <CurrentHoldingMarketEvidenceReviewPanel
                report={holdingMarketEvidenceReview.data}
                loading={holdingMarketEvidenceReview.isLoading}
                error={holdingMarketEvidenceReview.isError}
              />
            ) : null}

            <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
              <div className="app-workbench-section min-w-0 p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.market.chart}
                </div>
                <div className="mt-4">
                  {selectedItem ? (
                    <PriceStructureChart
                      bars={kline.data ?? []}
                      emptyLabel={copy.market.noChart}
                      titleLabel={copy.market.priceRangeKline}
                      priceLabel={copy.market.priceLabel}
                      rangeLabels={copy.market.klineRanges}
                      axisLabels={copy.market.klineAxes}
                      rangeAriaLabel={copy.market.showKlineRange}
                    />
                  ) : (
                    <div className="app-muted text-sm">
                      {copy.market.noSelection}
                    </div>
                  )}
                </div>
              </div>
              <section
                className="min-w-0 border-y border-[var(--app-divider)] py-4"
                data-testid="market-selected-instrument"
              >
                {selectedItem ? (
                  <>
                    <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                          {copy.market.selectedSymbol}
                        </div>
                        <h2 className="mt-1 truncate text-lg font-semibold text-[var(--app-text)]">
                          {selectedItem.name || selectedItem.symbol}
                        </h2>
                      </div>
                      <StatusBadge
                        tone={
                          isConfirmedMarketDataStatus(
                            selectedHealthQuote?.quote_status,
                          )
                            ? 'success'
                            : isUnconfirmedMarketDataStatus(
                                  selectedHealthQuote?.quote_status,
                                )
                              ? 'warning'
                              : 'neutral'
                        }
                      >
                        {selectedHealthQuote?.quote_status
                          ? formatPublicStatus(
                              selectedHealthQuote.quote_status,
                              locale,
                            )
                          : copy.market.unknown}
                      </StatusBadge>
                    </div>

                    <MetricStrip
                      className="mt-3"
                      ariaLabel={copy.market.selectedSymbol}
                      items={[
                        {
                          id: 'symbol',
                          label: copy.market.symbolLabel,
                          value: selectedItem.symbol,
                          detail: getAssetClassLabel(
                            copy,
                            selectedItem.asset_class,
                          ),
                        },
                        {
                          id: 'price',
                          label: copy.market.priceLabel,
                          value:
                            selectedItem.price == null
                              ? '--'
                              : formatCurrency(selectedItem.price),
                          detail:
                            selectedHealthQuote?.quote_source ??
                            copy.market.unknown,
                        },
                        {
                          id: 'holding',
                          label: copy.market.holdingsContext,
                          value:
                            selectedItem.is_holding &&
                            selectedItem.market_value != null
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
                          label: copy.market.quoteAge,
                          value: formatAge(
                            selectedHealthQuote?.quote_age_seconds,
                          ),
                          detail: formatTimestamp(
                            selectedHealthQuote?.timestamp,
                          ),
                          tone: isUnconfirmedMarketDataStatus(
                            selectedHealthQuote?.quote_status,
                          )
                            ? 'warning'
                            : 'neutral',
                        },
                      ]}
                    />

                    <dl className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-xs">
                      {[
                        [
                          copy.market.snapshotLabel,
                          formatTimestamp(selectedItem.last_snapshot_at),
                        ],
                        [
                          copy.market.staleReason,
                          formatStaleReason(
                            selectedHealthQuote?.stale_reason,
                            copy.common.staleReasons,
                          ),
                        ],
                        [
                          copy.market.providerNextAction,
                          selectedQuoteNextAction ?? '--',
                        ],
                        [
                          copy.market.lastResearch,
                          formatTimestamp(selectedItem.last_research_at),
                        ],
                      ].map(([label, value]) => (
                        <div
                          key={label}
                          className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] gap-3 px-2 py-2"
                        >
                          <dt className="text-[var(--app-text-tertiary)]">
                            {label}
                          </dt>
                          <dd className="min-w-0 break-words text-right text-[var(--app-text-secondary)]">
                            {value}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </>
                ) : (
                  <EvidenceState kind="empty" title={copy.market.noSelection} />
                )}
              </section>
            </div>

            <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
              <div className="app-workbench-section min-w-0 p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.market.notesTitle}
                </div>
                {selectedItem ? (
                  <form
                    className="mt-4 grid gap-3"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (!noteTitle.trim() || !noteContent.trim()) {
                        pushToast(
                          'error',
                          copy.market.noteFailed,
                          copy.common.required,
                        );
                        return;
                      }
                      try {
                        if (editingNoteId !== null) {
                          await updateResearchNote.mutateAsync({
                            noteId: editingNoteId,
                            entry_kind: noteType,
                            title: noteTitle.trim(),
                            content: noteContent.trim(),
                            priority: notePriority,
                            event_date: noteDate || null,
                          });
                        } else {
                          await createResearchNote.mutateAsync({
                            symbol: selectedItem.symbol,
                            asset_class: selectedItem.asset_class,
                            entry_kind: noteType,
                            title: noteTitle.trim(),
                            content: noteContent.trim(),
                            priority: notePriority,
                            event_date: noteDate || null,
                          });
                        }
                        setEditingNoteId(null);
                        setNoteType('note');
                        setNotePriority('normal');
                        setNoteTitle('');
                        setNoteContent('');
                        setNoteDate('');
                        pushToast(
                          'success',
                          editingNoteId !== null
                            ? copy.market.updateNote
                            : copy.market.noteSaved,
                          selectedItem.symbol,
                        );
                      } catch (error) {
                        pushToast(
                          'error',
                          copy.market.noteFailed,
                          getErrorMessage(error),
                        );
                      }
                    }}
                  >
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="grid gap-2">
                        <span className="text-sm font-medium">
                          {copy.market.noteType}
                        </span>
                        <select
                          name="research_note_type"
                          value={noteType}
                          onChange={(event) => setNoteType(event.target.value)}
                          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        >
                          <option value="note">{copy.market.note}</option>
                          <option value="thesis">{copy.market.thesis}</option>
                          <option value="catalyst">
                            {copy.market.catalyst}
                          </option>
                        </select>
                      </label>
                      <label className="grid gap-2">
                        <span className="text-sm font-medium">
                          {copy.market.notePriority}
                        </span>
                        <select
                          name="research_note_priority"
                          value={notePriority}
                          onChange={(event) =>
                            setNotePriority(event.target.value)
                          }
                          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        >
                          <option value="high">
                            {copy.market.highPriority}
                          </option>
                          <option value="normal">
                            {copy.market.normalPriority}
                          </option>
                          <option value="low">{copy.market.lowPriority}</option>
                        </select>
                      </label>
                    </div>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteTitle}
                      </span>
                      <input
                        name="research_note_title"
                        autoComplete="off"
                        value={noteTitle}
                        onChange={(event) => setNoteTitle(event.target.value)}
                        placeholder={copy.market.noteTitlePlaceholder}
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteContent}
                      </span>
                      <textarea
                        name="research_note_content"
                        value={noteContent}
                        onChange={(event) => setNoteContent(event.target.value)}
                        placeholder={copy.market.noteContentPlaceholder}
                        rows={5}
                        className="app-field min-h-32 rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteDate}
                      </span>
                      <input
                        name="research_note_date"
                        type="date"
                        value={noteDate}
                        onChange={(event) => setNoteDate(event.target.value)}
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={
                        createResearchNote.isPending ||
                        updateResearchNote.isPending
                      }
                      className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm"
                    >
                      {createResearchNote.isPending ||
                      updateResearchNote.isPending
                        ? copy.market.savingNote
                        : editingNoteId !== null
                          ? copy.market.updateNote
                          : copy.market.saveNote}
                    </button>
                  </form>
                ) : (
                  <div className="app-muted mt-4 text-sm">
                    {copy.market.noSelection}
                  </div>
                )}
              </div>

              <div className="app-workbench-section min-w-0 p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.market.notesTitle}
                </div>
                <FilterBar
                  className="mt-4"
                  label={copy.market.notesTitle}
                  summary={
                    notes.data ? String(notes.data.items.length) : undefined
                  }
                >
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.noteType}
                    </span>
                    <select
                      value={noteFilterType}
                      onChange={(event) =>
                        setNoteFilterType(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                    >
                      <option value="">{copy.market.allTypes}</option>
                      <option value="note">{copy.market.note}</option>
                      <option value="thesis">{copy.market.thesis}</option>
                      <option value="catalyst">{copy.market.catalyst}</option>
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.notePriority}
                    </span>
                    <select
                      value={noteFilterPriority}
                      onChange={(event) =>
                        setNoteFilterPriority(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                    >
                      <option value="">{copy.market.allPriorities}</option>
                      <option value="high">{copy.market.highPriority}</option>
                      <option value="normal">
                        {copy.market.normalPriority}
                      </option>
                      <option value="low">{copy.market.lowPriority}</option>
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.noteDateFrom}
                    </span>
                    <input
                      type="date"
                      value={noteFilterDateFrom}
                      onChange={(event) =>
                        setNoteFilterDateFrom(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      aria-label={copy.market.noteDateFrom}
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.noteDateTo}
                    </span>
                    <input
                      type="date"
                      value={noteFilterDateTo}
                      onChange={(event) =>
                        setNoteFilterDateTo(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      aria-label={copy.market.noteDateTo}
                    />
                  </label>
                </FilterBar>
                {notes.isLoading ? (
                  <div className="app-muted mt-4 text-sm">
                    {copy.states.loading}
                  </div>
                ) : notes.isError ? (
                  <div className="app-muted mt-4 text-sm">
                    {copy.market.noteFailed}
                  </div>
                ) : notes.data && notes.data.items.length > 0 ? (
                  <div className="mt-4 grid gap-3">
                    {notes.data.items.map((note) => (
                      <div
                        key={note.id}
                        className="app-panel-strong rounded-[var(--app-radius-surface)] px-4 py-4"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold">
                              {note.title}
                            </div>
                            <div className="app-kicker mt-2 text-[11px] uppercase tracking-[0.16em]">
                              {getNoteTypeLabel(copy, note.entry_kind)} ·{' '}
                              {getPriorityLabel(copy, note.priority)}
                              {note.event_date ? ` · ${note.event_date}` : ''}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1 text-xs"
                              onClick={() => {
                                setEditingNoteId(note.id);
                                setNoteType(note.entry_kind);
                                setNotePriority(note.priority);
                                setNoteTitle(note.title);
                                setNoteContent(note.content);
                                setNoteDate(note.event_date ?? '');
                              }}
                            >
                              {copy.market.editNote}
                            </button>
                            <button
                              type="button"
                              className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1 text-xs"
                              onClick={async () => {
                                try {
                                  await deleteResearchNote.mutateAsync(note.id);
                                  pushToast(
                                    'success',
                                    copy.market.noteDeleted,
                                    note.title,
                                  );
                                } catch (error) {
                                  pushToast(
                                    'error',
                                    copy.market.noteDeleteFailed,
                                    getErrorMessage(error),
                                  );
                                }
                              }}
                            >
                              {copy.market.remove}
                            </button>
                          </div>
                        </div>
                        <div className="app-muted mt-3 text-sm leading-6">
                          {note.content}
                        </div>
                        <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
                          {note.updated_at}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="app-muted mt-4 text-sm">
                    {copy.market.notesEmpty}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
    </>
  );
}

export function ActivityPage() {
  const copy = useCopy();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [activeEntryTool, setActiveEntryTool] =
    useState<ActivityEntryTool>('trade');
  const entries = useLedgerEntriesQuery();
  const pendingFundOrders = usePendingFundOrdersQuery();
  const positions = usePositionsQuery();
  const settings = useSettingsQuery();
  const createTrade = useCreateTradeMutation();
  const tradePreview = useTradePreviewMutation();
  const previewTrade = tradePreview.mutate;
  const resetTradePreview = tradePreview.reset;
  const createCashFlow = useCreateCashFlowMutation();
  const createDividend = useCreateDividendMutation();
  const createAdjustment = useCreateAdjustmentMutation();
  const ledgerRows = entries.data ?? [];
  const latestEntry = ledgerRows[0] ?? null;
  const fundBatchCandidates = useMemo<FundBatchCandidate[]>(
    () =>
      (positions.data ?? [])
        .filter((position) => position.asset_class?.toLowerCase() === 'fund')
        .map((position) => ({
          symbol: position.symbol,
          display_name:
            position.display_name || position.name || position.symbol,
        })),
    [positions.data],
  );

  const pushToast = (
    tone: ToastItem['tone'],
    title: string,
    message: string,
  ) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, tone, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  };

  const handleTradeSubmit = async (values: TradeFormValues) => {
    const normalizeNumber = (value: number | null | undefined) =>
      typeof value === 'number' && Number.isFinite(value) ? value : null;
    try {
      await createTrade.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
        quantity: normalizeNumber(values.quantity),
        unit_price: normalizeNumber(values.unit_price),
        amount: normalizeNumber(values.amount),
        fee: normalizeNumber(values.fee),
        asset_class: values.asset_class.trim().toLowerCase(),
        symbol: values.symbol.trim(),
      });
      pushToast(
        'success',
        copy.activity.tradeSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.tradeFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleTradePreviewChange = useCallback(
    (values: TradeFormValues) => {
      const normalizeNumber = (value: number | null | undefined) =>
        typeof value === 'number' && Number.isFinite(value) ? value : null;
      const assetClass = values.asset_class.trim().toLowerCase();
      const symbol = values.symbol.trim();
      const quantity = normalizeNumber(values.quantity);
      const unitPrice = normalizeNumber(values.unit_price);
      const fee = normalizeNumber(values.fee);
      const occurredAt = new Date(values.occurred_at);
      const isPriceBasedTrade =
        symbol &&
        Number.isFinite(occurredAt.getTime()) &&
        quantity !== null &&
        quantity > 0 &&
        unitPrice !== null &&
        unitPrice > 0 &&
        !(assetClass === 'fund' && values.direction === 'buy');

      if (!isPriceBasedTrade) {
        resetTradePreview();
        return;
      }

      previewTrade({
        ...values,
        occurred_at: occurredAt.toISOString(),
        quantity,
        unit_price: unitPrice,
        amount: normalizeNumber(values.amount),
        fee,
        asset_class: assetClass,
        symbol,
      });
    },
    [previewTrade, resetTradePreview],
  );

  const handleFundBatchSubmit = async (values: FundBatchFormValues) => {
    try {
      for (const order of values.orders) {
        await createTrade.mutateAsync({
          occurred_at: new Date(values.occurred_at).toISOString(),
          symbol: order.symbol,
          asset_class: 'fund',
          direction: 'buy',
          quantity: null,
          unit_price: null,
          amount: order.amount,
          fee: 0,
          note: [
            values.note.trim(),
            order.display_name,
            copy.activity.forms.fundBatch.title,
          ]
            .filter(Boolean)
            .join(' | '),
        });
      }
      pushToast(
        'success',
        copy.activity.tradeSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.tradeFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleCashFlowSubmit = async (values: CashFlowFormValues) => {
    try {
      await createCashFlow.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
      pushToast(
        'success',
        copy.activity.cashFlowSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.cashFlowFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleDividendSubmit = async (values: DividendFormValues) => {
    try {
      await createDividend.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
      pushToast(
        'success',
        copy.activity.dividendSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.dividendFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleAdjustmentSubmit = async (values: ManualAdjustmentFormValues) => {
    try {
      await createAdjustment.mutateAsync({
        ...values,
        symbol: values.symbol || null,
        amount:
          values.amount === null || Number.isNaN(values.amount)
            ? null
            : values.amount,
        quantity:
          values.quantity === null || Number.isNaN(values.quantity)
            ? null
            : values.quantity,
        price:
          values.price === null || Number.isNaN(values.price)
            ? null
            : values.price,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
      pushToast(
        'success',
        copy.activity.adjustmentSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast(
        'error',
        copy.activity.adjustmentFailed,
        getErrorMessage(error),
      );
      throw error;
    }
  };

  return (
    <>
      <ToastStack toasts={toasts} />
      <section
        className="app-workbench-route min-w-0 space-y-5 sm:space-y-6"
        data-workbench-route="activity"
      >
        <WorkspaceHeader
          eyebrow={copy.activity.kicker}
          title={copy.activity.title}
          description={copy.activity.subtitle}
          context={
            latestEntry ? formatTimestamp(latestEntry.timestamp) : undefined
          }
        />

        <MetricStrip
          ariaLabel={copy.activity.title}
          items={[
            {
              id: 'pending-orders',
              label: copy.activity.summary.pendingOrders,
              value: pendingFundOrders.isLoading
                ? '--'
                : String(pendingFundOrders.data?.length ?? 0),
              detail: copy.activity.summary.pendingOrdersDetail,
              tone:
                (pendingFundOrders.data?.length ?? 0) > 0
                  ? 'warning'
                  : 'neutral',
            },
            {
              id: 'recent-entries',
              label: copy.activity.summary.recentEntries,
              value: entries.isLoading ? '--' : String(ledgerRows.length),
              detail: copy.activity.summary.recentEntriesDetail,
            },
            {
              id: 'net-cash-impact',
              label: copy.activity.summary.netCashImpact,
              value: copy.activity.summary.netCashImpactUnavailable,
              detail: copy.activity.summary.netCashImpactDetail,
            },
            {
              id: 'latest-activity',
              label: copy.activity.summary.latestActivity,
              value: latestEntry
                ? formatTimestamp(latestEntry.timestamp)
                : '--',
              detail: copy.activity.summary.latestActivityDetail,
            },
          ]}
        />

        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.55fr)]">
          <div
            className="min-w-0 space-y-6 xl:col-start-1 xl:row-start-1"
            data-activity-surface="audit-history"
          >
            {entries.isLoading ? (
              <EvidenceState
                kind="loading"
                title={copy.states.loading}
                description={copy.activity.loading}
              />
            ) : entries.isError ? (
              <EvidenceState
                kind="error"
                title={copy.states.error}
                description={copy.activity.error}
                action={
                  <button
                    type="button"
                    className="app-button-secondary px-3 py-2 text-xs"
                    onClick={() => void entries.refetch()}
                  >
                    {copy.states.retry}
                  </button>
                }
              />
            ) : (
              <ActivityFeed entries={entries.data ?? []} />
            )}
          </div>
          <aside
            className="min-w-0 space-y-6 xl:sticky xl:top-24 xl:col-start-2 xl:row-start-1 xl:self-start"
            data-activity-surface="priority-and-entry"
          >
            <PendingFundOrdersCard
              orders={pendingFundOrders.data ?? []}
              loading={pendingFundOrders.isLoading}
              error={pendingFundOrders.isError}
              onRetry={() => void pendingFundOrders.refetch()}
            />
            <ActivityEntryToolsPanel
              activeEntryTool={activeEntryTool}
              candidates={fundBatchCandidates}
              commissionSettings={
                settings.data
                  ? {
                      stock_rate: settings.data.account_commission_rate,
                      stock_min_commission:
                        settings.data.account_min_commission,
                    }
                  : undefined
              }
              createAdjustmentPending={createAdjustment.isPending}
              createCashFlowPending={createCashFlow.isPending}
              createDividendPending={createDividend.isPending}
              createTradePending={createTrade.isPending}
              loadingCandidates={positions.isLoading}
              onAdjustmentSubmit={handleAdjustmentSubmit}
              onCashFlowSubmit={handleCashFlowSubmit}
              onDividendSubmit={handleDividendSubmit}
              onFundBatchSubmit={handleFundBatchSubmit}
              onSelectEntryTool={setActiveEntryTool}
              onTradePreviewChange={handleTradePreviewChange}
              onTradeSubmit={handleTradeSubmit}
              previewError={tradePreview.isError}
              previewLoading={tradePreview.isPending}
              tradePreview={tradePreview.data ?? null}
            />
          </aside>
        </div>
      </section>
    </>
  );
}

type ActivityEntryTool =
  'trade' | 'fundBatch' | 'cashFlow' | 'dividend' | 'adjustment';

function ActivityEntryToolsPanel({
  activeEntryTool,
  candidates,
  commissionSettings,
  createAdjustmentPending,
  createCashFlowPending,
  createDividendPending,
  createTradePending,
  loadingCandidates,
  onAdjustmentSubmit,
  onCashFlowSubmit,
  onDividendSubmit,
  onFundBatchSubmit,
  onSelectEntryTool,
  onTradePreviewChange,
  onTradeSubmit,
  previewError,
  previewLoading,
  tradePreview,
}: {
  activeEntryTool: ActivityEntryTool;
  candidates: FundBatchCandidate[];
  commissionSettings?: {
    stock_rate: number;
    stock_min_commission: number;
  };
  createAdjustmentPending: boolean;
  createCashFlowPending: boolean;
  createDividendPending: boolean;
  createTradePending: boolean;
  loadingCandidates: boolean;
  onAdjustmentSubmit: (values: ManualAdjustmentFormValues) => Promise<void>;
  onCashFlowSubmit: (values: CashFlowFormValues) => Promise<void>;
  onDividendSubmit: (values: DividendFormValues) => Promise<void>;
  onFundBatchSubmit: (values: FundBatchFormValues) => Promise<void>;
  onSelectEntryTool: (tool: ActivityEntryTool) => void;
  onTradePreviewChange: (values: TradeFormValues) => void;
  onTradeSubmit: (values: TradeFormValues) => Promise<void>;
  previewError: boolean;
  previewLoading: boolean;
  tradePreview: ReturnType<typeof useTradePreviewMutation>['data'] | null;
}) {
  const copy = useCopy();
  const tools: Array<{ key: ActivityEntryTool; label: string }> = [
    { key: 'trade', label: copy.activity.forms.trade.title },
    { key: 'cashFlow', label: copy.activity.forms.cashFlow.title },
    { key: 'dividend', label: copy.activity.forms.dividend.title },
    { key: 'adjustment', label: copy.activity.forms.adjustment.title },
    { key: 'fundBatch', label: copy.activity.forms.fundBatch.title },
  ];

  return (
    <ControlledActionZone
      title={copy.activity.entryTools.title}
      description={copy.activity.entryTools.detail}
      evidence={copy.activity.entryTools.boundary}
      layout="stack"
      tone="info"
      className="min-w-0"
    >
      <div className="min-w-0 w-full">
        <div
          aria-label={copy.activity.entryTools.ariaLabel}
          className="grid min-w-0 grid-cols-2 gap-1"
          role="group"
        >
          {tools.map((tool) => {
            const isSelected = activeEntryTool === tool.key;
            return (
              <button
                key={tool.key}
                aria-pressed={isSelected}
                className={`min-h-10 min-w-0 rounded-[var(--app-radius-control)] border px-2.5 py-1.5 text-left text-xs font-semibold transition-colors xl:min-h-8 ${
                  isSelected
                    ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-hover)]'
                    : 'border-transparent bg-transparent text-[var(--app-text-tertiary)] hover:border-[var(--app-border)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)]'
                }`}
                onClick={() => onSelectEntryTool(tool.key)}
                type="button"
              >
                {tool.label}
              </button>
            );
          })}
        </div>
        <div className="mt-4 min-w-0 border-t border-[var(--app-divider)] pt-4">
          {activeEntryTool === 'trade' ? (
            <TradeForm
              onSubmit={onTradeSubmit}
              pending={createTradePending}
              tradePreview={tradePreview}
              previewLoading={previewLoading}
              previewError={previewError}
              onPreviewChange={onTradePreviewChange}
              commissionSettings={commissionSettings}
            />
          ) : null}
          {activeEntryTool === 'fundBatch' ? (
            <FundBatchForm
              candidates={candidates}
              loadingCandidates={loadingCandidates}
              onSubmit={onFundBatchSubmit}
              pending={createTradePending}
            />
          ) : null}
          {activeEntryTool === 'cashFlow' ? (
            <CashFlowForm
              onSubmit={onCashFlowSubmit}
              pending={createCashFlowPending}
            />
          ) : null}
          {activeEntryTool === 'dividend' ? (
            <DividendForm
              onSubmit={onDividendSubmit}
              pending={createDividendPending}
            />
          ) : null}
          {activeEntryTool === 'adjustment' ? (
            <ManualAdjustmentForm
              onSubmit={onAdjustmentSubmit}
              pending={createAdjustmentPending}
            />
          ) : null}
        </div>
      </div>
    </ControlledActionZone>
  );
}

function PendingFundOrdersCard({
  orders,
  loading,
  error,
  onRetry,
}: {
  orders: Array<{
    id: number;
    submitted_at: string;
    symbol: string;
    display_name: string;
    amount: number;
    target_trade_date: string;
    status: string;
  }>;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();

  if (loading) {
    return (
      <EvidenceState
        kind="loading"
        title={copy.states.loading}
        description={copy.activity.pending.loading}
      />
    );
  }
  if (error) {
    return (
      <EvidenceState
        kind="error"
        title={copy.states.error}
        description={copy.activity.pending.error}
        action={
          <button
            type="button"
            className="app-button-secondary px-3 py-2 text-xs"
            onClick={onRetry}
          >
            {copy.states.retry}
          </button>
        }
      />
    );
  }
  if (orders.length === 0) {
    return null;
  }

  return (
    <section className="app-workbench-section min-w-0 overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-[var(--app-divider)] px-4 py-3">
        <div>
          <div className="app-product-mark">{copy.activity.pending.kicker}</div>
          <h2 className="mt-2 text-base font-semibold">
            {copy.activity.pending.title}
          </h2>
        </div>
        <StatusBadge tone="warning">{orders.length}</StatusBadge>
      </div>
      <div className="divide-y divide-[var(--app-divider)]">
        {orders.map((order) => (
          <div key={order.id} className="px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">
                  {order.display_name}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {order.symbol} · {copy.activity.pending.submittedAt}{' '}
                  {formatTimestamp(order.submitted_at)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold">
                  {formatCurrency(order.amount)}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {formatPendingStatus(order.status, copy, locale)}
                </div>
              </div>
            </div>
            <div className="app-muted mt-3 text-xs">
              {copy.activity.pending.waitingFor} {order.target_trade_date}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatPendingStatus(
  status: string,
  copy: AppCopy,
  locale: 'en' | 'zh',
) {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'pending') {
    return copy.activity.pending.status.pending;
  }
  if (normalized === 'confirmed') {
    return copy.activity.pending.status.confirmed;
  }
  if (normalized === 'rejected') {
    return copy.activity.pending.status.rejected;
  }
  return formatPublicStatus(status, locale);
}

function ExplainabilityWorkspace({
  title,
  stateLabelRecent,
  stateLabelPositions,
  emptyLabel,
  explainability,
  loading,
  instrumentNames,
  filters,
  showReturnCalendar = false,
}: {
  title: string;
  stateLabelRecent: string;
  stateLabelPositions: string;
  emptyLabel: string;
  explainability:
    | {
        equity_bridge: Array<{
          key: string;
          label: string;
          value: number;
          detail: string;
        }>;
        recent_drivers: Array<{
          kind?: string;
          title: string;
          detail: string;
          timestamp: string;
          symbol?: string | null;
          amount?: number | null;
        }>;
        positions: Array<{
          symbol: string;
          quantity: number;
          market_value: number;
          unrealized_pnl: number;
          last_activity_at: string | null;
        }>;
        timeline: Array<{
          date: string;
          equity: number;
          delta: number;
          external_flow: number;
          market_pnl: number;
          market_breakdown?: ReturnCalendarBreakdownItem[];
          external_flow_breakdown?: ReturnCalendarBreakdownItem[];
          events: Array<{
            category: string;
            impact_source: string;
            kind: string;
            title: string;
            detail?: string;
            timestamp: string;
            symbol?: string | null;
            amount?: number | null;
          }>;
        }>;
      }
    | undefined;
  loading: boolean;
  instrumentNames?: Map<string, string>;
  filters?: ReactNode;
  showReturnCalendar?: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();

  if (loading) {
    return (
      <div className="app-panel rounded-2xl p-4 sm:p-5">
        {copy.states.loading}
      </div>
    );
  }

  const equityBridge = explainability?.equity_bridge ?? [];
  const equityBridgeTotalPnl = equityBridge
    .filter(
      (bridgeItem) =>
        bridgeItem.key === 'realized' || bridgeItem.key === 'unrealized',
    )
    .reduce((sum, bridgeItem) => sum + bridgeItem.value, 0);

  return (
    <div className="space-y-5">
      <div
        className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]"
        data-testid="risk-explainability-top-grid"
      >
        <div className="app-panel rounded-2xl p-4 sm:p-5">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {title}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {equityBridge.map((item) => {
              const label =
                copy.explainability.equityBridgeLabels[
                  item.key as keyof typeof copy.explainability.equityBridgeLabels
                ] ?? item.label;
              const detailTemplate =
                copy.explainability.equityBridgeDetails[
                  item.key as keyof typeof copy.explainability.equityBridgeDetails
                ];
              const detail =
                typeof detailTemplate === 'function'
                  ? detailTemplate(formatCurrency(equityBridgeTotalPnl))
                  : (detailTemplate ?? item.detail);

              return (
                <div
                  key={item.key}
                  className="app-panel-strong rounded-2xl px-4 py-4"
                >
                  <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                    {label}
                  </div>
                  <div className="mt-2 text-lg font-semibold tabular-nums">
                    {formatCurrency(item.value)}
                  </div>
                  <div className="app-muted mt-2 text-sm">{detail}</div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="space-y-5">
          <div className="app-panel rounded-2xl p-4 sm:p-5">
            <div className="app-kicker text-xs uppercase tracking-[0.18em]">
              {stateLabelRecent}
            </div>
            <div
              className="mt-4 grid max-h-[620px] gap-3 overflow-y-auto pr-1"
              data-testid="risk-recent-impact-list"
            >
              {(explainability?.recent_drivers?.length
                ? explainability.recent_drivers
                : [{ title: emptyLabel, detail: '', timestamp: '' }]
              ).map((item) => (
                <div
                  key={`${item.title}-${item.timestamp}`}
                  className="app-panel-strong rounded-2xl px-4 py-4"
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0 text-sm font-semibold leading-6">
                      {formatLedgerExplainabilityTitle(
                        item,
                        locale,
                        instrumentNames,
                      )}
                    </div>
                    {typeof item.amount === 'number' ? (
                      <div
                        className={`shrink-0 text-right text-sm font-semibold tabular-nums ${
                          item.amount < 0
                            ? 'text-[var(--app-pnl-negative)]'
                            : item.amount > 0
                              ? 'text-[var(--app-pnl-positive)]'
                              : 'text-[var(--app-pnl-neutral)]'
                        }`}
                      >
                        {formatCurrency(item.amount)}
                      </div>
                    ) : null}
                  </div>
                  {formatLedgerExplainabilityDetail(
                    item,
                    locale,
                    instrumentNames,
                  ) ? (
                    <div className="app-muted mt-2 break-words text-sm leading-6">
                      {formatLedgerExplainabilityDetail(
                        item,
                        locale,
                        instrumentNames,
                      )}
                    </div>
                  ) : null}
                  {item.timestamp ? (
                    <div className="app-kicker mt-3 text-[11px] tracking-[0.08em]">
                      {formatAuditTimestamp(item.timestamp)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>

          <div className="app-panel rounded-2xl p-4 sm:p-5">
            <div className="app-kicker text-xs uppercase tracking-[0.18em]">
              {stateLabelPositions}
            </div>
            <div className="mt-4 grid gap-3">
              {(explainability?.positions ?? []).map((item) => (
                <div
                  key={item.symbol}
                  className="app-panel-strong rounded-2xl px-4 py-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold">
                      {formatInstrumentDisplayLabel(
                        item.symbol,
                        instrumentNames,
                      )}
                    </div>
                    <div className="text-sm font-medium">
                      {formatCurrency(item.market_value)}
                    </div>
                  </div>
                  <div className="app-muted mt-2 text-sm">
                    {copy.explainability.quantity}{' '}
                    {formatQuantity(item.quantity)} ·{' '}
                    {copy.portfolio.table.unrealized}{' '}
                    {formatCurrency(item.unrealized_pnl)}
                  </div>
                  {item.last_activity_at ? (
                    <div className="app-kicker mt-3 text-[11px] tracking-[0.08em]">
                      {formatAuditTimestamp(item.last_activity_at)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="app-panel rounded-2xl p-4 sm:p-5">
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {copy.explainability.timeline}
        </div>
        {filters ? <div className="mt-4">{filters}</div> : null}
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(explainability?.timeline?.length
            ? explainability.timeline.slice().reverse()
            : [
                {
                  date: '',
                  equity: 0,
                  delta: 0,
                  external_flow: 0,
                  market_pnl: 0,
                  events: [],
                },
              ]
          ).map((point) => (
            <div
              key={`${point.date}-${point.equity}`}
              className="app-panel-strong rounded-2xl px-4 py-4"
            >
              {point.date ? (
                <>
                  <div className="text-sm font-semibold">{point.date}</div>
                  <div className="mt-3 grid gap-2">
                    <MetricBlock
                      label={copy.explainability.equity}
                      value={formatCurrency(point.equity)}
                    />
                    <MetricBlock
                      label={copy.explainability.netChange}
                      value={formatCurrency(point.delta)}
                    />
                    <MetricBlock
                      label={copy.explainability.externalFlow}
                      value={formatCurrency(point.external_flow)}
                    />
                    <MetricBlock
                      label={copy.explainability.marketPnl}
                      value={formatCurrency(point.market_pnl)}
                    />
                  </div>
                  {point.events.length > 0 ? (
                    <div className="mt-3 grid gap-2">
                      {point.events.map((event) => (
                        <div
                          key={`${event.timestamp}-${event.title}`}
                          className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_40%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_50%,transparent)] px-3 py-2"
                        >
                          <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                            {formatLedgerExplainabilityTitle(
                              event,
                              locale,
                              instrumentNames,
                            )}{' '}
                            · {getEventKindLabel(copy, event.kind)} ·{' '}
                            {getEventCategoryLabel(copy, event.category)} ·{' '}
                            {getImpactSourceLabel(copy, event.impact_source)}
                          </div>
                          {formatLedgerExplainabilityDetail(
                            event,
                            locale,
                            instrumentNames,
                          ) ? (
                            <div className="app-muted mt-1 text-xs leading-5">
                              {formatLedgerExplainabilityDetail(
                                event,
                                locale,
                                instrumentNames,
                              )}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="app-muted text-sm">
                  {copy.explainability.timelineEmpty}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {showReturnCalendar ? (
        <ReturnCalendarCard timeline={explainability?.timeline ?? []} />
      ) : null}
    </div>
  );
}

function MarketDataOperationsPanel({
  runs,
  loading,
  error,
  metadataPending,
  barsPending,
  onMetadataBackfill,
  onBarsBackfill,
}: {
  runs: QuoteFetchRun[];
  loading: boolean;
  error: boolean;
  metadataPending: boolean;
  barsPending: boolean;
  onMetadataBackfill: () => Promise<void>;
  onBarsBackfill: () => Promise<void>;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  return (
    <div className="space-y-3">
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {copy.market.dataOperations}
          </div>
          <p className="app-muted mt-2 break-words text-sm leading-6">
            {copy.market.dataOperationsDetail}
          </p>
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-2">
          <button
            type="button"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={metadataPending}
            onClick={() => void onMetadataBackfill()}
          >
            {metadataPending
              ? copy.market.backfilling
              : copy.market.metadataBackfill}
          </button>
          <button
            type="button"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={barsPending}
            onClick={() => void onBarsBackfill()}
          >
            {barsPending ? copy.market.backfilling : copy.market.barsBackfill}
          </button>
        </div>
      </div>
      {loading ? (
        <EvidenceState kind="loading" title={copy.states.loading} />
      ) : error ? (
        <EvidenceState kind="error" title={copy.market.quoteFetchRunsFailed} />
      ) : (
        <Timeline
          ariaLabel={copy.market.dataOperations}
          emptyState={copy.market.noQuoteFetchRuns}
          items={runs.slice(0, 4).map((run) => ({
            id: run.run_id,
            timestamp: formatTimestamp(run.started_at),
            title: `${formatPublicCode(run.trigger, locale)} · ${formatPublicStatus(run.status, locale)}`,
            description: `${copy.market.provider}: ${run.provider ?? copy.market.unknown} · ${copy.market.successCount}: ${run.success_count} · ${copy.market.failedCount}: ${run.failure_count} · ${copy.market.cacheHitCount}: ${run.cache_hit_count}`,
            evidence: run.error_message,
            tone:
              run.failure_count > 0 || run.error_message
                ? ('danger' as const)
                : run.status === 'completed'
                  ? ('success' as const)
                  : ('info' as const),
          }))}
        />
      )}
    </div>
  );
}

function MetricBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 bg-[var(--app-surface-raised)] px-4 py-3">
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
        {label}
      </div>
      <div className="mt-1.5 break-words text-sm font-medium">{value}</div>
    </div>
  );
}

function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(Math.round(seconds), 0)}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h`;
  }
  return `${Math.round(seconds / 86400)}d`;
}

function DrawdownChart({
  points,
}: {
  points: Array<{ timestamp: string; drawdown: number }>;
}) {
  const copy = useCopy();

  if (points.length === 0) {
    return (
      <div className="app-muted text-sm">
        {copy.explainability.timelineEmpty}
      </div>
    );
  }

  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 640;
      const y =
        (point.drawdown /
          Math.max(...points.map((item) => item.drawdown), 0.01)) *
        220;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg viewBox="0 0 640 220" className="h-48 w-full sm:h-56">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        points={path}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

type ReturnCalendarPeriod = 'day' | 'week' | 'month' | 'year';

type ReturnCalendarBreakdownItem = {
  key: string;
  label: string;
  value: number;
};

type ReturnCalendarRow = {
  label: string;
  delta: number;
  externalFlow: number;
  marketPnl: number;
  percentChange: number;
  valuationStatus: string;
  missingPriceSymbols: string[];
  marketBreakdown: ReturnCalendarBreakdownItem[];
  externalFlowBreakdown: ReturnCalendarBreakdownItem[];
};

type ReturnCalendarPosition = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  asset_class?: string | null;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
};

type ReturnCalendarMarketCalendar = Pick<
  MarketCalendarSnapshot,
  'days' | 'status'
>;

export function ReturnCalendarCard({
  timeline,
  positions = [],
  marketCalendar,
  compact = false,
}: {
  timeline: Array<{
    date: string;
    equity: number;
    delta: number;
    external_flow: number;
    market_pnl: number;
    valuation_status?: string;
    missing_price_symbols?: string[];
    market_breakdown?: ReturnCalendarBreakdownItem[];
    external_flow_breakdown?: ReturnCalendarBreakdownItem[];
  }>;
  positions?: ReturnCalendarPosition[];
  marketCalendar?: ReturnCalendarMarketCalendar | null;
  compact?: boolean;
}) {
  const copy = useCopy();
  const dailyRows = aggregateReturnTimeline(timeline, 'day');
  const weeklyRows = aggregateReturnTimeline(timeline, 'week');
  const monthlyRows = aggregateReturnTimeline(timeline, 'month');
  const yearlyRows = aggregateReturnTimeline(timeline, 'year');
  const monthOptions = Array.from(
    new Set(dailyRows.map((row) => row.label.slice(0, 7))),
  ).sort();
  const yearOptions = Array.from(
    new Set(monthlyRows.map((row) => row.label.slice(0, 4))),
  ).sort();
  const initialMonth = monthOptions[monthOptions.length - 1] ?? '';
  const initialYear = yearOptions[yearOptions.length - 1] ?? '';
  const [viewMode, setViewMode] = useState<'calendar' | 'table' | 'curve'>(
    'calendar',
  );
  const [period, setPeriod] = useState<ReturnCalendarPeriod>('day');
  const [metric, setMetric] = useState<'amount' | 'percent'>('amount');
  const [selectedMonth, setSelectedMonth] = useState(initialMonth);
  const [selectedYear, setSelectedYear] = useState(initialYear);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  const activeMonth = monthOptions.includes(selectedMonth)
    ? selectedMonth
    : initialMonth;
  const activeYear = yearOptions.includes(selectedYear)
    ? selectedYear
    : initialYear;

  const aggregated =
    period === 'day'
      ? dailyRows.filter((row) => row.label.startsWith(activeMonth))
      : period === 'week'
        ? weeklyRows.filter((row) => row.label.startsWith(activeYear))
        : period === 'month'
          ? monthlyRows.filter((row) => row.label.startsWith(activeYear))
          : yearlyRows;
  const selectedRow =
    aggregated.find((row) => row.label === selectedLabel) ??
    aggregated[aggregated.length - 1] ??
    null;
  const marketCalendarDays = useMemo(
    () => buildMarketCalendarDayMap(marketCalendar),
    [marketCalendar],
  );
  const panelClass = compact ? 'p-4' : 'app-panel rounded-2xl p-4 sm:p-5';
  const contentGridClass =
    period === 'week'
      ? compact
        ? 'return-calendar-layout-week mt-3 grid gap-3 2xl:grid-cols-1'
        : 'return-calendar-layout-week mt-4 grid gap-4 xl:grid-cols-1'
      : compact
        ? 'mt-3 grid gap-3 2xl:grid-cols-[minmax(0,1fr)_260px]'
        : 'mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]';
  const hasTimeline = timeline.length > 0;
  const valuationStatus = summarizeReturnCalendarStatus(aggregated);

  return (
    <div className={panelClass} data-testid="return-calendar-card">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {copy.explainability.returnCalendar}
          </div>
          <div className="app-muted mt-2 max-w-2xl text-sm">
            {copy.explainability.returnCalendarDetail}
          </div>
        </div>
      </div>
      {hasTimeline ? (
        <div className={`${compact ? 'mt-3' : 'mt-4'} min-w-0`}>
          <div
            className="grid min-w-0 items-center gap-3 rounded-2xl bg-[color-mix(in_srgb,var(--app-surface-1)_62%,transparent)] p-1.5 shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-border)_36%,transparent)] sm:grid-cols-[auto_minmax(14rem,1fr)_auto] sm:rounded-full"
            data-testid="return-calendar-toolbar"
          >
            <ReturnCalendarSegmentedControl
              compactMode="icon"
              label={copy.explainability.viewMode}
              options={[
                {
                  value: 'calendar',
                  label: copy.explainability.calendarView,
                  icon: <CalendarDays aria-hidden="true" size={18} />,
                },
                {
                  value: 'curve',
                  label: copy.explainability.curveView,
                  icon: <BarChart3 aria-hidden="true" size={18} />,
                },
                {
                  value: 'table',
                  label: copy.explainability.tableView,
                  icon: <Table2 aria-hidden="true" size={17} />,
                },
              ]}
              value={viewMode}
              onChange={(value) =>
                setViewMode(value as 'calendar' | 'table' | 'curve')
              }
            />
            <ReturnCalendarSegmentedControl
              compactMode="period"
              label={copy.explainability.periodMode}
              options={[
                { value: 'day', label: copy.explainability.day },
                { value: 'week', label: copy.explainability.week },
                { value: 'month', label: copy.explainability.month },
                { value: 'year', label: copy.explainability.year },
              ]}
              value={period}
              onChange={(value) => {
                setPeriod(value as ReturnCalendarPeriod);
                setSelectedLabel(null);
              }}
            />
            <ReturnCalendarSegmentedControl
              compactMode="metric"
              label={copy.explainability.metricMode}
              options={[
                {
                  value: 'amount',
                  label: copy.explainability.amountMetric,
                  icon: <CircleDollarSign aria-hidden="true" size={18} />,
                },
                {
                  value: 'percent',
                  label: copy.explainability.percentMetric,
                  icon: <Percent aria-hidden="true" size={18} />,
                },
              ]}
              value={metric}
              onChange={(value) => setMetric(value as 'amount' | 'percent')}
            />
          </div>
          <div className="mt-2 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            {period === 'day' ? (
              <select
                aria-label={copy.explainability.month}
                data-testid="return-calendar-period-select"
                value={activeMonth}
                onChange={(event) => {
                  setSelectedMonth(event.target.value);
                  setSelectedLabel(null);
                }}
                className="app-field h-9 min-w-0 rounded-full px-3 text-sm sm:w-40"
              >
                {monthOptions.map((month) => (
                  <option key={month} value={month}>
                    {month}
                  </option>
                ))}
              </select>
            ) : period === 'week' || period === 'month' ? (
              <select
                aria-label={copy.explainability.year}
                data-testid="return-calendar-period-select"
                value={activeYear}
                onChange={(event) => {
                  setSelectedYear(event.target.value);
                  setSelectedLabel(null);
                }}
                className="app-field h-9 min-w-0 rounded-full px-3 text-sm sm:w-32"
              >
                {yearOptions.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            ) : (
              <div className="hidden sm:block" aria-hidden="true" />
            )}
            <ReturnCalendarDataStatus
              status={valuationStatus}
              copy={copy}
              compact={compact}
            />
          </div>
        </div>
      ) : null}

      {aggregated.length === 0 ? (
        <ReturnCalendarEmptyState
          positions={positions}
          copy={copy}
          compact={compact}
        />
      ) : viewMode === 'calendar' ? (
        <div className={contentGridClass} data-testid="return-calendar-layout">
          <ReturnCalendarGrid
            rows={aggregated}
            period={period}
            activeMonth={activeMonth}
            activeYear={activeYear}
            metric={metric}
            copy={copy}
            compact={compact}
            selectedLabel={selectedRow?.label ?? null}
            onSelect={setSelectedLabel}
            marketCalendarDays={marketCalendarDays}
          />
          <ReturnCalendarDetail
            row={selectedRow}
            period={period}
            metric={metric}
            copy={copy}
            compact={compact}
          />
        </div>
      ) : viewMode === 'table' ? (
        <div className="mt-4 min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
          <table className="min-w-full text-left text-sm">
            <thead className="app-kicker text-[11px] uppercase tracking-[0.16em]">
              <tr>
                <th className="px-3 py-2">{copy.explainability.bucketLabel}</th>
                <th className="px-3 py-2">{copy.explainability.netChange}</th>
                <th className="px-3 py-2">
                  {copy.explainability.externalFlow}
                </th>
                <th className="px-3 py-2">{copy.explainability.marketPnl}</th>
              </tr>
            </thead>
            <tbody>
              {aggregated
                .slice()
                .reverse()
                .map((row) => {
                  const hasMissingValuation = row.valuationStatus === 'missing';
                  const returnValue = hasMissingValuation
                    ? copy.explainability.missingValuationShort
                    : metric === 'amount'
                      ? formatCurrency(row.delta)
                      : formatPercent(row.percentChange);
                  const marketValue = hasMissingValuation
                    ? copy.explainability.missingValuationShort
                    : formatCurrency(row.marketPnl);
                  return (
                    <tr
                      key={row.label}
                      className="border-t border-[var(--app-border)]"
                    >
                      <td className="px-3 py-3 font-medium">{row.label}</td>
                      <td className="px-3 py-3">{returnValue}</td>
                      <td className="px-3 py-3">
                        {formatCurrency(row.externalFlow)}
                      </td>
                      <td className="px-3 py-3">{marketValue}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4">
          <ReturnCurveChart
            points={aggregated.map((row) => ({
              label: row.label,
              value: metric === 'amount' ? row.marketPnl : row.percentChange,
            }))}
          />
        </div>
      )}
    </div>
  );
}

function ReturnCalendarSegmentedControl({
  compactMode = 'period',
  label,
  options,
  value,
  onChange,
}: {
  compactMode?: 'icon' | 'period' | 'metric';
  label: string;
  options: Array<{ value: string; label: string; icon?: ReactNode }>;
  value: string;
  onChange: (value: string) => void;
}) {
  const groupClass =
    compactMode === 'period'
      ? 'inline-flex w-full min-w-0 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_70%,transparent)] p-1 sm:justify-between'
      : 'inline-flex w-fit min-w-0 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_70%,transparent)] p-1';
  const buttonClass =
    compactMode === 'period'
      ? 'min-h-8 min-w-12 rounded-full px-4 py-1 text-base font-semibold transition sm:flex-1'
      : 'grid min-h-8 min-w-9 place-items-center rounded-full px-2 py-1 text-xs font-semibold transition';

  return (
    <div
      aria-label={label}
      className={`${groupClass} ${compactMode === 'metric' ? 'sm:justify-self-end' : ''}`}
      data-compact={compactMode}
      role="group"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            aria-label={option.label}
            onClick={() => onChange(option.value)}
            className={`${buttonClass} ${
              active
                ? 'bg-[var(--app-button)] text-[var(--app-button-text)] shadow-sm'
                : 'text-[color-mix(in_srgb,var(--app-muted)_78%,transparent)] hover:text-[var(--app-text)]'
            }`}
          >
            {option.icon ?? option.label}
            {option.icon ? (
              <span className="sr-only">{option.label}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function ReturnCalendarDataStatus({
  status,
  copy,
  compact,
}: {
  status: string;
  copy: AppCopy;
  compact: boolean;
}) {
  const detail =
    status === 'missing'
      ? copy.explainability.missingValuation
      : status === 'partial'
        ? copy.explainability.partialValuation
        : copy.explainability.confirmedValuation;
  const tone =
    status === 'missing'
      ? 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
      : status === 'partial'
        ? 'border-[color-mix(in_srgb,var(--app-accent-secondary)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-accent-secondary)_10%,transparent)] text-[var(--app-accent-secondary)]'
        : 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]';

  return (
    <div
      className={`${compact ? 'px-3 py-1.5' : 'px-3 py-2'} flex min-w-0 items-center gap-2 rounded-full border ${tone}`}
      data-testid="return-calendar-status-chip"
    >
      <div className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.12em]">
        {copy.explainability.dataStatus}
      </div>
      <div className="min-w-0 truncate text-xs font-semibold">{detail}</div>
    </div>
  );
}

function summarizeReturnCalendarStatus(rows: ReturnCalendarRow[]) {
  if (rows.some((row) => row.valuationStatus === 'missing')) {
    return 'missing';
  }
  if (rows.some((row) => row.valuationStatus === 'partial')) {
    return 'partial';
  }
  return 'complete';
}

function ReturnCalendarEmptyState({
  positions,
  copy,
  compact,
}: {
  positions: ReturnCalendarPosition[];
  copy: AppCopy;
  compact: boolean;
}) {
  const totalUnrealizedPnl = positions.reduce(
    (total, position) => total + position.unrealized_pnl,
    0,
  );
  const totalRealizedPnl = positions.reduce(
    (total, position) => total + position.realized_pnl,
    0,
  );
  const totalMarketValue = positions.reduce(
    (total, position) => total + position.market_value,
    0,
  );
  const totalPnl = totalUnrealizedPnl + totalRealizedPnl;
  const rankedPositions = positions
    .slice()
    .sort(
      (left, right) =>
        Math.abs(right.unrealized_pnl + right.realized_pnl) -
        Math.abs(left.unrealized_pnl + left.realized_pnl),
    )
    .slice(0, 4);
  const wrapperClass = compact
    ? 'mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_240px]'
    : 'mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]';

  return (
    <div className={wrapperClass} data-testid="return-calendar-empty-state">
      <div className="min-w-0 rounded-md border border-dashed border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-3">
        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
          {copy.explainability.currentPositionPnl}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <CalendarFallbackMetric
            label={copy.explainability.netChange}
            value={formatCurrency(totalPnl)}
          />
          <CalendarFallbackMetric
            label={copy.explainability.marketValue}
            value={formatCurrency(totalMarketValue)}
          />
          <CalendarFallbackMetric
            label={copy.explainability.unrealizedPnl}
            value={formatCurrency(totalUnrealizedPnl)}
          />
        </div>
        {rankedPositions.length > 0 ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {rankedPositions.map((position) => {
              const positionPnl =
                position.unrealized_pnl + position.realized_pnl;
              const displayName =
                position.display_name || position.name || position.symbol;
              const assetClass = position.asset_class || '--';
              const assetClassDisplay = formatAssetClassLabel(
                assetClass,
                copy.common,
              );
              return (
                <div
                  key={position.symbol}
                  className="rounded-md border border-[var(--app-border)] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate font-semibold">
                      {displayName}
                    </span>
                    <span
                      className={
                        positionPnl > 0
                          ? 'text-[var(--app-pnl-positive)]'
                          : positionPnl < 0
                            ? 'text-[var(--app-pnl-negative)]'
                            : 'text-[var(--app-pnl-neutral)]'
                      }
                    >
                      {formatCurrency(positionPnl)}
                    </span>
                  </div>
                  <div className="app-muted mt-1 flex items-center gap-2 text-[11px] uppercase">
                    <span>{position.symbol}</span>
                    <span aria-hidden="true">/</span>
                    <span>{assetClassDisplay}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
      <div className="rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_72%,transparent)] p-3">
        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
          {copy.explainability.returnCalendarWarmingUp}
        </div>
        <div className="app-muted mt-2 text-sm">
          {copy.explainability.returnCalendarEmptyDetail}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href="/activity"
            className="rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent)]"
          >
            {copy.explainability.addActivity}
          </a>
          <a
            href="/market"
            className="rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent)]"
          >
            {copy.explainability.checkDataSource}
          </a>
        </div>
      </div>
    </div>
  );
}

function CalendarFallbackMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_72%,transparent)] px-3 py-2">
      <div className="app-muted text-[11px]">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

function ReturnCurveChart({
  points,
}: {
  points: Array<{ label: string; value: number }>;
}) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (points.length === 0) {
    return null;
  }
  const width = 820;
  const height = 420;
  const left = 96;
  const right = 36;
  const top = 30;
  const bottom = 68;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const values = points.map((point) => point.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const positionForPoint = (point: { value: number }, index: number) => {
    const x = left + (index / Math.max(points.length - 1, 1)) * chartWidth;
    const y = top + chartHeight - ((point.value - min) / range) * chartHeight;
    return { x, y };
  };
  const positionedPoints = points.map((point, index) => ({
    ...point,
    ...positionForPoint(point, index),
  }));
  const line = positionedPoints
    .map((point) => `${point.x},${point.y}`)
    .join(' ');
  const ticks = Array.from(new Set(max === min ? [max] : [max, 0, min]));
  const zeroY = top + chartHeight - ((0 - min) / range) * chartHeight;
  const firstLabel = points[0]?.label ?? '';
  const lastLabel = points[points.length - 1]?.label ?? firstLabel;
  const activePoint =
    activeIndex === null ? null : (positionedPoints[activeIndex] ?? null);
  const tooltipX = activePoint
    ? Math.min(Math.max(activePoint.x + 12, left), width - 184)
    : 0;
  const tooltipY = activePoint ? Math.max(top + 6, activePoint.y - 54) : 0;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-[360px] w-full sm:h-[420px]"
      data-testid="return-curve-chart"
    >
      <line
        data-testid="return-curve-y-axis"
        x1={left}
        y1={top}
        x2={left}
        y2={top + chartHeight}
        stroke="currentColor"
        strokeOpacity="0.48"
        strokeWidth="1.2"
      />
      <line
        data-testid="return-curve-x-axis"
        x1={left}
        y1={top + chartHeight}
        x2={left + chartWidth}
        y2={top + chartHeight}
        stroke="currentColor"
        strokeOpacity="0.48"
        strokeWidth="1.2"
      />
      <line
        data-testid="return-curve-zero-axis"
        x1={left}
        y1={zeroY}
        x2={left + chartWidth}
        y2={zeroY}
        stroke="currentColor"
        strokeDasharray="4 5"
        strokeOpacity="0.34"
        strokeWidth="1.2"
      />
      {ticks.map((tick) => {
        const y = top + chartHeight - ((tick - min) / range) * chartHeight;
        return (
          <g key={tick}>
            <line
              x1={left}
              y1={y}
              x2={left + chartWidth}
              y2={y}
              stroke="currentColor"
              strokeOpacity="0.16"
            />
            <text
              x={left - 10}
              y={y + 5}
              textAnchor="end"
              className="fill-current text-[13px] font-semibold opacity-85"
            >
              {formatCurrency(tick)}
            </text>
          </g>
        );
      })}
      <text
        x={left}
        y={height - 16}
        textAnchor="start"
        className="fill-current text-[13px] font-semibold opacity-85"
      >
        {firstLabel}
      </text>
      <text
        x={left + chartWidth}
        y={height - 16}
        textAnchor="end"
        className="fill-current text-[13px] font-semibold opacity-85"
      >
        {lastLabel}
      </text>
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        points={line}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {positionedPoints.map((point, index) => (
        <circle
          key={point.label}
          cx={point.x}
          cy={point.y}
          r={activeIndex === index ? 6 : 4}
          tabIndex={0}
          role="img"
          aria-label={`${point.label} · ${formatCurrency(point.value)}`}
          data-testid={`return-curve-point-${index}`}
          fill="var(--app-text)"
          stroke="var(--app-mantle)"
          strokeWidth="2.4"
          opacity={activeIndex === null || activeIndex === index ? 1 : 0.56}
          onClick={() => setActiveIndex(index)}
          onFocus={() => setActiveIndex(index)}
          onBlur={() => setActiveIndex(null)}
          onPointerEnter={() => setActiveIndex(index)}
          onPointerMove={() => setActiveIndex(index)}
          onPointerLeave={() => setActiveIndex(null)}
          onMouseEnter={() => setActiveIndex(index)}
          onMouseLeave={() => setActiveIndex(null)}
        />
      ))}
      {activePoint ? (
        <g data-testid="return-curve-tooltip">
          <rect
            x={tooltipX}
            y={tooltipY}
            width="162"
            height="46"
            rx="10"
            fill="var(--app-panel-strong)"
            stroke="var(--app-border)"
            opacity="0.98"
          />
          <text
            x={tooltipX + 12}
            y={tooltipY + 18}
            className="fill-current text-[12px] font-semibold"
          >
            {activePoint.label}
          </text>
          <text
            x={tooltipX + 12}
            y={tooltipY + 36}
            className="fill-current text-[13px] font-bold"
          >
            {formatCurrency(activePoint.value)}
          </text>
        </g>
      ) : null}
    </svg>
  );
}

function aggregateReturnTimeline(
  timeline: Array<{
    date: string;
    equity: number;
    delta: number;
    external_flow: number;
    market_pnl: number;
    valuation_status?: string;
    missing_price_symbols?: string[];
    market_breakdown?: ReturnCalendarBreakdownItem[];
    external_flow_breakdown?: ReturnCalendarBreakdownItem[];
  }>,
  bucket: 'day' | 'week' | 'month' | 'year',
) {
  const groups = new Map<
    string,
    {
      label: string;
      delta: number;
      externalFlow: number;
      marketPnl: number;
      startEquity: number;
      endEquity: number;
      valuationStatus: string;
      missingPriceSymbols: Set<string>;
      marketBreakdown: Map<string, ReturnCalendarBreakdownItem>;
      externalFlowBreakdown: Map<string, ReturnCalendarBreakdownItem>;
    }
  >();

  timeline.forEach((point) => {
    const label = toReturnBucket(point.date, bucket);
    const existing = groups.get(label);
    const previousEquity = point.equity - point.delta;
    const missingPriceSymbols = point.missing_price_symbols ?? [];
    const valuationStatus =
      missingPriceSymbols.length > 0
        ? 'missing'
        : normalizeValuationStatus(point.valuation_status);
    if (existing) {
      existing.delta += point.delta;
      existing.externalFlow += point.external_flow;
      existing.marketPnl += point.market_pnl;
      existing.endEquity = point.equity;
      existing.valuationStatus = combineValuationStatus(
        existing.valuationStatus,
        valuationStatus,
      );
      mergeBreakdownItems(existing.marketBreakdown, point.market_breakdown);
      mergeBreakdownItems(
        existing.externalFlowBreakdown,
        point.external_flow_breakdown,
      );
      missingPriceSymbols.forEach((symbol) =>
        existing.missingPriceSymbols.add(symbol),
      );
      return;
    }
    groups.set(label, {
      label,
      delta: point.delta,
      externalFlow: point.external_flow,
      marketPnl: point.market_pnl,
      startEquity: previousEquity,
      endEquity: point.equity,
      valuationStatus,
      missingPriceSymbols: new Set(missingPriceSymbols),
      marketBreakdown: buildBreakdownMap(point.market_breakdown),
      externalFlowBreakdown: buildBreakdownMap(point.external_flow_breakdown),
    });
  });

  return Array.from(groups.values()).map((row) => ({
    ...row,
    missingPriceSymbols: Array.from(row.missingPriceSymbols).sort(),
    marketBreakdown: Array.from(row.marketBreakdown.values()).filter(
      (item) => Math.abs(item.value) > 0.000001,
    ),
    externalFlowBreakdown: Array.from(
      row.externalFlowBreakdown.values(),
    ).filter((item) => Math.abs(item.value) > 0.000001),
    percentChange:
      row.startEquity === 0 ? 0 : row.marketPnl / Math.abs(row.startEquity),
  }));
}

function buildBreakdownMap(items: ReturnCalendarBreakdownItem[] | undefined) {
  const map = new Map<string, ReturnCalendarBreakdownItem>();
  mergeBreakdownItems(map, items);
  return map;
}

function mergeBreakdownItems(
  target: Map<string, ReturnCalendarBreakdownItem>,
  items: ReturnCalendarBreakdownItem[] | undefined,
) {
  (items ?? []).forEach((item) => {
    const existing = target.get(item.key);
    if (existing) {
      target.set(item.key, {
        ...existing,
        value: existing.value + item.value,
      });
      return;
    }
    target.set(item.key, { ...item });
  });
}

function normalizeValuationStatus(status: string | undefined) {
  const normalized =
    status
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_') ?? '';
  if (
    ['missing', 'unavailable', 'missing_price_symbols'].includes(normalized)
  ) {
    return 'missing';
  }
  if (
    [
      'partial',
      'cache',
      'cached',
      'cache_only',
      'estimated',
      'estimate',
      'stale',
      'quote_older_than_expected_session',
      'confirmed_nav_missing',
      'confirmed_fund_nav_missing_estimate_only',
    ].includes(normalized)
  ) {
    return 'partial';
  }
  return 'complete';
}

function combineValuationStatus(left: string, right: string) {
  if (left === 'missing' || right === 'missing') {
    return 'missing';
  }
  if (left === 'partial' || right === 'partial') {
    return 'partial';
  }
  return 'complete';
}

function toReturnBucket(
  dateText: string,
  bucket: 'day' | 'week' | 'month' | 'year',
) {
  if (bucket === 'day') {
    return dateText;
  }
  const date = new Date(`${dateText}T00:00:00`);
  if (bucket === 'month') {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  }
  if (bucket === 'year') {
    return `${date.getFullYear()}`;
  }
  return toReturnWeekBucket(date);
}

function toReturnWeekBucket(date: Date) {
  const year = date.getFullYear();
  const slot = buildReturnWeekSlots(String(year)).find(
    (item) => date >= item.startDate && date <= item.endDate,
  );
  return slot?.label ?? `${year}-W01`;
}

function buildReturnWeekSlots(yearText: string) {
  const year = Number(yearText);
  if (!Number.isFinite(year)) {
    return [];
  }

  const slots: Array<{
    label: string;
    weekNumber: number;
    startDate: Date;
    endDate: Date;
    rangeLabel: string;
  }> = [];
  const yearEnd = new Date(year, 11, 31);
  const cursor = new Date(year, 0, 1);
  let weekNumber = 1;

  while (cursor <= yearEnd) {
    const startDate = new Date(cursor);
    const endDate = new Date(cursor);
    endDate.setDate(endDate.getDate() + (6 - startDate.getDay()));
    if (endDate > yearEnd) {
      endDate.setTime(yearEnd.getTime());
    }

    slots.push({
      label: `${year}-W${String(weekNumber).padStart(2, '0')}`,
      weekNumber,
      startDate,
      endDate,
      rangeLabel: `${formatReturnMonthDay(startDate)}-${formatReturnMonthDay(
        endDate,
      )}`,
    });

    cursor.setTime(endDate.getTime());
    cursor.setDate(cursor.getDate() + 1);
    weekNumber += 1;
  }

  return slots;
}

function formatReturnWeekHeading(weekNumber: number, copy: AppCopy) {
  if (copy.explainability.week === '周') {
    return `第${weekNumber}周`;
  }
  return `${copy.explainability.week} ${weekNumber}`;
}

function formatReturnCalendarDetailTitle(
  row: ReturnCalendarRow,
  period: ReturnCalendarPeriod,
  copy: AppCopy,
) {
  if (period !== 'week') {
    return row.label;
  }

  const match = /^(\d{4})-W(\d{2})$/.exec(row.label);
  const slot = match
    ? buildReturnWeekSlots(match[1]).find(
        (item) => item.weekNumber === Number(match[2]),
      )
    : null;
  if (!slot) {
    return row.label;
  }

  return `${formatReturnWeekHeading(slot.weekNumber, copy)} · ${
    slot.rangeLabel
  }`;
}

function formatReturnMonthDay(date: Date) {
  return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(
    date.getDate(),
  ).padStart(2, '0')}`;
}

function formatPercent(value: number) {
  return formatPercentValue(value, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}

function formatCurrency(value: number) {
  return formatCurrencyValue(value);
}

function formatCompactReturnCurrency(value: number) {
  if (value === 0) {
    return '0.00';
  }
  const sign = value > 0 ? '+' : '-';
  return `${sign}${Math.abs(value).toFixed(2)}`;
}

function formatAuditTimestamp(timestamp: string) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

function resolveInstrumentName(
  symbol: string | null | undefined,
  instrumentNames?: Map<string, string>,
) {
  const normalizedSymbol = symbol?.trim();
  if (!normalizedSymbol) {
    return null;
  }
  return instrumentNames?.get(normalizedSymbol.toLowerCase()) ?? null;
}

function formatInstrumentDisplayLabel(
  symbol: string,
  instrumentNames?: Map<string, string>,
) {
  const name = resolveInstrumentName(symbol, instrumentNames);
  if (!name || name === symbol) {
    return symbol;
  }
  return `${name} ${symbol}`;
}

function ReturnCalendarGrid({
  rows,
  period,
  activeMonth,
  activeYear,
  metric,
  copy,
  compact,
  selectedLabel,
  onSelect,
  marketCalendarDays,
}: {
  rows: ReturnCalendarRow[];
  period: ReturnCalendarPeriod;
  activeMonth: string;
  activeYear: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
  marketCalendarDays: Map<string, MarketCalendarDay>;
}) {
  const maxMagnitude = Math.max(
    ...rows.map((row) =>
      Math.abs(metric === 'amount' ? row.marketPnl : row.percentChange),
    ),
    0.0001,
  );

  if (period === 'day') {
    return (
      <ReturnMonthGrid
        rows={rows}
        activeMonth={activeMonth}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
        marketCalendarDays={marketCalendarDays}
      />
    );
  }

  if (period === 'week') {
    return (
      <ReturnWeekGrid
        rows={rows}
        activeYear={activeYear}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
      />
    );
  }

  if (period === 'month') {
    return (
      <ReturnYearGrid
        rows={rows}
        activeYear={activeYear}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
      />
    );
  }

  return (
    <ReturnYearsGrid
      rows={rows}
      metric={metric}
      compact={compact}
      maxMagnitude={maxMagnitude}
      selectedLabel={selectedLabel}
      onSelect={onSelect}
    />
  );
}

function ReturnMonthGrid({
  rows,
  activeMonth,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
  marketCalendarDays,
}: {
  rows: ReturnCalendarRow[];
  activeMonth: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
  marketCalendarDays: Map<string, MarketCalendarDay>;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  const firstDay = new Date(`${activeMonth}-01T00:00:00`);
  const month = firstDay.getMonth();
  const year = firstDay.getFullYear();
  const leadingBlanks = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [
    ...Array.from({ length: leadingBlanks }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ];
  const gapClass = compact ? 'gap-1.5' : 'gap-2';
  const blankClass = compact
    ? 'min-h-[4.25rem] rounded-md'
    : 'min-h-[5.75rem] rounded-lg';

  return (
    <div className="min-w-0">
      <div
        className={`app-kicker grid grid-cols-7 ${gapClass} text-center text-[11px] uppercase tracking-[0.14em]`}
      >
        {copy.explainability.weekdays.map((day) => (
          <div key={day} data-testid="return-calendar-weekday">
            {day}
          </div>
        ))}
      </div>
      <div
        className={`mt-2 grid grid-cols-7 ${gapClass}`}
        data-testid="return-calendar-month-grid"
      >
        {cells.map((day, index) => {
          if (day === null) {
            return (
              <div
                key={`blank-${index}`}
                className={`${blankClass} border border-dashed border-[color-mix(in_srgb,var(--app-border)_44%,transparent)]`}
              />
            );
          }
          const label = `${activeMonth}-${String(day).padStart(2, '0')}`;
          const row = rowsByLabel.get(label);
          const calendarDay =
            marketCalendarDays.get(label) ?? explainMarketCalendarDate(label);
          return (
            <ReturnCalendarCell
              key={label}
              label={label}
              heading={String(day)}
              row={row}
              calendarDay={calendarDay}
              metric={metric}
              maxMagnitude={maxMagnitude}
              selected={selectedLabel === label}
              onSelect={onSelect}
              compact={compact}
            />
          );
        })}
      </div>
    </div>
  );
}

function ReturnWeekGrid({
  rows,
  activeYear,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  activeYear: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  const slots = buildReturnWeekSlots(activeYear);

  return (
    <div
      className={`grid ${compact ? 'max-h-[34rem] gap-1.5' : 'max-h-[38rem] gap-2'} overflow-y-auto overscroll-contain pr-1 sm:grid-cols-2 md:grid-cols-3`}
      data-testid="return-calendar-week-grid"
    >
      {slots.map((slot) => (
        <ReturnCalendarCell
          key={slot.label}
          label={slot.label}
          heading={formatReturnWeekHeading(slot.weekNumber, copy)}
          sublabel={slot.rangeLabel}
          row={rowsByLabel.get(slot.label)}
          metric={metric}
          maxMagnitude={maxMagnitude}
          selected={selectedLabel === slot.label}
          onSelect={onSelect}
          compact={compact}
        />
      ))}
    </div>
  );
}

function ReturnYearGrid({
  rows,
  activeYear,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  activeYear: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  return (
    <div
      className={`grid ${compact ? 'gap-1.5' : 'gap-2'} sm:grid-cols-3 xl:grid-cols-4`}
      data-testid="return-calendar-year-grid"
    >
      {Array.from({ length: 12 }, (_, index) => {
        const label = `${activeYear}-${String(index + 1).padStart(2, '0')}`;
        return (
          <ReturnCalendarCell
            key={label}
            label={label}
            heading={label.slice(5)}
            row={rowsByLabel.get(label)}
            metric={metric}
            maxMagnitude={maxMagnitude}
            selected={selectedLabel === label}
            onSelect={onSelect}
            sublabel={copy.explainability.month}
            compact={compact}
          />
        );
      })}
    </div>
  );
}

function ReturnYearsGrid({
  rows,
  metric,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  metric: 'amount' | 'percent';
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  return (
    <div
      className={`grid ${compact ? 'gap-1.5' : 'gap-2'} sm:grid-cols-2 xl:grid-cols-3`}
      data-testid="return-calendar-years-grid"
    >
      {rows
        .slice()
        .reverse()
        .map((row) => (
          <ReturnCalendarCell
            key={row.label}
            label={row.label}
            heading={row.label}
            row={row}
            metric={metric}
            maxMagnitude={maxMagnitude}
            selected={selectedLabel === row.label}
            onSelect={onSelect}
            compact={compact}
          />
        ))}
    </div>
  );
}

function formatReturnCalendarCellHeading(heading: string, sublabel?: string) {
  if (!sublabel) {
    return { headingText: heading, sublabelText: null };
  }
  if (/^\d{2}$/.test(heading)) {
    return {
      headingText:
        sublabel === '月' ? `${heading}${sublabel}` : `${heading} ${sublabel}`,
      sublabelText: null,
    };
  }
  return { headingText: heading, sublabelText: sublabel };
}

function ReturnCalendarCell({
  label,
  heading,
  row,
  calendarDay,
  metric,
  maxMagnitude,
  selected,
  onSelect,
  sublabel,
  compact,
}: {
  label: string;
  heading: string;
  row: ReturnCalendarRow | undefined;
  calendarDay?: MarketCalendarDay;
  metric: 'amount' | 'percent';
  maxMagnitude: number;
  selected: boolean;
  onSelect: (label: string) => void;
  sublabel?: string;
  compact: boolean;
}) {
  const copy = useCopy();
  const hasMissingValuation =
    row !== undefined && row.valuationStatus === 'missing';
  const hasUnconfirmedValuation =
    row !== undefined && row.valuationStatus === 'partial';
  const value = row
    ? metric === 'amount'
      ? row.marketPnl
      : row.percentChange
    : 0;
  const displayValue = row
    ? hasMissingValuation
      ? copy.explainability.missingValuationShort
      : metric === 'amount'
        ? formatCurrency(row.marketPnl)
        : formatPercent(row.percentChange)
    : '--';
  const nonTradingLabel =
    !row && calendarDay && !calendarDay.isTradingDay
      ? formatMarketCalendarClosedLabel(calendarDay, copy)
      : null;
  const rowNonTradingLabel =
    row && calendarDay && !calendarDay.isTradingDay
      ? formatMarketCalendarClosedLabel(calendarDay, copy)
      : null;
  const cellDisplayValue =
    rowNonTradingLabel ??
    (compact && row && !hasMissingValuation && metric === 'amount'
      ? formatCompactReturnCurrency(row.marketPnl)
      : (nonTradingLabel ?? displayValue));
  const cellAccessibleValue =
    rowNonTradingLabel ?? nonTradingLabel ?? displayValue;
  const tone = row
    ? hasMissingValuation
      ? 'border-dashed border-[color-mix(in_srgb,var(--app-border)_72%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_64%,transparent)] text-[var(--app-muted)]'
      : getHeatmapTone(value, maxMagnitude)
    : 'border-[color-mix(in_srgb,var(--app-border)_54%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_42%,transparent)] text-[var(--app-muted)]';
  const cellClass = compact
    ? 'flex min-h-[4.25rem] min-w-0 flex-col overflow-hidden rounded-md px-1.5 py-2'
    : 'flex min-h-[5.75rem] min-w-0 flex-col overflow-hidden rounded-lg px-3 py-3';
  const valueClass = compact
    ? 'mt-auto self-end whitespace-nowrap text-right text-[10px] font-semibold leading-4 sm:text-[11px]'
    : 'mt-auto max-w-full self-end break-words text-right text-base font-semibold leading-tight';
  const metaClass = compact
    ? 'mt-1 self-end text-right text-[10px] opacity-80'
    : 'mt-2 self-end text-right text-[11px] opacity-80';
  const { headingText, sublabelText } = formatReturnCalendarCellHeading(
    heading,
    sublabel,
  );

  if (!row) {
    return (
      <div className={`${cellClass} border ${tone}`}>
        <div
          className="text-xs font-semibold"
          data-testid="return-calendar-cell-heading"
        >
          {headingText}
        </div>
        {sublabelText ? (
          <div className="app-muted mt-1 text-[11px]">{sublabelText}</div>
        ) : null}
        <div className={valueClass} data-testid="return-calendar-cell-value">
          {cellDisplayValue}
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`${label} · ${cellAccessibleValue}`}
      onClick={() => onSelect(label)}
      className={`${cellClass} border text-left transition hover:-translate-y-0.5 focus:outline-none focus:ring-2 focus:ring-[color-mix(in_srgb,var(--app-accent)_58%,transparent)] ${
        selected ? 'ring-2 ring-[var(--app-accent)]' : ''
      } ${tone}`}
    >
      <div
        className="text-xs font-semibold"
        data-testid="return-calendar-cell-heading"
      >
        {headingText}
      </div>
      {sublabelText ? (
        <div className="mt-1 text-[11px] opacity-70">{sublabelText}</div>
      ) : null}
      <div className={valueClass} data-testid="return-calendar-cell-value">
        {cellDisplayValue}
      </div>
      {hasMissingValuation && row.missingPriceSymbols.length > 0 ? (
        <div className={metaClass}>
          {row.missingPriceSymbols.slice(0, 2).join(', ')}
        </div>
      ) : null}
      {hasUnconfirmedValuation ? (
        <div className={metaClass}>
          {copy.explainability.unconfirmedValuationShort}
        </div>
      ) : null}
    </button>
  );
}

function ReturnCalendarDetail({
  row,
  period,
  metric,
  copy,
  compact,
}: {
  row: ReturnCalendarRow | null;
  period: ReturnCalendarPeriod;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
}) {
  const detailClass = compact
    ? 'rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-3'
    : 'rounded-lg border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-4';

  if (row === null) {
    return (
      <div
        className={`${compact ? 'rounded-md p-3' : 'rounded-lg p-4'} border border-dashed border-[var(--app-border)] text-sm text-[var(--app-muted)]`}
      >
        {copy.explainability.timelineEmpty}
      </div>
    );
  }

  const hasMissingValuation = row.valuationStatus === 'missing';
  const hasUnconfirmedValuation = row.valuationStatus === 'partial';
  const returnValue = hasMissingValuation
    ? copy.explainability.missingValuationShort
    : metric === 'amount'
      ? formatCurrency(row.delta)
      : formatPercent(row.percentChange);
  const marketValue = hasMissingValuation
    ? copy.explainability.missingValuationShort
    : formatCurrency(row.marketPnl);
  const detailTitle = formatReturnCalendarDetailTitle(row, period, copy);
  const netChangeLabel =
    period === 'day'
      ? copy.explainability.netChangeDaily
      : period === 'week'
        ? copy.explainability.netChangeWeekly
        : period === 'month'
          ? copy.explainability.netChangeMonthly
          : copy.explainability.netChangeAnnual;

  return (
    <div className={detailClass}>
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
        {copy.explainability.selectedPeriod}
      </div>
      <div
        className={`${compact ? 'mt-1 text-base' : 'mt-2 text-lg'} font-semibold`}
      >
        {detailTitle}
      </div>
      <div
        className={`${compact ? 'mt-3 space-y-2' : 'mt-4 space-y-3'} text-sm`}
      >
        <CalendarDetailMetric label={netChangeLabel} value={returnValue} />
        <CalendarDetailMetric
          label={copy.explainability.marketPnl}
          value={marketValue}
        />
        {row.marketBreakdown.length > 0 ? (
          <CalendarDetailBreakdown
            items={row.marketBreakdown}
            labelForKey={(item) =>
              copy.explainability.marketBreakdownLabels[
                item.key as keyof typeof copy.explainability.marketBreakdownLabels
              ] ?? item.label
            }
          />
        ) : null}
        <CalendarDetailMetric
          label={copy.explainability.externalFlow}
          value={formatCurrency(row.externalFlow)}
        />
        {row.externalFlowBreakdown.length > 0 ? (
          <CalendarDetailBreakdown
            items={row.externalFlowBreakdown}
            labelForKey={(item) =>
              copy.explainability.externalFlowBreakdownLabels[
                item.key as keyof typeof copy.explainability.externalFlowBreakdownLabels
              ] ?? item.label
            }
          />
        ) : null}
        {hasMissingValuation || hasUnconfirmedValuation ? (
          <CalendarDetailMetric
            label={copy.explainability.valuationCoverage}
            value={
              hasMissingValuation && row.missingPriceSymbols.length > 0
                ? `${copy.explainability.missingHistoricalPrices}: ${row.missingPriceSymbols.join(', ')}`
                : copy.explainability.partialValuation
            }
          />
        ) : null}
      </div>
    </div>
  );
}

function buildMarketCalendarDayMap(
  marketCalendar?: ReturnCalendarMarketCalendar | null,
) {
  const days =
    marketCalendar?.status === 'missing' ? [] : (marketCalendar?.days ?? []);
  return new Map(
    days.map((day) => [
      day.date,
      {
        schemaVersion: MARKET_CALENDAR_SCHEMA_VERSION,
        date: day.date,
        dayType: day.day_type,
        reasonCode: day.reason_code,
        reason: day.reason,
        isTradingDay: day.is_trading_day,
      } satisfies MarketCalendarDay,
    ]),
  );
}

function formatMarketCalendarClosedLabel(
  day: MarketCalendarDay,
  copy: AppCopy,
) {
  if (day.dayType === 'holiday') {
    return isGenericMarketCalendarReason(day.reason)
      ? copy.explainability.marketHolidayShort
      : day.reason;
  }
  if (day.dayType === 'weekend') {
    return isGenericMarketCalendarReason(day.reason)
      ? copy.explainability.marketWeekendShort
      : day.reason;
  }
  return isGenericMarketCalendarReason(day.reason)
    ? copy.explainability.marketClosedShort
    : day.reason;
}

function isGenericMarketCalendarReason(reason: string | null | undefined) {
  const normalized = (reason ?? '').trim().toLowerCase();
  return (
    normalized === '' ||
    normalized === 'weekend' ||
    normalized === 'exchange closed'
  );
}

function CalendarDetailMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-[var(--app-border)] pt-3 first:border-t-0 first:pt-0">
      <span className="app-muted">{label}</span>
      <span className="text-right font-semibold">{value}</span>
    </div>
  );
}

function CalendarDetailBreakdown({
  items,
  labelForKey,
}: {
  items: ReturnCalendarBreakdownItem[];
  labelForKey: (item: ReturnCalendarBreakdownItem) => string;
}) {
  return (
    <div className="space-y-2 border-t border-[var(--app-border)] pt-3">
      {items.map((item) => (
        <div
          key={item.key}
          className="flex items-center justify-between gap-3 text-xs"
        >
          <span className="app-muted">{labelForKey(item)}</span>
          <span className="text-right font-semibold">
            {formatCurrency(item.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function getHeatmapTone(value: number, maxMagnitude: number) {
  const intensity = Math.min(Math.abs(value) / maxMagnitude, 1);

  if (value > 0) {
    if (intensity > 0.66) {
      return 'app-heat-positive-strong';
    }
    if (intensity > 0.33) {
      return 'app-heat-positive-medium';
    }
    return 'app-heat-positive-soft';
  }

  if (value < 0) {
    if (intensity > 0.66) {
      return 'app-heat-negative-strong';
    }
    if (intensity > 0.33) {
      return 'app-heat-negative-medium';
    }
    return 'app-heat-negative-soft';
  }

  return 'border-[var(--app-border)] bg-[var(--app-panel-strong)] text-[var(--app-foreground)]';
}

function getAssetClassLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'stock':
      return copy.common.assetClassStock;
    case 'etf':
      return copy.common.assetClassEtf;
    case 'fund':
      return copy.common.assetClassFund;
    case 'gold':
      return copy.common.assetClassGold;
    case 'bond':
      return copy.common.assetClassBond;
    default:
      return value;
  }
}

function getNoteTypeLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'note':
      return copy.market.note;
    case 'thesis':
      return copy.market.thesis;
    case 'catalyst':
      return copy.market.catalyst;
    default:
      return value;
  }
}

function getPriorityLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'high':
      return copy.market.highPriority;
    case 'normal':
      return copy.market.normalPriority;
    case 'low':
      return copy.market.lowPriority;
    default:
      return value;
  }
}

function getEventKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'cash_deposit':
      return copy.explainability.deposits;
    case 'cash_withdrawal':
      return copy.explainability.withdrawals;
    case 'dividend':
      return copy.explainability.dividends;
    case 'trade_buy':
      return copy.explainability.buys;
    case 'trade_sell':
      return copy.explainability.sells;
    case 'manual_adjustment':
      return copy.explainability.adjustments;
    default:
      return value;
  }
}

function getEventCategoryLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'capital':
      return copy.explainability.categoryCapital;
    case 'income':
      return copy.explainability.categoryIncome;
    case 'override':
      return copy.explainability.categoryOverride;
    case 'trade':
      return copy.explainability.categoryTrade;
    default:
      return value;
  }
}

function getImpactSourceLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'external':
      return copy.explainability.sourceExternal;
    case 'cash':
      return copy.explainability.sourceCash;
    case 'manual':
      return copy.explainability.sourceManual;
    case 'positioning':
      return copy.explainability.sourcePositioning;
    default:
      return value;
  }
}

function getRiskMetricLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'current_drawdown':
      return copy.riskPage.currentDrawdown;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdown;
    case 'gross_exposure':
      return copy.riskPage.grossExposure;
    case 'cash_ratio':
      return copy.riskPage.cashRatio;
    case 'largest_weight':
      return copy.riskPage.largestPosition;
    case 'top3_weight':
      return copy.riskPage.top3Concentration;
    default:
      return value;
  }
}

function getRiskMetricDetail(copy: AppCopy, value: string) {
  switch (value) {
    case 'current_drawdown':
      return copy.riskPage.currentDrawdownDetail;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdownDetail;
    case 'gross_exposure':
      return copy.riskPage.grossExposureDetail;
    case 'cash_ratio':
      return copy.riskPage.cashRatioDetail;
    case 'largest_weight':
      return copy.riskPage.largestPositionDetail;
    case 'top3_weight':
      return copy.riskPage.top3ConcentrationDetail;
    default:
      return value;
  }
}

function getRiskAlertKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'cash_buffer':
      return copy.overview.risk.cashBuffer;
    case 'concentration':
    case 'largest_weight':
      return copy.overview.risk.concentration;
    case 'gross_exposure':
    case 'capital_deployment':
      return copy.overview.risk.deployment;
    case 'current_drawdown':
      return copy.riskPage.currentDrawdown;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdown;
    case 'market_data':
    case 'data':
      return copy.decision.marketData;
    case 'manual_confirmation':
      return copy.overview.risk.manualConfirmationRequired;
    default:
      return value;
  }
}

function formatRiskAlertDetail(value: string, locale: Locale) {
  const quoteTimestamp = /^(\S+)\s+最新快照时间\s+(.+)$/u.exec(value.trim());
  if (quoteTimestamp) {
    const [, symbol, timestamp] = quoteTimestamp;
    return locale === 'zh'
      ? `${symbol} 最新行情截至 ${formatTimestamp(timestamp)}`
      : `${symbol} quote evidence as of ${formatTimestamp(timestamp)}`;
  }
  return formatPublicNote(value, locale);
}

function formatRiskAlertLevel(level: string, locale: Locale) {
  const normalized = level.trim().toLowerCase();
  if (normalized === 'medium') {
    return formatPublicStatus('warning', locale);
  }
  if (normalized === 'high') {
    return formatPublicStatus('blocked', locale);
  }
  if (normalized === 'low') {
    return formatPublicStatus('healthy', locale);
  }
  return formatPublicStatus(level, locale);
}

function getRiskBucketLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'heavy':
      return copy.riskPage.bucketHeavy;
    case 'core':
      return copy.riskPage.bucketCore;
    case 'starter':
      return copy.riskPage.bucketStarter;
    case 'small':
      return copy.riskPage.bucketSmall;
    case 'cash':
      return copy.riskPage.bucketCash;
    default:
      return value;
  }
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
      <div className="text-sm font-semibold tracking-[-0.01em]">{title}</div>
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

function getErrorMessage(error: unknown) {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return 'Request failed. Check the form values and service status.';
}
