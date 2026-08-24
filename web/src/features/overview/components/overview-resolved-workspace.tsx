import type { Dispatch, SetStateAction } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { EvidenceState } from '../../../shared/ui/workbench';
import {
  OverviewCards,
  OverviewSnapshotFallbackCards,
} from '../overview-feature-boundary';
import type {
  EquityCurveRange,
  PortfolioSnapshot,
} from '../overview-feature-boundary';
import type { OverviewAnalysisView } from '../model/overview-page-model';
import type { OverviewWorkspaceQueries } from '../model/use-overview-page-controller';
import { OverviewAnalysisSection } from './overview-analysis-section';
import { OverviewHoldingsSection } from './overview-holdings-section';
import { OverviewReviewStrip } from './overview-review-strip';
import { DashboardTodayQueue } from './overview-today-queue';

export function OverviewResolvedWorkspace({
  queries,
  positions,
  assetClassBySymbol,
  todayPnlLabel,
  todayPnlContext,
  analysisView,
  setAnalysisView,
  equityCurveRange,
  setEquityCurveRange,
}: {
  queries: OverviewWorkspaceQueries;
  positions: PortfolioSnapshot['positions'];
  assetClassBySymbol: Record<string, string>;
  todayPnlLabel: string;
  todayPnlContext: string | null;
  analysisView: OverviewAnalysisView;
  setAnalysisView: Dispatch<SetStateAction<OverviewAnalysisView>>;
  equityCurveRange: EquityCurveRange;
  setEquityCurveRange: Dispatch<SetStateAction<EquityCurveRange>>;
}) {
  const copy = useCopy();
  const {
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
  } = queries;
  return (
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
          <OverviewAnalysisSection
            analysisView={analysisView}
            setAnalysisView={setAnalysisView}
            equityCurveRange={equityCurveRange}
            setEquityCurveRange={setEquityCurveRange}
            equityCurvePoints={equityCurve.data}
            equityCurveLoading={equityCurve.isLoading}
            equityCurveError={equityCurve.isError}
            equityCurveErrorValue={equityCurve.error}
            onRetryEquityCurve={() => void equityCurve.refetch()}
            snapshot={snapshot.data}
            strategyContribution={strategyContribution.data}
            strategyContributionLoading={strategyContribution.isLoading}
            strategyContributionError={strategyContribution.isError}
            onRetryStrategyContribution={() =>
              void strategyContribution.refetch()
            }
            explainabilityTimeline={explainability.data?.timeline ?? []}
            positions={positions}
            marketCalendar={marketCalendar.data}
          />
          <OverviewReviewStrip
            marketHealth={marketHealth.data}
            marketHealthLoading={marketHealth.isLoading}
            marketHealthError={marketHealth.isError}
            orders={pendingOrders.data ?? []}
            ordersLoading={pendingOrders.isLoading}
            ordersError={pendingOrders.isError}
            entries={ledgerEntries.data ?? []}
            entriesLoading={ledgerEntries.isLoading}
            entriesError={ledgerEntries.isError}
            copy={copy}
          />
        </>
      ) : null}
    </div>
  );
}
