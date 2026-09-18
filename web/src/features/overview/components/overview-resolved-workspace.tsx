import { useCopy } from '../../../shared/i18n/context';
import {
  OverviewEquityCurve,
  EquityCurveSkeleton,
  type AccountStateResponse,
} from '../overview-feature-boundary';
import type { useOverviewPageController } from '../model/use-overview-page-controller';
import { getEquityCurveErrorDetail } from '../model/overview-page-model';
import {
  OverviewDataDetails,
  OverviewDataStatus,
  OverviewMarketStatus,
} from './overview-data-status';
import { OverviewHoldingsSection } from './overview-holdings-section';
import { OverviewPerformanceDrivers } from './overview-performance-drivers';
import { OverviewStatusCard } from './overview-status-card';
import { OverviewStrategyRecommendation } from './overview-strategy-recommendation';
import { OverviewSummary } from './overview-summary';
import { DashboardTodayQueue } from './overview-today-queue';

export function OverviewResolvedWorkspace({
  controller,
  state,
}: {
  controller: ReturnType<typeof useOverviewPageController>;
  state: AccountStateResponse;
}) {
  const copy = useCopy();
  const { equityCurve, equityCurveRange, setEquityCurveRange } = controller;
  const assetClassBySymbol = Object.fromEntries(
    state.snapshot.allocation.map((item) => [item.symbol, item.asset_class]),
  );
  const weightBySymbol = Object.fromEntries(
    state.snapshot.allocation.map((item) => [item.symbol, item.weight]),
  );

  return (
    <div className="min-w-0">
      <OverviewDataStatus state={state} />
      <OverviewSummary summary={state.summary} />
      <div
        className="grid min-w-0 items-start xl:grid-cols-[minmax(0,1fr)_18rem]"
        data-testid="overview-financial-canvas"
      >
        <div className="min-w-0 xl:border-r xl:border-[var(--app-divider)]">
          <section
            className="min-w-0 py-3.5 xl:pr-6"
            data-testid="overview-performance-card"
          >
            {equityCurve.isLoading && !equityCurve.data ? (
              <EquityCurveSkeleton />
            ) : equityCurve.isError && !equityCurve.data ? (
              <OverviewStatusCard
                tone="danger"
                title={copy.states.error}
                detail={getEquityCurveErrorDetail(equityCurve.error, copy)}
                actionLabel={copy.states.retry}
                onAction={() => void equityCurve.refetch()}
              />
            ) : (
              <>
                {equityCurve.isError ? (
                  <p
                    role="status"
                    data-testid="equity-curve-refresh-warning"
                    className="mb-3 text-xs text-[var(--app-warning-text)]"
                  >
                    {copy.overview.curveRefreshError}
                  </p>
                ) : null}
                <OverviewEquityCurve
                  points={equityCurve.data ?? []}
                  range={equityCurveRange}
                  onRangeChange={setEquityCurveRange}
                />
                <OverviewPerformanceDrivers state={state} />
              </>
            )}
          </section>
          <OverviewHoldingsSection
            positions={state.snapshot.positions}
            assetClassBySymbol={assetClassBySymbol}
            weightBySymbol={weightBySymbol}
            className="border-t border-[var(--app-divider)] xl:pr-6"
          />
        </div>
        <aside className="min-w-0 xl:pl-5">
          <OverviewStrategyRecommendation query={controller.tradingPlan} />
          <OverviewMarketStatus state={state} />
          <DashboardTodayQueue overview={state.overview} />
          <OverviewDataDetails
            state={state}
            refreshFailed={controller.account.isError}
          />
        </aside>
      </div>
    </div>
  );
}
