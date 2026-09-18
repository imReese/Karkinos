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
import { OverviewValuationCoverage } from './overview-valuation-coverage';
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
    <div className="min-w-0" data-testid="overview-financial-canvas">
      <OverviewDataStatus state={state} />
      <OverviewSummary summary={state.summary} />
      <DashboardTodayQueue overview={state.overview} />
      <OverviewValuationCoverage snapshot={state.snapshot} />

      <section
        className="min-w-0 border-b border-[var(--app-divider)] py-4"
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
                className="app-type-compact mb-3 text-[var(--app-warning-text)]"
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
        className="border-b border-[var(--app-divider)]"
      />

      <div className="grid min-w-0 lg:grid-cols-2 lg:divide-x lg:divide-[var(--app-divider)]">
        <div className="min-w-0 lg:pr-6">
          <OverviewStrategyRecommendation
            planQuery={controller.tradingPlan}
            decisionQuery={controller.todayDecision}
          />
        </div>
        <div className="min-w-0 lg:pl-6">
          <OverviewMarketStatus state={state} />
        </div>
      </div>

      <OverviewDataDetails
        state={state}
        refreshFailed={controller.account.isError}
      />
    </div>
  );
}
