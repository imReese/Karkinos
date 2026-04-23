import { useState, type ReactNode } from "react";
import {
  createRoute,
  createRootRoute,
  createRouter,
  Outlet,
  useNavigate,
} from "@tanstack/react-router";

import { useCopy, type AppCopy } from "./copy";
import { ToastStack, type ToastItem } from "./components/toast-stack";
import { AppShell } from "./layout/app-shell";
import {
  useAccountOverviewQuery,
  useAccountStateQuery,
  useExplainabilityQuery,
  useEquityCurveSeriesQuery,
  useRiskSummaryQuery,
  useRiskWorkspaceQuery,
} from "../features/account/api";
import {
  EquityCurveCard,
  EquityCurveSkeleton,
} from "../features/account/components/equity-curve-card";
import { LiveHoldingsSummaryCard } from "../features/account/components/live-holdings-summary-card";
import {
  OverviewCards,
  OverviewCardsSkeleton,
} from "../features/account/components/overview-cards";
import { PerformanceBreakdownCard } from "../features/account/components/performance-breakdown-card";
import { RiskSummaryCard } from "../features/account/components/risk-summary-card";
import {
  useCreateAdjustmentMutation,
  useCreateCashFlowMutation,
  useCreateDividendMutation,
  useCreateTradeMutation,
  useLedgerEntriesQuery,
  usePendingFundOrdersQuery,
} from "../features/activity/api";
import { ActivityFeed } from "../features/activity/components/activity-feed";
import {
  CashFlowForm,
  type CashFlowFormValues,
} from "../features/activity/components/cash-flow-form";
import {
  DividendForm,
  type DividendFormValues,
} from "../features/activity/components/dividend-form";
import {
  ManualAdjustmentForm,
  type ManualAdjustmentFormValues,
} from "../features/activity/components/manual-adjustment-form";
import {
  TradeForm,
  type TradeFormValues,
} from "../features/activity/components/trade-form";
import {
  FundBatchForm,
  type FundBatchFormValues,
} from "../features/activity/components/fund-batch-form";
import {
  type AllocationGroup,
  type AllocationItem,
  useLiveHoldingsQuery,
  usePortfolioSnapshotQuery,
  usePositionsQuery,
} from "../features/portfolio/api";
import { AllocationCard } from "../features/portfolio/components/allocation-card";
import { AllocationGroupsCard } from "../features/portfolio/components/allocation-groups-card";
import { LiveHoldingsBoard } from "../features/portfolio/components/live-holdings-board";
import { PositionsTable } from "../features/portfolio/components/positions-table";
import { WorkspaceToolbar } from "../features/portfolio/components/workspace-toolbar";
import {
  useAddWatchlistItemMutation,
  useCreateResearchNoteMutation,
  useUpdateResearchNoteMutation,
  useDeleteResearchNoteMutation,
  useKlineQuery,
  useResearchBoardQuery,
  useResearchNotesQuery,
  useRemoveWatchlistItemMutation,
} from "../features/market/api";

type PortfolioSearchState = {
  assetClass: string;
  pnl: "all" | "winners" | "losers";
  q: string;
};

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: OverviewPage,
});

const portfolioRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/portfolio",
  validateSearch: (search: Record<string, unknown>) => ({
    assetClass:
      typeof search.assetClass === "string" && search.assetClass.length > 0
        ? search.assetClass
        : "all",
    pnl:
      search.pnl === "winners" || search.pnl === "losers" || search.pnl === "all"
        ? search.pnl
        : "all",
    q: typeof search.q === "string" ? search.q : "",
  }),
  component: PortfolioPage,
});

const activityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/activity",
  component: ActivityPage,
});

const riskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/risk",
  component: RiskPage,
});

const marketRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/market",
  component: MarketPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: PlaceholderPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  portfolioRoute,
  activityRoute,
  riskRoute,
  marketRoute,
  settingsRoute,
]);

export const router = createRouter({ routeTree });

function OverviewPage() {
  const copy = useCopy();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"account" | "strategy">("account");
  const overview = useAccountOverviewQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const liveHoldings = useLiveHoldingsQuery();
  const equityCurve = useEquityCurveSeriesQuery();
  const explainability = useExplainabilityQuery();

  return (
    <section className="space-y-3">
      <PageHeader
        kicker={copy.overview.kicker}
        title={copy.overview.title}
        subtitle={copy.overview.subtitle}
      />

      {overview.isLoading || snapshot.isLoading ? (
        <div className="space-y-3">
          <OverviewCardsSkeleton />
          <section className="app-surface-section overflow-hidden rounded-xl">
            <div className="app-surface-section-header">
              <div>
                <div className="app-product-mark">{copy.overview.kicker}</div>
                <div className="mt-1.5 text-base font-semibold">
                  {copy.overview.title}
                </div>
              </div>
            </div>
            <div className="app-surface-pane min-w-0">
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
        <div className="space-y-3">
          <OverviewCards overview={overview.data} />
          {liveHoldings.isLoading ? (
            <StatusCard title={copy.states.loading} detail={copy.overview.livePulse.loading} />
          ) : liveHoldings.isError ? (
            <StatusCard
              tone="danger"
              title={copy.states.error}
              detail={copy.overview.livePulse.error}
              actionLabel={copy.states.retry}
              onAction={() => void liveHoldings.refetch()}
            />
          ) : (
            <LiveHoldingsSummaryCard
              groups={liveHoldings.data?.groups ?? []}
              onSelectAssetClass={(assetClass) => {
                void navigate({
                  to: "/portfolio",
                  search: {
                    assetClass,
                    pnl: "all",
                    q: "",
                  },
                });
              }}
            />
          )}
          <ExplainabilityCard
            drivers={explainability.data?.recent_drivers ?? []}
            isLoading={explainability.isLoading}
          />
          <section className="app-surface-section overflow-hidden rounded-xl">
            <div className="app-surface-section-header">
              <div>
                <div className="app-product-mark">{copy.overview.kicker}</div>
                <div className="mt-1.5 text-base font-semibold">
                  {copy.overview.title}
                </div>
              </div>
            </div>
            <div className="grid gap-0 xl:grid-cols-[minmax(0,1.28fr)_minmax(340px,0.92fr)]">
              <div className="app-surface-pane min-w-0">
                {equityCurve.isLoading ? (
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
                  <EquityCurveCard points={equityCurve.data ?? []} />
                )}
              </div>
              <div className="app-surface-pane app-surface-pane-accent min-w-0 xl:border-l">
                <PerformanceBreakdownCard
                  overview={overview.data}
                  snapshot={snapshot.data}
                  mode={mode}
                  onModeChange={setMode}
                  accountLabel={copy.mode.account}
                  strategyLabel={copy.mode.strategy}
                />
              </div>
            </div>
          </section>
          <section className="app-surface-section overflow-hidden rounded-xl">
            <RiskSummaryCard overview={overview.data} snapshot={snapshot.data} />
          </section>
        </div>
      ) : (
        <StatusCard title={copy.states.empty} detail={copy.overview.empty} />
      )}
    </section>
  );
}

function PortfolioPage() {
  const copy = useCopy();
  const navigate = useNavigate();
  const searchState = portfolioRoute.useSearch();
  const [mode, setMode] = useState<"account" | "strategy">("account");
  const overview = useAccountOverviewQuery();
  const positions = usePositionsQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const liveHoldings = useLiveHoldingsQuery();
  const explainability = useExplainabilityQuery();
  const search = searchState.q;
  const assetClassFilter = searchState.assetClass;
  const pnlFilter = searchState.pnl as "all" | "winners" | "losers";

  const allocationBySymbol = new Map(
    (snapshot.data?.allocation ?? []).map((item) => [item.symbol, item]),
  );
  const assetClasses = Array.from(
    new Set((snapshot.data?.allocation ?? []).map((item) => item.asset_class)),
  );
  const filteredPositions = (positions.data ?? []).filter((position) => {
    const assetClass = allocationBySymbol.get(position.symbol)?.asset_class ?? "unknown";
    const matchesSearch =
      search.trim().length === 0 ||
      position.symbol.toLowerCase().includes(search.trim().toLowerCase());
    const matchesAssetClass =
      assetClassFilter === "all" || assetClass === assetClassFilter;
    const matchesPnl =
      pnlFilter === "all" ||
      (pnlFilter === "winners" && position.unrealized_pnl >= 0) ||
      (pnlFilter === "losers" && position.unrealized_pnl < 0);
    return matchesSearch && matchesAssetClass && matchesPnl;
  });

  const filteredSymbols = new Set(filteredPositions.map((position) => position.symbol));
  const filteredAllocation = (snapshot.data?.allocation ?? []).filter((item) =>
    filteredSymbols.has(item.symbol),
  );
  const filteredGroups = groupAllocation(filteredAllocation);
  const filteredLiveGroups = (liveHoldings.data?.groups ?? [])
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        const matchesSearch =
          search.trim().length === 0 ||
          item.symbol.toLowerCase().includes(search.trim().toLowerCase()) ||
          item.name.toLowerCase().includes(search.trim().toLowerCase());
        const matchesAssetClass =
          assetClassFilter === "all" || group.asset_class === assetClassFilter;
        const matchesPnl =
          pnlFilter === "all" ||
          (pnlFilter === "winners" && item.since_buy_pnl >= 0) ||
          (pnlFilter === "losers" && item.since_buy_pnl < 0);
        return matchesSearch && matchesAssetClass && matchesPnl;
      }),
    }))
    .filter((group) => group.items.length > 0)
    .map((group) => ({
      ...group,
      total_market_value: group.items.reduce((sum, item) => sum + item.market_value, 0),
      total_today_change: group.items.reduce((sum, item) => sum + (item.today_change ?? 0), 0),
      total_since_buy_pnl: group.items.reduce((sum, item) => sum + item.since_buy_pnl, 0),
    }));

  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        kicker={copy.portfolio.kicker}
        title={copy.portfolio.title}
        subtitle={copy.portfolio.subtitle}
      />

      <WorkspaceToolbar
        mode={mode}
        onModeChange={setMode}
        search={search}
        onSearchChange={(value) => {
          void navigate({
            to: "/portfolio",
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
            to: "/portfolio",
            search: (current: PortfolioSearchState) => ({
              ...current,
              assetClass: value,
            }),
          });
        }}
        pnlFilter={pnlFilter}
        onPnlFilterChange={(value) => {
          void navigate({
            to: "/portfolio",
            search: (current: PortfolioSearchState) => ({
              ...current,
              pnl: value,
            }),
          });
        }}
        assetClasses={assetClasses}
      />

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,0.95fr)]">
        <div className="min-w-0 space-y-5 sm:space-y-6">
          {liveHoldings.isLoading ? (
            <StatusCard title={copy.states.loading} detail={copy.portfolio.liveBoard.loading} />
          ) : liveHoldings.isError ? (
            <StatusCard
              tone="danger"
              title={copy.states.error}
              detail={copy.portfolio.liveBoard.error}
              actionLabel={copy.states.retry}
              onAction={() => void liveHoldings.refetch()}
            />
          ) : (
            <LiveHoldingsBoard groups={filteredLiveGroups} />
          )}
          <ExplainabilityCard
            drivers={explainability.data?.recent_drivers ?? []}
            isLoading={explainability.isLoading}
          />
          {positions.isLoading ? (
            <StatusCard title={copy.states.loading} detail={copy.portfolio.positionsLoading} />
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
            />
          )}
        </div>

        <div className="min-w-0 space-y-5 sm:space-y-6">
          {snapshot.isLoading || overview.isLoading ? (
            <StatusCard title={copy.states.loading} detail={copy.portfolio.sidebarLoading} />
          ) : snapshot.isError || overview.isError ? (
            <StatusCard
              tone="danger"
              title={copy.states.error}
              detail={copy.portfolio.sidebarError}
              actionLabel={copy.states.retry}
              onAction={() => {
                void snapshot.refetch();
                void overview.refetch();
              }}
            />
          ) : snapshot.data && overview.data ? (
            <>
              <PerformanceBreakdownCard
                overview={overview.data}
                snapshot={snapshot.data}
                mode={mode}
                onModeChange={setMode}
                accountLabel={copy.mode.account}
                strategyLabel={copy.mode.strategy}
              />
              <RiskSummaryCard overview={overview.data} snapshot={snapshot.data} />
              <AllocationCard items={filteredAllocation} />
              <AllocationGroupsCard groups={filteredGroups} />
            </>
          ) : (
            <StatusCard title={copy.states.empty} detail={copy.portfolio.sidebarEmpty} />
          )}
        </div>
      </div>
    </section>
  );
}

function RiskPage() {
  const copy = useCopy();
  const state = useAccountStateQuery();
  const risks = useRiskSummaryQuery();
  const workspace = useRiskWorkspaceQuery();
  const [timelineFromDate, setTimelineFromDate] = useState("");
  const [timelineToDate, setTimelineToDate] = useState("");
  const [timelineEventKind, setTimelineEventKind] = useState("");
  const explainability = useExplainabilityQuery({
    from_date: timelineFromDate || undefined,
    to_date: timelineToDate || undefined,
    event_kind: timelineEventKind || undefined,
  });

  return (
    <section className="space-y-5 sm:space-y-6">
      <PageHeader
        kicker={copy.riskPage.kicker}
        title={copy.riskPage.title}
        subtitle={copy.riskPage.subtitle}
      />

      {state.isLoading || risks.isLoading || workspace.isLoading ? (
        <StatusCard title={copy.states.loading} detail={copy.riskPage.loading} />
      ) : state.isError || risks.isError || workspace.isError || !state.data || !workspace.data ? (
        <StatusCard title={copy.states.error} detail={copy.riskPage.error} tone="danger" />
      ) : (
        <div className="space-y-5 sm:space-y-6">
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {workspace.data.metrics.map((metric) => (
              <div key={metric.key} className="app-panel rounded-2xl p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {getRiskMetricLabel(copy, metric.key)}
                </div>
                <div className="mt-3 text-2xl font-semibold">{metric.display_value}</div>
                <div className="app-muted mt-2 text-sm">
                  {getRiskMetricDetail(copy, metric.key)}
                </div>
              </div>
            ))}
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]">
            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                {copy.riskPage.alerts}
              </div>
              <div className="mt-4 grid gap-3">
                {risks.data?.map((item) => (
                  <div
                    key={`${item.kind}-${item.title}`}
                    className={`rounded-2xl border px-4 py-4 ${
                      item.level === "high" || item.level === "medium"
                        ? "app-panel-danger"
                        : "app-panel-strong"
                    }`}
                  >
                    <div className="text-sm font-semibold">{item.title}</div>
                    <div className="mt-2 text-sm opacity-90">{item.detail}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-5">
              <RiskSummaryCard
                overview={state.data.summary}
                snapshot={state.data.snapshot}
              />
              <div className="app-panel rounded-2xl p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.riskPage.nextStep}
                </div>
                <div className="mt-3 text-lg font-semibold">{state.data.next_step}</div>
              </div>
            </div>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                {copy.riskPage.drawdown}
              </div>
              <div className="mt-4">
                <DrawdownChart points={workspace.data.drawdown_series} />
              </div>
            </div>
            <div className="space-y-5">
              <div className="app-panel rounded-2xl p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.riskPage.exposure}
                </div>
                <div className="mt-4 grid gap-3">
                  {workspace.data.exposure_buckets.map((bucket) => (
                    <div key={bucket.bucket} className="app-panel-strong rounded-2xl px-4 py-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold">
                          {getRiskBucketLabel(copy, bucket.bucket)}
                        </div>
                        <div className="text-sm font-medium">
                          {Math.round(bucket.weight * 1000) / 10}%
                        </div>
                      </div>
                      <div className="app-muted mt-2 text-sm">
                        {formatCurrency(bucket.value)} ·{" "}
                        {copy.overview.risk.positionsHint(bucket.positions_count)}
                      </div>
                      {bucket.symbols.length > 0 ? (
                        <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
                          {bucket.symbols.join(" · ")}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>

              <div className="app-panel rounded-2xl p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.riskPage.concentration}
                </div>
                <div className="mt-4 grid gap-3">
                  {workspace.data.concentration.length > 0 ? (
                    workspace.data.concentration.map((item) => (
                      <div key={item.symbol} className="app-panel-strong rounded-2xl px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold">{item.symbol}</div>
                          <div className="text-sm font-medium">
                            {Math.round(item.weight * 1000) / 10}%
                          </div>
                        </div>
                        <div className="app-muted mt-2 text-sm">
                          {formatCurrency(item.market_value)} ·{" "}
                          {copy.portfolio.table.unrealized} {formatCurrency(item.unrealized_pnl)}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="app-muted text-sm">{copy.riskPage.noConcentration}</div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <ExplainabilityWorkspace
            title={copy.riskPage.equityBridge}
            stateLabelRecent={copy.riskPage.recentDrivers}
            stateLabelPositions={copy.riskPage.positionDrivers}
            emptyLabel={copy.riskPage.emptyDrivers}
            explainability={explainability.data}
            loading={explainability.isLoading}
            filters={
              <div className="grid gap-3 md:grid-cols-3">
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.noteDateFrom}</span>
                  <input
                    type="date"
                    value={timelineFromDate}
                    onChange={(event) => setTimelineFromDate(event.target.value)}
                    className="app-field rounded-xl px-3 py-2 text-sm"
                    aria-label={copy.market.noteDateFrom}
                  />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.noteDateTo}</span>
                  <input
                    type="date"
                    value={timelineToDate}
                    onChange={(event) => setTimelineToDate(event.target.value)}
                    className="app-field rounded-xl px-3 py-2 text-sm"
                    aria-label={copy.market.noteDateTo}
                  />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">
                    {copy.explainability.timelineEventKind}
                  </span>
                  <select
                    value={timelineEventKind}
                    onChange={(event) => setTimelineEventKind(event.target.value)}
                    className="app-field rounded-xl px-3 py-2 text-sm"
                    aria-label={copy.explainability.timelineEventKind}
                  >
                    <option value="">{copy.explainability.allEvents}</option>
                    <option value="cash_deposit">{copy.explainability.deposits}</option>
                    <option value="cash_withdrawal">{copy.explainability.withdrawals}</option>
                    <option value="dividend">{copy.explainability.dividends}</option>
                    <option value="trade_buy">{copy.explainability.buys}</option>
                    <option value="trade_sell">{copy.explainability.sells}</option>
                    <option value="manual_adjustment">{copy.explainability.adjustments}</option>
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

function MarketPage() {
  const copy = useCopy();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const board = useResearchBoardQuery();
  const addWatchlistItem = useAddWatchlistItemMutation();
  const removeWatchlistItem = useRemoveWatchlistItemMutation();
  const createResearchNote = useCreateResearchNoteMutation();
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const [newAssetClass, setNewAssetClass] = useState("stock");
  const [noteFilterType, setNoteFilterType] = useState("");
  const [noteFilterPriority, setNoteFilterPriority] = useState("");
  const [noteFilterDateFrom, setNoteFilterDateFrom] = useState("");
  const [noteFilterDateTo, setNoteFilterDateTo] = useState("");
  const [noteType, setNoteType] = useState("note");
  const [notePriority, setNotePriority] = useState("normal");
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [noteDate, setNoteDate] = useState("");
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const items = board.data?.items ?? [];
  const activeSymbol = selectedSymbol || items[0]?.symbol || "";
  const updateResearchNote = useUpdateResearchNoteMutation(activeSymbol);
  const selectedItem = items.find((item) => item.symbol === activeSymbol) ?? null;
  const kline = useKlineQuery(activeSymbol);
  const notes = useResearchNotesQuery(activeSymbol, {
    entry_kind: noteFilterType || undefined,
    priority: noteFilterPriority || undefined,
    event_date_from: noteFilterDateFrom || undefined,
    event_date_to: noteFilterDateTo || undefined,
  });
  const deleteResearchNote = useDeleteResearchNoteMutation(activeSymbol);
  const assetClassOptions = [
    ["stock", copy.common.assetClassStock],
    ["etf", copy.common.assetClassEtf],
    ["fund", copy.common.assetClassFund],
    ["gold", copy.common.assetClassGold],
    ["bond", copy.common.assetClassBond],
  ] as const;

  const pushToast = (tone: ToastItem["tone"], title: string, message: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, tone, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  };

  return (
    <>
      <ToastStack toasts={toasts} />
      <section className="space-y-5 sm:space-y-6">
        <PageHeader
          kicker={copy.market.kicker}
          title={copy.market.title}
          subtitle={copy.market.subtitle}
        />

        {board.isLoading ? (
          <StatusCard title={copy.states.loading} detail={copy.market.loading} />
        ) : board.isError ? (
          <StatusCard title={copy.states.error} detail={copy.market.error} tone="danger" />
        ) : (
          <div className="space-y-5 sm:space-y-6">
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(300px,0.9fr)]">
            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.market.watchlist}
                </div>
                <div className="app-muted text-sm">
                  {board.data?.health.market_open
                    ? copy.market.marketOpen
                    : copy.market.marketClosed}
                </div>
              </div>

              <form
                className="mb-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_160px_100px]"
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (!newSymbol.trim()) {
                    return;
                  }
                  await addWatchlistItem.mutateAsync({
                    symbol: newSymbol.trim(),
                    asset_class: newAssetClass,
                  });
                  setNewSymbol("");
                  setSelectedSymbol("");
                }}
              >
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.symbolLabel}</span>
                <input
                  name="watchlist_symbol"
                  autoComplete="off"
                  value={newSymbol}
                  onChange={(event) => setNewSymbol(event.target.value)}
                  placeholder={copy.market.symbolPlaceholder}
                  className="app-field rounded-xl px-3 py-2 text-sm"
                />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.assetClass}</span>
                <select
                  name="watchlist_asset_class"
                  value={newAssetClass}
                  onChange={(event) => setNewAssetClass(event.target.value)}
                  className="app-field rounded-xl px-3 py-2 text-sm"
                >
                  {assetClassOptions.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                </label>
                <button type="submit" className="app-button-primary rounded-xl px-4 py-2 text-sm">
                  {copy.market.add}
                </button>
              </form>

              <div className="grid gap-3">
                {items.map((item) => (
                  <button
                    key={item.symbol}
                    type="button"
                    onClick={() => setSelectedSymbol(item.symbol)}
                    className={`app-panel-strong rounded-2xl p-4 text-left ${
                      activeSymbol === item.symbol ? "ring-1 ring-[var(--app-border)]" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold">{item.symbol}</div>
                        <div className="app-muted mt-1 text-xs">
                          {getAssetClassLabel(copy, item.asset_class)}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="app-button-secondary rounded-xl px-3 py-1 text-xs"
                        onClick={async (event) => {
                          event.stopPropagation();
                          await removeWatchlistItem.mutateAsync(item.symbol);
                          if (activeSymbol === item.symbol) {
                            setSelectedSymbol("");
                          }
                        }}
                      >
                        {copy.market.remove}
                      </button>
                    </div>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2">
                      <div>
                        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                          {copy.market.priceLabel}
                        </div>
                        <div className="mt-1 text-sm font-medium">
                          {formatCurrency(item.price ?? 0)}
                        </div>
                      </div>
                      <div>
                        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                          {copy.market.holdingsContext}
                        </div>
                        <div className="mt-1 text-sm font-medium">
                          {item.is_holding
                            ? formatCurrency(item.market_value ?? 0)
                            : "--"}
                        </div>
                      </div>
                      <div>
                        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                          {copy.market.researchCount}
                        </div>
                        <div className="mt-1 text-sm font-medium">{item.research_count}</div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-5">
              <div className="app-panel rounded-2xl p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.market.health}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <MetricBlock
                    label={copy.market.marketOpen}
                    value={
                      board.data?.health.market_open
                        ? copy.market.marketOpen
                        : copy.market.marketClosed
                    }
                  />
                  <MetricBlock
                    label={copy.market.refreshPolicy}
                    value={board.data?.health.refresh_policy ?? "--"}
                  />
                </div>
              </div>
              <div className="app-panel rounded-2xl p-4 sm:p-5">
                <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                  {copy.market.promptsTitle}
                </div>
                <div className="mt-4 grid gap-3">
                  {copy.market.prompts.map((prompt) => (
                    <div key={prompt} className="app-panel-strong rounded-2xl px-4 py-3 text-sm">
                      {prompt}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                {copy.market.chart}
              </div>
              <div className="mt-4">
                {selectedItem ? (
                  <PriceStructureChart bars={kline.data ?? []} emptyLabel={copy.market.noChart} />
                ) : (
                  <div className="app-muted text-sm">{copy.market.noSelection}</div>
                )}
              </div>
            </div>
            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                {copy.market.selectedSymbol}
              </div>
              {selectedItem ? (
                <div className="mt-4 space-y-3">
                  <MetricBlock label={copy.market.symbolLabel} value={selectedItem.symbol} />
                  <MetricBlock
                    label={copy.market.priceLabel}
                    value={formatCurrency(selectedItem.price ?? 0)}
                  />
                  <MetricBlock
                    label={copy.market.holdingsContext}
                    value={
                      selectedItem.is_holding
                        ? `${copy.explainability.quantity} ${selectedItem.quantity ?? 0} / ${formatCurrency(
                            selectedItem.market_value ?? 0,
                          )}`
                        : "--"
                    }
                  />
                  <MetricBlock
                    label={copy.market.snapshotLabel}
                    value={selectedItem.last_snapshot_at ?? "--"}
                  />
                  <MetricBlock
                    label={copy.market.lastResearch}
                    value={selectedItem.last_research_at ?? "--"}
                  />
                </div>
              ) : (
                <div className="app-muted mt-4 text-sm">{copy.market.noSelection}</div>
              )}
            </div>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                {copy.market.notesTitle}
              </div>
              {selectedItem ? (
                <form
                  className="mt-4 grid gap-3"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    if (!noteTitle.trim() || !noteContent.trim()) {
                      pushToast("error", copy.market.noteFailed, copy.common.required);
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
                      setNoteType("note");
                      setNotePriority("normal");
                      setNoteTitle("");
                      setNoteContent("");
                      setNoteDate("");
                      pushToast(
                        "success",
                        editingNoteId !== null ? copy.market.updateNote : copy.market.noteSaved,
                        selectedItem.symbol,
                      );
                    } catch (error) {
                      pushToast("error", copy.market.noteFailed, getErrorMessage(error));
                    }
                  }}
                >
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">{copy.market.noteType}</span>
                    <select
                      name="research_note_type"
                      value={noteType}
                      onChange={(event) => setNoteType(event.target.value)}
                      className="app-field rounded-xl px-3 py-2 text-sm"
                    >
                      <option value="note">{copy.market.note}</option>
                      <option value="thesis">{copy.market.thesis}</option>
                      <option value="catalyst">{copy.market.catalyst}</option>
                    </select>
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">{copy.market.notePriority}</span>
                    <select
                      name="research_note_priority"
                      value={notePriority}
                      onChange={(event) => setNotePriority(event.target.value)}
                      className="app-field rounded-xl px-3 py-2 text-sm"
                    >
                      <option value="high">{copy.market.highPriority}</option>
                      <option value="normal">{copy.market.normalPriority}</option>
                      <option value="low">{copy.market.lowPriority}</option>
                    </select>
                    </label>
                  </div>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">{copy.market.noteTitle}</span>
                  <input
                    name="research_note_title"
                    autoComplete="off"
                    value={noteTitle}
                    onChange={(event) => setNoteTitle(event.target.value)}
                    placeholder={copy.market.noteTitlePlaceholder}
                    className="app-field rounded-xl px-3 py-2 text-sm"
                  />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">{copy.market.noteContent}</span>
                  <textarea
                    name="research_note_content"
                    value={noteContent}
                    onChange={(event) => setNoteContent(event.target.value)}
                    placeholder={copy.market.noteContentPlaceholder}
                    rows={5}
                    className="app-field min-h-32 rounded-xl px-3 py-2 text-sm"
                  />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">{copy.market.noteDate}</span>
                  <input
                    name="research_note_date"
                    type="date"
                    value={noteDate}
                    onChange={(event) => setNoteDate(event.target.value)}
                    className="app-field rounded-xl px-3 py-2 text-sm"
                  />
                  </label>
                  <button
                    type="submit"
                    disabled={createResearchNote.isPending || updateResearchNote.isPending}
                    className="app-button-primary rounded-xl px-4 py-2 text-sm"
                  >
                    {createResearchNote.isPending || updateResearchNote.isPending
                      ? copy.market.savingNote
                      : editingNoteId !== null
                        ? copy.market.updateNote
                        : copy.market.saveNote}
                  </button>
                </form>
              ) : (
                <div className="app-muted mt-4 text-sm">{copy.market.noSelection}</div>
              )}
            </div>

            <div className="app-panel rounded-2xl p-4 sm:p-5">
              <div className="app-kicker text-xs uppercase tracking-[0.18em]">
                {copy.market.notesTitle}
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-4">
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.noteType}</span>
                <select
                  value={noteFilterType}
                  onChange={(event) => setNoteFilterType(event.target.value)}
                  className="app-field rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">{copy.market.allTypes}</option>
                  <option value="note">{copy.market.note}</option>
                  <option value="thesis">{copy.market.thesis}</option>
                  <option value="catalyst">{copy.market.catalyst}</option>
                </select>
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.notePriority}</span>
                <select
                  value={noteFilterPriority}
                  onChange={(event) => setNoteFilterPriority(event.target.value)}
                  className="app-field rounded-xl px-3 py-2 text-sm"
                >
                  <option value="">{copy.market.allPriorities}</option>
                  <option value="high">{copy.market.highPriority}</option>
                  <option value="normal">{copy.market.normalPriority}</option>
                  <option value="low">{copy.market.lowPriority}</option>
                </select>
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.noteDateFrom}</span>
                <input
                  type="date"
                  value={noteFilterDateFrom}
                  onChange={(event) => setNoteFilterDateFrom(event.target.value)}
                  className="app-field rounded-xl px-3 py-2 text-sm"
                  aria-label={copy.market.noteDateFrom}
                />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">{copy.market.noteDateTo}</span>
                <input
                  type="date"
                  value={noteFilterDateTo}
                  onChange={(event) => setNoteFilterDateTo(event.target.value)}
                  className="app-field rounded-xl px-3 py-2 text-sm"
                  aria-label={copy.market.noteDateTo}
                />
                </label>
              </div>
              {notes.isLoading ? (
                <div className="app-muted mt-4 text-sm">{copy.states.loading}</div>
              ) : notes.isError ? (
                <div className="app-muted mt-4 text-sm">{copy.market.noteFailed}</div>
              ) : notes.data && notes.data.items.length > 0 ? (
                <div className="mt-4 grid gap-3">
                  {notes.data.items.map((note) => (
                    <div key={note.id} className="app-panel-strong rounded-2xl px-4 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold">{note.title}</div>
                          <div className="app-kicker mt-2 text-[11px] uppercase tracking-[0.16em]">
                            {getNoteTypeLabel(copy, note.entry_kind)} ·{" "}
                            {getPriorityLabel(copy, note.priority)}
                            {note.event_date ? ` · ${note.event_date}` : ""}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            className="app-button-secondary rounded-xl px-3 py-1 text-xs"
                            onClick={() => {
                              setEditingNoteId(note.id);
                              setNoteType(note.entry_kind);
                              setNotePriority(note.priority);
                              setNoteTitle(note.title);
                              setNoteContent(note.content);
                              setNoteDate(note.event_date ?? "");
                            }}
                          >
                            {copy.market.editNote}
                          </button>
                          <button
                            type="button"
                            className="app-button-secondary rounded-xl px-3 py-1 text-xs"
                            onClick={async () => {
                              try {
                                await deleteResearchNote.mutateAsync(note.id);
                                pushToast("success", copy.market.noteDeleted, note.title);
                              } catch (error) {
                                pushToast(
                                  "error",
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
                      <div className="app-muted mt-3 text-sm leading-6">{note.content}</div>
                      <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
                        {note.updated_at}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="app-muted mt-4 text-sm">{copy.market.notesEmpty}</div>
              )}
            </div>
          </div>
        </div>
        )}
      </section>
    </>
  );
}

function ActivityPage() {
  const copy = useCopy();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const entries = useLedgerEntriesQuery();
  const pendingFundOrders = usePendingFundOrdersQuery();
  const createTrade = useCreateTradeMutation();
  const createCashFlow = useCreateCashFlowMutation();
  const createDividend = useCreateDividendMutation();
  const createAdjustment = useCreateAdjustmentMutation();

  const pushToast = (tone: ToastItem["tone"], title: string, message: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, tone, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  };

  const handleTradeSubmit = async (values: TradeFormValues) => {
    const normalizeNumber = (value: number | null | undefined) =>
      typeof value === "number" && Number.isFinite(value) ? value : null;
    try {
      await createTrade.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
        quantity: normalizeNumber(values.quantity),
        unit_price: normalizeNumber(values.unit_price),
        amount: normalizeNumber(values.amount),
        fee: normalizeNumber(values.fee) ?? 0,
        asset_class: values.asset_class.trim().toLowerCase(),
        symbol: values.symbol.trim(),
      });
      pushToast("success", copy.activity.tradeSaved, copy.activity.feedRefreshed);
    } catch (error) {
      pushToast("error", copy.activity.tradeFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleFundBatchSubmit = async (values: FundBatchFormValues) => {
    try {
      for (const order of values.orders) {
        await createTrade.mutateAsync({
          occurred_at: new Date(values.occurred_at).toISOString(),
          symbol: order.symbol,
          asset_class: "fund",
          direction: "buy",
          quantity: null,
          unit_price: null,
          amount: order.amount,
          fee: 0,
          note: [values.note.trim(), order.display_name, copy.activity.forms.fundBatch.title]
            .filter(Boolean)
            .join(" | "),
        });
      }
      pushToast("success", copy.activity.tradeSaved, copy.activity.feedRefreshed);
    } catch (error) {
      pushToast("error", copy.activity.tradeFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleCashFlowSubmit = async (values: CashFlowFormValues) => {
    try {
      await createCashFlow.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
      pushToast("success", copy.activity.cashFlowSaved, copy.activity.feedRefreshed);
    } catch (error) {
      pushToast("error", copy.activity.cashFlowFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleDividendSubmit = async (values: DividendFormValues) => {
    try {
      await createDividend.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
      pushToast("success", copy.activity.dividendSaved, copy.activity.feedRefreshed);
    } catch (error) {
      pushToast("error", copy.activity.dividendFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleAdjustmentSubmit = async (values: ManualAdjustmentFormValues) => {
    try {
      await createAdjustment.mutateAsync({
        ...values,
        symbol: values.symbol || null,
        amount:
          values.amount === null || Number.isNaN(values.amount) ? null : values.amount,
        quantity:
          values.quantity === null || Number.isNaN(values.quantity)
            ? null
            : values.quantity,
        price:
          values.price === null || Number.isNaN(values.price) ? null : values.price,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
      pushToast("success", copy.activity.adjustmentSaved, copy.activity.feedRefreshed);
    } catch (error) {
      pushToast("error", copy.activity.adjustmentFailed, getErrorMessage(error));
      throw error;
    }
  };

  return (
    <>
      <ToastStack toasts={toasts} />
      <section className="space-y-6">
        <header className="space-y-2">
          <div className="app-kicker text-xs font-medium uppercase tracking-[0.24em]">
            {copy.activity.kicker}
          </div>
          <h1 className="text-3xl font-semibold">{copy.activity.title}</h1>
          <p className="app-muted max-w-2xl text-sm leading-6">
            {copy.activity.subtitle}
          </p>
        </header>

        <div className="grid gap-6 xl:grid-cols-[1.05fr_1.05fr_1.4fr]">
          <div className="space-y-6">
            <FundBatchForm
              onSubmit={handleFundBatchSubmit}
              pending={createTrade.isPending}
            />
            <TradeForm onSubmit={handleTradeSubmit} pending={createTrade.isPending} />
            <DividendForm
              onSubmit={handleDividendSubmit}
              pending={createDividend.isPending}
            />
          </div>
          <div className="space-y-6">
            <CashFlowForm
              onSubmit={handleCashFlowSubmit}
              pending={createCashFlow.isPending}
            />
            <ManualAdjustmentForm
              onSubmit={handleAdjustmentSubmit}
              pending={createAdjustment.isPending}
            />
          </div>
          <div className="space-y-6">
            <PendingFundOrdersCard
              orders={pendingFundOrders.data ?? []}
              loading={pendingFundOrders.isLoading}
              error={pendingFundOrders.isError}
              onRetry={() => void pendingFundOrders.refetch()}
            />
            {entries.isLoading ? (
              <StatusCard title={copy.states.loading} detail={copy.activity.loading} />
            ) : entries.isError ? (
              <StatusCard
                tone="danger"
                title={copy.states.error}
                detail={copy.activity.error}
                actionLabel={copy.states.retry}
                onAction={() => void entries.refetch()}
              />
            ) : (
              <ActivityFeed entries={entries.data ?? []} />
            )}
          </div>
        </div>
      </section>
    </>
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

  if (loading) {
    return <StatusCard title={copy.states.loading} detail={copy.activity.pending.loading} />;
  }
  if (error) {
    return (
      <StatusCard
        tone="danger"
        title={copy.states.error}
        detail={copy.activity.pending.error}
        actionLabel={copy.states.retry}
        onAction={onRetry}
      />
    );
  }
  if (orders.length === 0) {
    return null;
  }

  return (
    <div className="app-panel rounded-2xl p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="app-product-mark">{copy.activity.pending.kicker}</div>
          <h2 className="mt-2 text-base font-semibold">{copy.activity.pending.title}</h2>
        </div>
        <span className="app-chip app-chip-warn text-xs">{orders.length}</span>
      </div>
      <div className="mt-4 space-y-3">
        {orders.map((order) => (
          <div key={order.id} className="rounded-2xl border border-[var(--app-border)] bg-[var(--app-surface-1)] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">{order.display_name}</div>
                <div className="app-muted mt-1 text-xs">
                  {order.symbol} · {copy.activity.pending.submittedAt} {order.submitted_at}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold">{formatCurrency(order.amount)}</div>
                <div className="app-muted mt-1 text-xs">{order.status}</div>
              </div>
            </div>
            <div className="app-muted mt-3 text-xs">
              {copy.activity.pending.waitingFor} {order.target_trade_date}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlaceholderPage() {
  const copy = useCopy();
  return <StatusCard title={copy.states.empty} detail={copy.placeholder} />;
}

function ExplainabilityCard({
  drivers,
  isLoading,
}: {
  drivers: Array<{ title: string; detail: string; timestamp: string }>;
  isLoading: boolean;
}) {
  const copy = useCopy();

  if (isLoading) {
    return <StatusCard title={copy.states.loading} detail={copy.states.loading} />;
  }

  return (
    <div className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)]">
      <div className="border-b border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-4 py-3 sm:px-5">
        <div className="app-kicker text-[10px] uppercase tracking-[0.18em]">
          {copy.explainability.title}
        </div>
      </div>
      <div className="grid divide-y divide-[color-mix(in_srgb,var(--app-border)_22%,transparent)] md:grid-cols-3 md:divide-x md:divide-y-0">
        {(drivers.length > 0
          ? drivers.slice(0, 3)
          : [{ title: copy.explainability.empty, detail: "", timestamp: "" }]
        ).map((driver) => (
            <div
              key={`${driver.title}-${driver.timestamp}`}
              className="group relative px-4 py-3 transition-colors duration-200 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] sm:px-5"
            >
              <span
                className="absolute left-0 top-3 h-7 w-px bg-[var(--app-accent)] opacity-45 transition-opacity duration-200 group-hover:opacity-80"
                aria-hidden="true"
              />
              <div className="text-sm font-medium tracking-[-0.01em]">{driver.title}</div>
              {driver.detail ? (
                <div className="app-muted mt-1.5 text-xs leading-5">{driver.detail}</div>
              ) : null}
              {driver.timestamp ? (
                <div className="app-kicker mt-2 text-[10px] uppercase tracking-[0.16em]">
                  {driver.timestamp}
                </div>
              ) : null}
            </div>
          ))}
      </div>
    </div>
  );
}

function ExplainabilityWorkspace({
  title,
  stateLabelRecent,
  stateLabelPositions,
  emptyLabel,
  explainability,
  loading,
  filters,
}: {
  title: string;
  stateLabelRecent: string;
  stateLabelPositions: string;
  emptyLabel: string;
  explainability:
    | {
        equity_bridge: Array<{ key: string; label: string; value: number; detail: string }>;
        recent_drivers: Array<{ title: string; detail: string; timestamp: string }>;
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
          events: Array<{
            category: string;
            impact_source: string;
            kind: string;
            title: string;
            timestamp: string;
          }>;
        }>;
      }
    | undefined;
  loading: boolean;
  filters?: ReactNode;
}) {
  const copy = useCopy();

  if (loading) {
    return (
      <div className="app-panel rounded-2xl p-4 sm:p-5">{copy.states.loading}</div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
        <div className="app-panel rounded-2xl p-4 sm:p-5">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">{title}</div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {(explainability?.equity_bridge ?? []).map((item) => (
              <div key={item.key} className="app-panel-strong rounded-2xl px-4 py-4">
                <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
                  {item.label}
                </div>
                <div className="mt-2 text-lg font-semibold">{formatCurrency(item.value)}</div>
                <div className="app-muted mt-2 text-sm">{item.detail}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-5">
          <div className="app-panel rounded-2xl p-4 sm:p-5">
            <div className="app-kicker text-xs uppercase tracking-[0.18em]">
              {stateLabelRecent}
            </div>
            <div className="mt-4 grid gap-3">
              {(explainability?.recent_drivers?.length
                ? explainability.recent_drivers
                : [{ title: emptyLabel, detail: "", timestamp: "" }]
              ).map((item) => (
                <div
                  key={`${item.title}-${item.timestamp}`}
                  className="app-panel-strong rounded-2xl px-4 py-4"
                >
                  <div className="text-sm font-semibold">{item.title}</div>
                  {item.detail ? (
                    <div className="app-muted mt-2 text-sm">{item.detail}</div>
                  ) : null}
                  {item.timestamp ? (
                    <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
                      {item.timestamp}
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
                <div key={item.symbol} className="app-panel-strong rounded-2xl px-4 py-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold">{item.symbol}</div>
                    <div className="text-sm font-medium">
                      {formatCurrency(item.market_value)}
                    </div>
                  </div>
                  <div className="app-muted mt-2 text-sm">
                    {copy.explainability.quantity} {item.quantity} ·{" "}
                    {copy.portfolio.table.unrealized} {formatCurrency(item.unrealized_pnl)}
                  </div>
                  {item.last_activity_at ? (
                    <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
                      {item.last_activity_at}
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
            : [{ date: "", equity: 0, delta: 0, external_flow: 0, market_pnl: 0, events: [] }]
          ).map((point) => (
            <div
              key={`${point.date}-${point.equity}`}
              className="app-panel-strong rounded-2xl px-4 py-4"
            >
              {point.date ? (
                <>
                  <div className="text-sm font-semibold">{point.date}</div>
                  <div className="mt-3 grid gap-2">
                    <MetricBlock label={copy.explainability.equity} value={formatCurrency(point.equity)} />
                    <MetricBlock label={copy.explainability.netChange} value={formatCurrency(point.delta)} />
                    <MetricBlock
                      label={copy.explainability.externalFlow}
                      value={formatCurrency(point.external_flow)}
                    />
                    <MetricBlock label={copy.explainability.marketPnl} value={formatCurrency(point.market_pnl)} />
                  </div>
                  {point.events.length > 0 ? (
                    <div className="mt-3 grid gap-2">
                      {point.events.map((event) => (
                        <div
                          key={`${event.timestamp}-${event.title}`}
                          className="app-kicker text-[11px] uppercase tracking-[0.16em]"
                        >
                          {event.title} · {getEventKindLabel(copy, event.kind)} ·{" "}
                          {getEventCategoryLabel(copy, event.category)} ·{" "}
                          {getImpactSourceLabel(copy, event.impact_source)}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="app-muted text-sm">{copy.explainability.timelineEmpty}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <ReturnCalendarCard timeline={explainability?.timeline ?? []} />
    </div>
  );
}

function MetricBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-panel-strong rounded-2xl px-4 py-4">
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">{label}</div>
      <div className="mt-2 text-sm font-medium">{value}</div>
    </div>
  );
}

function PriceStructureChart({
  bars,
  emptyLabel,
}: {
  bars: Array<{ close: number }>;
  emptyLabel: string;
}) {
  if (bars.length === 0) {
    return <div className="app-muted text-sm">{emptyLabel}</div>;
  }
  const closes = bars.map((bar) => bar.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const points = closes
    .map((close, index) => {
      const x = (index / Math.max(closes.length - 1, 1)) * 640;
      const y = 220 - ((close - min) / range) * 220;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 640 220" className="h-48 w-full sm:h-56">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        points={points}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function DrawdownChart({
  points,
}: {
  points: Array<{ timestamp: string; drawdown: number }>;
}) {
  const copy = useCopy();

  if (points.length === 0) {
    return <div className="app-muted text-sm">{copy.explainability.timelineEmpty}</div>;
  }

  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 640;
      const y = (point.drawdown / Math.max(...points.map((item) => item.drawdown), 0.01)) * 220;
      return `${x},${y}`;
    })
    .join(" ");

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

function ReturnCalendarCard({
  timeline,
}: {
  timeline: Array<{
    date: string;
    equity: number;
    delta: number;
    external_flow: number;
    market_pnl: number;
  }>;
}) {
  const copy = useCopy();
  const [viewMode, setViewMode] = useState<"heatmap" | "table" | "curve">("heatmap");
  const [bucket, setBucket] = useState<"day" | "week" | "month" | "year">("day");
  const [metric, setMetric] = useState<"amount" | "percent">("amount");

  const aggregated = aggregateReturnTimeline(timeline, bucket);

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {copy.explainability.returnCalendar}
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <select
            value={viewMode}
            onChange={(event) =>
              setViewMode(event.target.value as "heatmap" | "table" | "curve")
            }
            className="app-field rounded-xl px-3 py-2 text-sm"
          >
            <option value="heatmap">{copy.explainability.heatmapView}</option>
            <option value="table">{copy.explainability.tableView}</option>
            <option value="curve">{copy.explainability.curveView}</option>
          </select>
          <select
            value={bucket}
            onChange={(event) =>
              setBucket(event.target.value as "day" | "week" | "month" | "year")
            }
            className="app-field rounded-xl px-3 py-2 text-sm"
          >
            <option value="day">{copy.explainability.day}</option>
            <option value="week">{copy.explainability.week}</option>
            <option value="month">{copy.explainability.month}</option>
            <option value="year">{copy.explainability.year}</option>
          </select>
          <select
            value={metric}
            onChange={(event) => setMetric(event.target.value as "amount" | "percent")}
            className="app-field rounded-xl px-3 py-2 text-sm"
          >
            <option value="amount">{copy.explainability.amountMetric}</option>
            <option value="percent">{copy.explainability.percentMetric}</option>
          </select>
        </div>
      </div>

      {aggregated.length === 0 ? (
        <div className="app-muted mt-4 text-sm">{copy.explainability.timelineEmpty}</div>
      ) : viewMode === "heatmap" ? (
        <div className="mt-4">
          <ReturnHeatmap rows={aggregated} bucket={bucket} metric={metric} copy={copy} />
        </div>
      ) : viewMode === "table" ? (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="app-kicker text-[11px] uppercase tracking-[0.16em]">
              <tr>
                <th className="px-3 py-2">{copy.explainability.bucketLabel}</th>
                <th className="px-3 py-2">{copy.explainability.netChange}</th>
                <th className="px-3 py-2">{copy.explainability.externalFlow}</th>
                <th className="px-3 py-2">{copy.explainability.marketPnl}</th>
              </tr>
            </thead>
            <tbody>
              {aggregated.slice().reverse().map((row) => (
                <tr key={row.label} className="border-t border-[var(--app-border)]">
                  <td className="px-3 py-3 font-medium">{row.label}</td>
                  <td className="px-3 py-3">
                    {metric === "amount"
                      ? formatCurrency(row.delta)
                      : formatPercent(row.percentChange)}
                  </td>
                  <td className="px-3 py-3">{formatCurrency(row.externalFlow)}</td>
                  <td className="px-3 py-3">{formatCurrency(row.marketPnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4">
          <ReturnCurveChart
            points={aggregated.map((row) => ({
              label: row.label,
              value: metric === "amount" ? row.delta : row.percentChange,
            }))}
          />
        </div>
      )}
    </div>
  );
}

function ReturnCurveChart({
  points,
}: {
  points: Array<{ label: string; value: number }>;
}) {
  if (points.length === 0) {
    return null;
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const line = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 640;
      const y = 220 - ((point.value - min) / range) * 220;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 640 220" className="h-48 w-full sm:h-56">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        points={line}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
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
  }>,
  bucket: "day" | "week" | "month" | "year",
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
    }
  >();

  timeline.forEach((point) => {
    const label = toReturnBucket(point.date, bucket);
    const existing = groups.get(label);
    const previousEquity = point.equity - point.delta;
    if (existing) {
      existing.delta += point.delta;
      existing.externalFlow += point.external_flow;
      existing.marketPnl += point.market_pnl;
      existing.endEquity = point.equity;
      return;
    }
    groups.set(label, {
      label,
      delta: point.delta,
      externalFlow: point.external_flow,
      marketPnl: point.market_pnl,
      startEquity: previousEquity,
      endEquity: point.equity,
    });
  });

  return Array.from(groups.values()).map((row) => ({
    ...row,
    percentChange:
      row.startEquity === 0 ? 0 : row.delta / Math.abs(row.startEquity),
  }));
}

function toReturnBucket(dateText: string, bucket: "day" | "week" | "month" | "year") {
  if (bucket === "day") {
    return dateText;
  }
  const date = new Date(`${dateText}T00:00:00`);
  if (bucket === "month") {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }
  if (bucket === "year") {
    return `${date.getFullYear()}`;
  }
  const start = new Date(date);
  const day = start.getDay() || 7;
  start.setDate(start.getDate() - day + 1);
  return `${start.getFullYear()}-W${String(weekOfYear(start)).padStart(2, "0")}`;
}

function weekOfYear(date: Date) {
  const start = new Date(date.getFullYear(), 0, 1);
  const diff = date.getTime() - start.getTime();
  return Math.floor(diff / 86_400_000 / 7) + 1;
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatCurrency(value: number) {
  const locale =
    typeof document !== "undefined" && document.documentElement.lang.startsWith("zh")
      ? "zh-CN"
      : "en-US";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2,
  }).format(value);
}

function ReturnHeatmap({
  rows,
  bucket,
  metric,
  copy,
}: {
  rows: Array<{
    label: string;
    delta: number;
    externalFlow: number;
    marketPnl: number;
    percentChange: number;
  }>;
  bucket: "day" | "week" | "month" | "year";
  metric: "amount" | "percent";
  copy: AppCopy;
}) {
  const maxMagnitude = Math.max(
    ...rows.map((row) => Math.abs(metric === "amount" ? row.delta : row.percentChange)),
    0.0001,
  );
  const columns =
    bucket === "day" ? "grid-cols-7" : bucket === "week" ? "grid-cols-4" : "grid-cols-3";

  return (
    <div className={`grid gap-2 ${columns}`}>
      {rows.map((row) => {
        const value = metric === "amount" ? row.delta : row.percentChange;
        const tone = getHeatmapTone(value, maxMagnitude);
        return (
          <div
            key={row.label}
            className={`rounded-2xl border px-3 py-3 text-left ${tone}`}
            title={`${row.label} · ${
              metric === "amount" ? formatCurrency(row.delta) : formatPercent(row.percentChange)
            }`}
          >
            <div className="text-xs font-semibold uppercase tracking-[0.12em]">
              {row.label}
            </div>
            <div className="mt-3 text-sm font-semibold">
              {metric === "amount" ? formatCurrency(row.delta) : formatPercent(row.percentChange)}
            </div>
            <div className="mt-2 text-xs opacity-80">
              {copy.explainability.marketPnl}: {formatCurrency(row.marketPnl)}
            </div>
            <div className="mt-1 text-xs opacity-80">
              {copy.explainability.externalFlow}: {formatCurrency(row.externalFlow)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function getHeatmapTone(value: number, maxMagnitude: number) {
  const intensity = Math.min(Math.abs(value) / maxMagnitude, 1);

  if (value > 0) {
    if (intensity > 0.66) {
      return "app-heat-positive-strong";
    }
    if (intensity > 0.33) {
      return "app-heat-positive-medium";
    }
    return "app-heat-positive-soft";
  }

  if (value < 0) {
    if (intensity > 0.66) {
      return "app-heat-negative-strong";
    }
    if (intensity > 0.33) {
      return "app-heat-negative-medium";
    }
    return "app-heat-negative-soft";
  }

  return "border-[var(--app-border)] bg-[var(--app-panel-strong)] text-[var(--app-foreground)]";
}

function getAssetClassLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "stock":
      return copy.common.assetClassStock;
    case "etf":
      return copy.common.assetClassEtf;
    case "fund":
      return copy.common.assetClassFund;
    case "gold":
      return copy.common.assetClassGold;
    case "bond":
      return copy.common.assetClassBond;
    default:
      return value;
  }
}

function getNoteTypeLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "note":
      return copy.market.note;
    case "thesis":
      return copy.market.thesis;
    case "catalyst":
      return copy.market.catalyst;
    default:
      return value;
  }
}

function getPriorityLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "high":
      return copy.market.highPriority;
    case "normal":
      return copy.market.normalPriority;
    case "low":
      return copy.market.lowPriority;
    default:
      return value;
  }
}

function getEventKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "cash_deposit":
      return copy.explainability.deposits;
    case "cash_withdrawal":
      return copy.explainability.withdrawals;
    case "dividend":
      return copy.explainability.dividends;
    case "trade_buy":
      return copy.explainability.buys;
    case "trade_sell":
      return copy.explainability.sells;
    case "manual_adjustment":
      return copy.explainability.adjustments;
    default:
      return value;
  }
}

function getEventCategoryLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "capital":
      return copy.explainability.categoryCapital;
    case "income":
      return copy.explainability.categoryIncome;
    case "override":
      return copy.explainability.categoryOverride;
    case "trade":
      return copy.explainability.categoryTrade;
    default:
      return value;
  }
}

function getImpactSourceLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "external":
      return copy.explainability.sourceExternal;
    case "cash":
      return copy.explainability.sourceCash;
    case "manual":
      return copy.explainability.sourceManual;
    case "positioning":
      return copy.explainability.sourcePositioning;
    default:
      return value;
  }
}

function getRiskMetricLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "current_drawdown":
      return copy.riskPage.currentDrawdown;
    case "max_drawdown":
      return copy.riskPage.maxDrawdown;
    case "gross_exposure":
      return copy.riskPage.grossExposure;
    case "cash_ratio":
      return copy.riskPage.cashRatio;
    case "largest_weight":
      return copy.riskPage.largestPosition;
    case "top3_weight":
      return copy.riskPage.top3Concentration;
    default:
      return value;
  }
}

function getRiskMetricDetail(copy: AppCopy, value: string) {
  switch (value) {
    case "current_drawdown":
      return copy.riskPage.currentDrawdownDetail;
    case "max_drawdown":
      return copy.riskPage.maxDrawdownDetail;
    case "gross_exposure":
      return copy.riskPage.grossExposureDetail;
    case "cash_ratio":
      return copy.riskPage.cashRatioDetail;
    case "largest_weight":
      return copy.riskPage.largestPositionDetail;
    case "top3_weight":
      return copy.riskPage.top3ConcentrationDetail;
    default:
      return value;
  }
}

function getRiskBucketLabel(copy: AppCopy, value: string) {
  switch (value) {
    case "heavy":
      return copy.riskPage.bucketHeavy;
    case "core":
      return copy.riskPage.bucketCore;
    case "starter":
      return copy.riskPage.bucketStarter;
    case "small":
      return copy.riskPage.bucketSmall;
    case "cash":
      return copy.riskPage.bucketCash;
    default:
      return value;
  }
}

function StatusCard({
  title,
  detail,
  tone = "default",
  actionLabel,
  onAction,
}: {
  title: string;
  detail: string;
  tone?: "default" | "danger";
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div
      className={
        tone === "danger"
          ? "app-panel-danger rounded-xl p-4 sm:p-5"
          : "rounded-xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-4 sm:p-5"
      }
    >
      <div className="text-sm font-semibold tracking-[-0.01em]">{title}</div>
      <div className="mt-2 text-sm opacity-80">{detail}</div>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="app-button-secondary mt-4 rounded-xl px-4 py-2 text-sm"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function PageHeader({
  kicker,
  title,
  subtitle,
}: {
  kicker: string;
  title: string;
  subtitle: string;
}) {
  return (
    <header className="app-page-header pb-1">
      <div className="app-product-mark">{kicker}</div>
      <h1 className="app-page-title">{title}</h1>
      <p className="app-page-subtitle">{subtitle}</p>
    </header>
  );
}

function groupAllocation(items: AllocationItem[]): AllocationGroup[] {
  const grouped = new Map<string, AllocationGroup>();
  const total = items.reduce((sum, item) => sum + item.value, 0) || 1;

  items.forEach((item) => {
    const existing = grouped.get(item.asset_class);
    if (existing) {
      existing.value += item.value;
      existing.items.push(item);
      existing.weight = existing.value / total;
      return;
    }
    grouped.set(item.asset_class, {
      asset_class: item.asset_class,
      name: item.asset_class,
      value: item.value,
      weight: item.value / total,
      items: [item],
    });
  });

  return Array.from(grouped.values()).sort((left, right) => right.value - left.value);
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error && error.message.trim().length > 0) {
    return error.message;
  }
  return "Request failed. Check your payload and server logs.";
}
