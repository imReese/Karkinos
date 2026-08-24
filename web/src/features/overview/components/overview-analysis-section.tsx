import type { ComponentProps, Dispatch, SetStateAction } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  EquityCurveCard,
  EquityCurveSkeleton,
  PortfolioExposureSummary,
  ReturnCalendarCard,
  StrategyContributionGateCard,
  type AccountStrategyContributionReport,
  type EquityCurveRange,
  type MarketCalendarSnapshot,
  type PortfolioSnapshot,
} from '../overview-feature-boundary';
import {
  getEquityCurveErrorDetail,
  type OverviewAnalysisView,
} from '../model/overview-page-model';
import { OverviewStatusCard } from './overview-status-card';

export function OverviewAnalysisSection({
  analysisView,
  setAnalysisView,
  equityCurveRange,
  setEquityCurveRange,
  equityCurvePoints,
  equityCurveLoading,
  equityCurveError,
  equityCurveErrorValue,
  onRetryEquityCurve,
  snapshot,
  strategyContribution,
  strategyContributionLoading,
  strategyContributionError,
  onRetryStrategyContribution,
  explainabilityTimeline,
  positions,
  marketCalendar,
}: {
  analysisView: OverviewAnalysisView;
  setAnalysisView: Dispatch<SetStateAction<OverviewAnalysisView>>;
  equityCurveRange: EquityCurveRange;
  setEquityCurveRange: Dispatch<SetStateAction<EquityCurveRange>>;
  equityCurvePoints?: ComponentProps<typeof EquityCurveCard>['points'];
  equityCurveLoading: boolean;
  equityCurveError: boolean;
  equityCurveErrorValue: unknown;
  onRetryEquityCurve: () => void;
  snapshot: PortfolioSnapshot;
  strategyContribution?: AccountStrategyContributionReport;
  strategyContributionLoading: boolean;
  strategyContributionError: boolean;
  onRetryStrategyContribution: () => void;
  explainabilityTimeline: ComponentProps<typeof ReturnCalendarCard>['timeline'];
  positions: PortfolioSnapshot['positions'];
  marketCalendar?: MarketCalendarSnapshot;
}) {
  const copy = useCopy();
  const tabs = [
    { id: 'performance' as const, label: copy.overview.dashboard.equityPanel },
    { id: 'allocation' as const, label: copy.portfolio.allocation.title },
    {
      id: 'attribution' as const,
      label: copy.backtest.page.accountStrategyContributionPublicTitle,
    },
    { id: 'calendar' as const, label: copy.explainability.returnCalendar },
  ];
  return (
    <section
      data-testid="overview-performance-card"
      className="min-w-0 overflow-hidden border-y border-[var(--app-divider)] bg-transparent"
    >
      <div
        role="tablist"
        aria-label={copy.overview.dashboard.equityPanel}
        className="flex max-w-full overflow-x-auto border-b border-[var(--app-divider)]"
      >
        {tabs.map((tab) => (
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
          equityCurveLoading && !equityCurvePoints ? (
            <EquityCurveSkeleton />
          ) : equityCurveError && !equityCurvePoints ? (
            <OverviewStatusCard
              tone="danger"
              title={copy.states.error}
              detail={getEquityCurveErrorDetail(equityCurveErrorValue, copy)}
              actionLabel={copy.states.retry}
              onAction={onRetryEquityCurve}
            />
          ) : (
            <div className="space-y-3">
              {equityCurveError ? (
                <div
                  role="status"
                  data-testid="equity-curve-refresh-warning"
                  className="app-panel-danger rounded-[var(--app-radius-surface)] px-3 py-2 text-xs leading-5"
                >
                  {copy.overview.curveRefreshError}
                </div>
              ) : null}
              <EquityCurveCard
                points={equityCurvePoints ?? []}
                range={equityCurveRange}
                onRangeChange={setEquityCurveRange}
              />
            </div>
          )
        ) : analysisView === 'allocation' ? (
          <PortfolioExposureSummary snapshot={snapshot} />
        ) : analysisView === 'attribution' ? (
          <StrategyContributionGateCard
            report={strategyContribution}
            isLoading={strategyContributionLoading}
            isError={strategyContributionError}
            onRetry={onRetryStrategyContribution}
            instruments={positions}
            variant="compact"
          />
        ) : (
          <ReturnCalendarCard
            timeline={explainabilityTimeline}
            positions={positions}
            marketCalendar={marketCalendar}
            compact
          />
        )}
      </div>
    </section>
  );
}
