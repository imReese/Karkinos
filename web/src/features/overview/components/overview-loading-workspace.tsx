import type { AppCopy } from '../../../shared/i18n/context';
import { EvidenceState } from '../../../shared/ui/workbench';

export function OverviewLoadingWorkspace({ copy }: { copy: AppCopy }) {
  return (
    <div
      className="min-w-0 space-y-6 pt-4"
      data-testid="overview-loading-workspace"
      aria-busy="true"
    >
      <EvidenceState kind="loading" title={copy.overview.loading} />

      <div aria-hidden="true" className="min-w-0 space-y-6">
        <section className="min-w-0 border-b border-[var(--app-divider)] pb-6">
          <div className="space-y-4 py-2">
            <span className="overview-loading-block h-3 w-24" />
            <div className="flex flex-wrap items-end gap-4">
              <span className="overview-loading-block h-12 w-56 max-w-full sm:w-72" />
              <span className="overview-loading-block h-6 w-28 rounded-full" />
              <span className="overview-loading-block h-6 w-36 rounded-full" />
            </div>
            <span className="overview-loading-block h-3 w-48 max-w-full" />
            <div className="grid grid-cols-2 divide-x divide-y divide-[var(--app-divider)] overflow-hidden rounded-xl border border-[var(--app-divider)] sm:grid-cols-4 sm:divide-y-0">
              {Array.from({ length: 4 }, (_, index) => (
                <div key={index} className="min-w-0 space-y-2 px-3 py-3">
                  <span className="overview-loading-block h-2 w-16" />
                  <span className="overview-loading-block h-4 w-24 max-w-full" />
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="min-w-0 border-b border-[var(--app-divider)] pb-6">
          <div className="flex gap-4 border-b border-[var(--app-divider)] pb-3">
            <span className="overview-loading-block h-4 w-20" />
            <span className="overview-loading-block h-4 w-20" />
          </div>
          <div className="flex h-56 min-w-0 flex-col justify-between py-5 sm:h-72">
            <span className="overview-loading-block h-3 w-28" />
            <span className="overview-loading-block h-2 w-full opacity-60" />
            <span className="overview-loading-block h-2 w-full opacity-60" />
            <span className="overview-loading-block h-2 w-full opacity-60" />
            <span className="overview-loading-block h-2 w-2/3 opacity-60" />
          </div>
        </section>

        <section className="min-w-0 border-b border-[var(--app-divider)] pb-6">
          <span className="overview-loading-block mb-4 h-5 w-28" />
          <div className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {Array.from({ length: 3 }, (_, index) => (
              <div
                key={index}
                className="flex min-h-12 min-w-0 items-center justify-between gap-4 py-3"
              >
                <span className="overview-loading-block h-4 w-32 max-w-[55%]" />
                <span className="overview-loading-block h-4 w-20" />
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
