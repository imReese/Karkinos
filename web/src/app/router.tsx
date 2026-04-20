import { useState } from "react";
import {
  createRoute,
  createRootRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";

import { useCopy } from "./copy";
import { ToastStack, type ToastItem } from "./components/toast-stack";
import { AppShell } from "./layout/app-shell";
import {
  useAccountOverviewQuery,
  useEquityCurveQuery,
} from "../features/account/api";
import { EquityCurveCard } from "../features/account/components/equity-curve-card";
import { OverviewCards } from "../features/account/components/overview-cards";
import { PerformanceBreakdownCard } from "../features/account/components/performance-breakdown-card";
import {
  useCreateAdjustmentMutation,
  useCreateCashFlowMutation,
  useCreateDividendMutation,
  useCreateTradeMutation,
  useLedgerEntriesQuery,
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
  type AllocationGroup,
  type AllocationItem,
  usePortfolioSnapshotQuery,
  usePositionsQuery,
} from "../features/portfolio/api";
import { AllocationCard } from "../features/portfolio/components/allocation-card";
import { AllocationGroupsCard } from "../features/portfolio/components/allocation-groups-card";
import { PositionsTable } from "../features/portfolio/components/positions-table";
import { WorkspaceToolbar } from "../features/portfolio/components/workspace-toolbar";

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
  component: PortfolioPage,
});

const activityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/activity",
  component: ActivityPage,
});

const marketRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/market",
  component: PlaceholderPage,
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
  marketRoute,
  settingsRoute,
]);

export const router = createRouter({ routeTree });

function OverviewPage() {
  const copy = useCopy();
  const [mode, setMode] = useState<"account" | "strategy">("account");
  const overview = useAccountOverviewQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const equityCurve = useEquityCurveQuery();

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <div className="app-kicker text-xs font-medium uppercase tracking-[0.24em]">
          {copy.overview.kicker}
        </div>
        <h1 className="text-3xl font-semibold">{copy.overview.title}</h1>
        <p className="app-muted max-w-2xl text-sm leading-6">
          {copy.overview.subtitle}
        </p>
      </header>

      <SegmentedMode
        mode={mode}
        onModeChange={setMode}
        accountLabel={copy.mode.account}
        strategyLabel={copy.mode.strategy}
        helper={copy.overview.modeHelper}
      />

      {overview.isLoading || snapshot.isLoading ? (
        <StatusCard title={copy.states.loading} detail={copy.overview.loading} />
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
        <div className="space-y-6">
          <OverviewCards overview={overview.data} />
          <PerformanceBreakdownCard
            overview={overview.data}
            snapshot={snapshot.data}
            mode={mode}
          />
          {equityCurve.isLoading ? (
            <StatusCard title={copy.states.loading} detail={copy.overview.curveLoading} />
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
      ) : (
        <StatusCard title={copy.states.empty} detail={copy.overview.empty} />
      )}
    </section>
  );
}

function PortfolioPage() {
  const copy = useCopy();
  const [mode, setMode] = useState<"account" | "strategy">("account");
  const [search, setSearch] = useState("");
  const [assetClassFilter, setAssetClassFilter] = useState("all");
  const [pnlFilter, setPnlFilter] = useState<"all" | "winners" | "losers">("all");
  const overview = useAccountOverviewQuery();
  const positions = usePositionsQuery();
  const snapshot = usePortfolioSnapshotQuery();

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

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <div className="app-kicker text-xs font-medium uppercase tracking-[0.24em]">
          {copy.portfolio.kicker}
        </div>
        <h1 className="text-3xl font-semibold">{copy.portfolio.title}</h1>
        <p className="app-muted max-w-2xl text-sm leading-6">
          {copy.portfolio.subtitle}
        </p>
      </header>

      <WorkspaceToolbar
        mode={mode}
        onModeChange={setMode}
        search={search}
        onSearchChange={setSearch}
        assetClassFilter={assetClassFilter}
        onAssetClassFilterChange={setAssetClassFilter}
        pnlFilter={pnlFilter}
        onPnlFilterChange={setPnlFilter}
        assetClasses={assetClasses}
      />

      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <div className="space-y-6">
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

        <div className="space-y-6">
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
              />
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

function ActivityPage() {
  const copy = useCopy();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const entries = useLedgerEntriesQuery();
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
    try {
      await createTrade.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
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
      </section>
    </>
  );
}

function PlaceholderPage() {
  const copy = useCopy();
  return <StatusCard title={copy.states.empty} detail={copy.placeholder} />;
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
    <div className={tone === "danger" ? "app-panel-danger rounded-2xl p-5" : "app-panel rounded-2xl p-5"}>
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-2 text-sm opacity-90">{detail}</div>
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

function SegmentedMode({
  mode,
  onModeChange,
  accountLabel,
  strategyLabel,
  helper,
}: {
  mode: "account" | "strategy";
  onModeChange: (mode: "account" | "strategy") => void;
  accountLabel: string;
  strategyLabel: string;
  helper: string;
}) {
  return (
    <div className="app-panel rounded-2xl p-5">
      <div className="flex flex-wrap items-center gap-2">
        {[
          { value: "account", label: accountLabel },
          { value: "strategy", label: strategyLabel },
        ].map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => onModeChange(item.value as "account" | "strategy")}
            className={`rounded-xl px-4 py-2 text-sm ${
              mode === item.value ? "app-button-primary" : "app-button-secondary"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="app-muted mt-3 text-sm">{helper}</div>
    </div>
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
