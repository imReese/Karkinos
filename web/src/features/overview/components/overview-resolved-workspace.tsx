import { useCopy } from '../../../shared/i18n/context';
import { SectionHeader } from '../../../shared/ui/workbench';
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
} from './overview-data-status';
import { OverviewAllocationRiskSection } from './overview-allocation-risk-section';
import { OverviewDataTrustStrip } from './overview-data-trust-strip';
import { OverviewHoldingsSection } from './overview-holdings-section';
import { OverviewStatusCard } from './overview-status-card';
import { OverviewStrategyRecommendation } from './overview-strategy-recommendation';
import { OverviewSummary } from './overview-summary';
import { OverviewTodayDigest } from './overview-today-digest';
import { DashboardTodayQueue } from './overview-today-queue';
import { OverviewValuationCoverage } from './overview-valuation-coverage';

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

  const performance =
    equityCurve.isLoading && !equityCurve.data ? (
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
      </>
    );

  return (
    <div className="min-w-0" data-testid="overview-financial-canvas">
      <OverviewDataStatus state={state} />
      <OverviewSummary summary={state.summary} />

      <section
        className="min-w-0 border-b border-[var(--app-divider)] py-4"
        data-testid="overview-performance-card"
      >
        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,0.72fr)]">
          <div className="min-w-0">{performance}</div>
          <OverviewTodayDigest state={state} />
        </div>
      </section>

      <OverviewHoldingsSection
        positions={state.snapshot.positions}
        assetClassBySymbol={assetClassBySymbol}
        weightBySymbol={weightBySymbol}
        className="border-b border-[var(--app-divider)]"
      />

      <OverviewAllocationRiskSection state={state} />
      <section
        className="grid min-w-0 gap-6 border-b border-[var(--app-divider)] py-4 lg:grid-cols-2 lg:gap-0 lg:divide-x lg:divide-[var(--app-divider)]"
        data-testid="overview-research-actions"
      >
        <OverviewStrategyRecommendation
          planQuery={controller.tradingPlan}
          decisionQuery={controller.todayDecision}
          className="border-b-0 py-0 lg:pr-6"
        />
        <DashboardTodayQueue
          overview={state.overview}
          className="border-b-0 py-0 lg:pl-6"
        />
      </section>

      <section className="min-w-0 py-4" data-testid="overview-data-trust">
        <SectionHeader
          title={copy.overview.dashboard.dataTrust}
          className="mb-2"
        />
        <OverviewDataTrustStrip state={state} />
        <OverviewValuationCoverage snapshot={state.snapshot} />
        <OverviewDataDetails
          state={state}
          refreshFailed={controller.account.isError}
        />
      </section>
    </div>
  );
}
