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
} from './overview-data-status';
import { OverviewHoldingsSection } from './overview-holdings-section';
import { OverviewStatusCard } from './overview-status-card';
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
  return (
    <div className="min-w-0">
      <OverviewDataStatus state={state} />
      <div
        className="grid min-w-0 gap-x-8 xl:grid-cols-[minmax(0,1fr)_272px]"
        data-testid="overview-financial-canvas"
      >
        <div className="min-w-0 xl:col-start-1 xl:row-start-1">
          <OverviewSummary summary={state.summary} />
          <section
            className="min-w-0 border-t border-[var(--app-divider)] pt-4 pb-5"
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
              </>
            )}
          </section>
        </div>
        <aside className="min-w-0 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:pt-5">
          <DashboardTodayQueue overview={state.overview} />
          <OverviewDataDetails
            state={state}
            refreshFailed={controller.account.isError}
          />
        </aside>
        <OverviewHoldingsSection
          positions={state.snapshot.positions}
          assetClassBySymbol={Object.fromEntries(
            state.snapshot.allocation.map((item) => [
              item.symbol,
              item.asset_class,
            ]),
          )}
          weightBySymbol={Object.fromEntries(
            state.snapshot.allocation.map((item) => [item.symbol, item.weight]),
          )}
          className="xl:col-start-1 xl:row-start-2"
        />
      </div>
    </div>
  );
}
