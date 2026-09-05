import { createLazyRoute } from '@tanstack/react-router';
import { PublicationStatus } from '../../../shared/portfolio-evidence/publication-status';

import { WorkspaceHeader } from '../../../shared/ui/workbench';
import { OverviewLoadingWorkspace } from '../components/overview-loading-workspace';
import { OverviewResolvedWorkspace } from '../components/overview-resolved-workspace';
import { OverviewStatusCard } from '../components/overview-status-card';
import { useOverviewPageController } from '../model/use-overview-page-controller';

export function OverviewPage() {
  const controller = useOverviewPageController();
  const { copy, queries } = controller;
  return (
    <section className="space-y-5">
      <WorkspaceHeader
        eyebrow={copy.overview.kicker}
        title={copy.overview.title}
        description={copy.overview.subtitle}
      />
      <PublicationStatus
        snapshotId={queries.snapshot.data?.valuation_snapshot_id}
        asOf={queries.snapshot.data?.valuation_as_of}
      />
      {controller.isInitialOverviewLoad ? (
        <OverviewLoadingWorkspace
          copy={copy}
          todayPnlLabel={controller.todayPnlLabel}
        />
      ) : controller.isInitialOverviewError ? (
        <OverviewStatusCard
          tone="danger"
          title={copy.states.error}
          detail={copy.overview.error}
          actionLabel={copy.states.retry}
          onAction={() => {
            void queries.overview.refetch();
            void queries.snapshot.refetch();
          }}
        />
      ) : controller.hasAnyPrimaryProjection ? (
        <OverviewResolvedWorkspace
          queries={queries}
          positions={controller.positions}
          assetClassBySymbol={controller.assetClassBySymbol}
          todayPnlLabel={controller.todayPnlLabel}
          todayPnlContext={controller.todayPnlContext}
          analysisView={controller.analysisView}
          setAnalysisView={controller.setAnalysisView}
          equityCurveRange={controller.equityCurveRange}
          setEquityCurveRange={controller.setEquityCurveRange}
        />
      ) : (
        <OverviewStatusCard
          title={copy.states.empty}
          detail={copy.overview.empty}
        />
      )}
    </section>
  );
}

export const Route = createLazyRoute('/overview')({
  component: OverviewPage,
});
