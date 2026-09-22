import { useCopy } from '../../../shared/i18n/context';
import {
  OverviewEquityCurve,
  EquityCurveSkeleton,
  ReturnCalendarCard,
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
  const {
    equityCurve,
    equityCurveRange,
    setEquityCurveRange,
    analysisView,
    setAnalysisView,
    explainability,
  } = controller;
  const assetClassBySymbol = Object.fromEntries(
    state.snapshot.allocation.map((item) => [item.symbol, item.asset_class]),
  );
  const weightBySymbol = Object.fromEntries(
    state.snapshot.allocation.map((item) => [item.symbol, item.weight]),
  );
  const showAttention =
    state.overview.attention_status !== 'available' ||
    state.overview.user_attention.length > 0;
  const hasPerformanceDrivers = Boolean(
    state.summary.today_contributors?.length,
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

  const calendar =
    explainability.isLoading && !explainability.data ? (
      <div className="py-8 text-center text-sm text-[var(--app-text-secondary)]">
        {copy.states.loading}
      </div>
    ) : explainability.isError && !explainability.data ? (
      <OverviewStatusCard
        tone="danger"
        title={copy.states.error}
        detail={copy.explainability.empty}
        actionLabel={copy.states.retry}
        onAction={() => void explainability.refetch()}
      />
    ) : (
      <ReturnCalendarCard
        timeline={explainability.data?.timeline ?? []}
        positions={state.snapshot.positions}
        compact
      />
    );

  return (
    <div className="min-w-0 space-y-6" data-testid="overview-financial-canvas">
      <OverviewSummary summary={state.summary} />

      <section
        className="min-w-0 border-b border-[var(--app-divider)] pb-6"
        data-testid="overview-performance-card"
      >
        <div
          role="tablist"
          aria-label={copy.overview.dashboard.equityPanel}
          className="mb-4 flex max-w-full overflow-x-auto border-b border-[var(--app-divider)]"
          data-testid="overview-analysis-view-tabs"
        >
          <button
            id="overview-analysis-tab-curve"
            type="button"
            role="tab"
            aria-selected={analysisView === 'curve'}
            aria-controls="overview-analysis-panel-curve"
            onClick={() => setAnalysisView('curve')}
            className={`flex h-9 shrink-0 items-center border-b-2 px-3 text-xs font-semibold transition-colors ${
              analysisView === 'curve'
                ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
            }`}
          >
            {copy.overview.dashboard.equityCurve}
          </button>
          <button
            id="overview-analysis-tab-calendar"
            type="button"
            role="tab"
            aria-selected={analysisView === 'calendar'}
            aria-controls="overview-analysis-panel-calendar"
            onClick={() => setAnalysisView('calendar')}
            className={`flex h-9 shrink-0 items-center border-b-2 px-3 text-xs font-semibold transition-colors ${
              analysisView === 'calendar'
                ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
            }`}
          >
            {copy.explainability.returnCalendar}
          </button>
        </div>

        <div className="min-w-0">
          {analysisView === 'curve' ? (
            <div
              id="overview-analysis-panel-curve"
              role="tabpanel"
              aria-labelledby="overview-analysis-tab-curve"
            >
              {performance}
            </div>
          ) : (
            <div
              id="overview-analysis-panel-calendar"
              role="tabpanel"
              aria-labelledby="overview-analysis-tab-calendar"
            >
              {calendar}
            </div>
          )}
        </div>
        <div className="mt-3 min-w-0">
          <OverviewStrategyRecommendation
            planQuery={controller.tradingPlan}
            positions={state.snapshot.positions}
            currentWeightBySymbol={weightBySymbol}
          />
        </div>
      </section>

      <OverviewHoldingsSection
        positions={state.snapshot.positions}
        assetClassBySymbol={assetClassBySymbol}
        weightBySymbol={weightBySymbol}
        className="border-b border-[var(--app-divider)] pb-6"
      />

      {hasPerformanceDrivers ? (
        <section
          className="min-w-0 border-b border-[var(--app-divider)] py-4"
          data-testid="overview-session-impact"
        >
          <OverviewTodayDigest state={state} />
        </section>
      ) : null}

      <OverviewAllocationRiskSection state={state} />

      {showAttention ? (
        <section
          className="min-w-0 border-b border-[var(--app-divider)] py-4"
          data-testid="overview-research-actions"
        >
          <DashboardTodayQueue
            overview={state.overview}
            className="border-b-0 py-0"
          />
        </section>
      ) : null}
    </div>
  );
}
