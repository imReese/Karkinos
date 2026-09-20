import type { AppCopy } from '../../../shared/i18n/context';
import { EvidenceLoadingLayout } from '../../../shared/ui/workbench';

export function OverviewLoadingWorkspace({ copy }: { copy: AppCopy }) {
  return (
    <div className="pt-4" data-testid="overview-loading-workspace">
      <EvidenceLoadingLayout
        title={copy.overview.loading}
        metricCount={4}
        rowCount={4}
      />
    </div>
  );
}
