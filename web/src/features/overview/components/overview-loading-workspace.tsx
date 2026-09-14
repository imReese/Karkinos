import type { AppCopy } from '../../../shared/i18n/context';
import { EvidenceState } from '../../../shared/ui/workbench';

export function OverviewLoadingWorkspace({ copy }: { copy: AppCopy }) {
  return (
    <div className="space-y-5" data-testid="overview-loading-workspace">
      <EvidenceState kind="loading" title={copy.overview.loading} />
      <div aria-hidden="true" className="space-y-5">
        <div className="h-10 w-56 bg-[var(--app-divider)]" />
        <div className="grid grid-cols-3 gap-5">
          {[0, 1, 2].map((item) => (
            <div key={item} className="h-12 bg-[var(--app-divider)]" />
          ))}
        </div>
        <div className="h-52 border-y border-[var(--app-divider)]" />
      </div>
    </div>
  );
}
