import type { AppCopy } from '../../../shared/i18n/context';
import { EvidenceState } from '../../../shared/ui/workbench';

export function OverviewLoadingWorkspace({
  copy,
  todayPnlLabel,
}: {
  copy: AppCopy;
  todayPnlLabel: string;
}) {
  return (
    <div className="min-w-0 space-y-4" data-testid="overview-loading-workspace">
      <EvidenceState
        kind="loading"
        statusLabel={copy.states.loading}
        title={copy.overview.loading}
      />
      <section
        aria-hidden="true"
        className="account-overview-summary min-w-0"
        data-testid="overview-loading-summary"
      >
        <dl className="account-primary-metric min-w-0">
          <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
            {copy.overview.cards.totalAssets}
          </dt>
          <dd className="mt-2 h-7 w-44 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
          <div className="mt-2 h-2 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
        </dl>
        <div
          className="account-metric-strip account-support-metric-strip app-metric-strip grid min-w-0 sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-row lg:grid-cols-5"
          data-testid="overview-loading-supporting-metrics"
        >
          {[
            todayPnlLabel,
            copy.overview.cards.unrealizedPnl,
            copy.portfolio.table.realized,
            copy.overview.cards.availableCash,
            copy.overview.cards.currentDrawdown,
          ].map((label) => (
            <div
              key={label}
              className="app-metric-strip-item min-w-0 px-3 py-2.5"
            >
              <span className="app-type-label block font-medium text-[var(--app-text-secondary)]">
                {label}
              </span>
              <span className="mt-2 block h-4 w-24 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
            </div>
          ))}
        </div>
      </section>
      <div
        className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(340px,0.85fr)]"
        data-testid="overview-loading-daily-workbench"
      >
        <section
          className="min-w-0 space-y-2 xl:order-2"
          data-testid="overview-loading-queue"
        >
          <div>
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {copy.overview.dashboard.todayToReview}
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
              {copy.overview.dashboard.opsPanel}
            </p>
          </div>
          <div
            aria-hidden="true"
            className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
            data-testid="overview-loading-queue-rows"
          >
            {Array.from({ length: 2 }, (_, index) => (
              <div key={index} className="min-w-0 px-3 py-3">
                <span className="block h-3 w-28 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                <span className="mt-2 block h-3 w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
              </div>
            ))}
          </div>
        </section>
        <section
          className="min-w-0 space-y-2 xl:order-1"
          data-testid="overview-loading-holdings"
        >
          <div>
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {copy.overview.dashboard.positionsPanel}
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
              {copy.overview.dashboard.positionsDetail}
            </p>
          </div>
          <div
            aria-hidden="true"
            className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
            data-testid="overview-loading-holding-rows"
          >
            {Array.from({ length: 3 }, (_, index) => (
              <div
                key={index}
                className="grid min-h-14 min-w-0 grid-cols-[minmax(0,1fr)_6rem] items-center gap-4 px-3 py-3 sm:grid-cols-[minmax(9rem,1fr)_repeat(3,minmax(5rem,0.55fr))]"
              >
                <span className="block h-3 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                {Array.from({ length: 3 }, (_, metricIndex) => (
                  <span
                    key={metricIndex}
                    className={`h-3 rounded-[var(--app-radius-control)] bg-[var(--app-divider)] ${
                      metricIndex > 0 ? 'hidden sm:block' : 'block'
                    }`}
                  />
                ))}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
