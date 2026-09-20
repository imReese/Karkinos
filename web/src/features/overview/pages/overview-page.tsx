import { createLazyRoute } from '@tanstack/react-router';

import { WorkspaceHeader } from '../../../shared/ui/workbench';
import { OverviewLoadingWorkspace } from '../components/overview-loading-workspace';
import { OverviewResolvedWorkspace } from '../components/overview-resolved-workspace';
import { OverviewStatusCard } from '../components/overview-status-card';
import { useOverviewPageController } from '../model/use-overview-page-controller';

export function OverviewPage() {
  const controller = useOverviewPageController();
  const { copy, account } = controller;
  return (
    <section
      className="app-workbench-route overview-terminal-route min-w-0"
      data-testid="overview-page"
      data-workbench-route="overview"
      data-workbench-width="wide"
    >
      <WorkspaceHeader title={copy.overview.title} />
      {account.data ? (
        <OverviewResolvedWorkspace
          controller={controller}
          state={account.data}
        />
      ) : account.isLoading ? (
        <OverviewLoadingWorkspace copy={copy} />
      ) : (
        <OverviewStatusCard
          tone="danger"
          title={copy.states.error}
          detail={copy.overview.error}
          actionLabel={copy.states.retry}
          onAction={() => void account.refetch()}
        />
      )}
    </section>
  );
}

export const Route = createLazyRoute('/overview')({ component: OverviewPage });
