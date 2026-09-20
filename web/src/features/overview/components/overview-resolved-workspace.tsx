import { useCopy } from '../../../shared/i18n/context';
import {
  OverviewEquityCurve,
  EquityCurveSkeleton,
  type AccountStateResponse,
} from '../overview-feature-boundary';
import type { useOverviewPageController } from '../model/use-overview-page-controller';
import { getEquityCurveErrorDetail } from '../model/overview-page-model';
import { OverviewAllocationRiskSection } from './overview-allocation-risk-section';
import { OverviewHoldingsSection } from './overview-holdings-section';
import { OverviewStatusCard } from './overview-status-card';
import { OverviewStrategyRecommendation } from './overview-strategy-recommendation';
import { OverviewSummary } from './overview-summary';
import { OverviewTodayDigest } from './overview-today-digest';
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
  const showAttention =
    state.overview.attention_status !== 'available' ||
    state.overview.user_attention.length > 0;

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
        className={
          'min-w-0 border-b border-[var(--app-divider)] py-4 ' +
          (showAttention
            ? 'grid gap-6 lg:grid-cols-2 lg:gap-0 lg:divide-x lg:divide-[var(--app-divider)]'
            : '')
        }
        data-testid="overview-research-actions"
      >
        <OverviewStrategyRecommendation
          planQuery={controller.tradingPlan}
          positions={state.snapshot.positions}
          currentWeightBySymbol={weightBySymbol}
          className={
            showAttention ? 'border-b-0 py-0 lg:pr-6' : 'border-b-0 py-0'
          }
        />
        {showAttention ? (
          <DashboardTodayQueue
            overview={state.overview}
            className="border-b-0 py-0 lg:pl-6"
          />
        ) : null}
      </section>
    </div>
  );
}
