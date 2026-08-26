import type { useCopy } from '../../../shared/i18n/context';
import { EvidenceState, WorkspaceHeader } from '../../../shared/ui/workbench';

export function PortfolioPageLoadingView({
  copy,
}: {
  copy: ReturnType<typeof useCopy>;
}) {
  return (
    <section className="space-y-4 sm:space-y-5">
      <WorkspaceHeader
        eyebrow={copy.portfolio.kicker}
        title={copy.portfolio.title}
        description={copy.portfolio.subtitle}
      />
      <EvidenceState
        kind="loading"
        statusLabel={copy.states.loading}
        title={copy.portfolio.summary.loading}
        description={copy.portfolio.summary.loadingDetail}
      />
      <div
        aria-hidden="true"
        className="app-metric-strip grid min-w-0 grid-cols-2 border-y border-[var(--app-divider)] bg-transparent sm:grid-flow-col sm:auto-cols-fr sm:grid-cols-none"
        data-testid="portfolio-loading-summary"
      >
        {[
          copy.portfolio.summary.totalEquity,
          copy.portfolio.summary.cash,
          copy.portfolio.summary.openHoldings,
          copy.portfolio.summary.realizedPnl,
        ].map((label) => (
          <div
            key={label}
            className="app-metric-strip-item min-w-0 px-3 py-2.5"
          >
            <span className="app-type-label block truncate font-medium text-[var(--app-text-secondary)]">
              {label}
            </span>
            <span className="mt-2 block h-4 w-24 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
            <span className="mt-2 block h-2 w-32 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
          </div>
        ))}
      </div>
      <section
        className="min-w-0 space-y-2"
        data-testid="portfolio-loading-current-holdings"
      >
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.portfolio.currentHoldings.title}
          </h2>
          <p className="mt-0.5 max-w-4xl text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.portfolio.currentHoldings.detail}
          </p>
        </div>
        <div
          aria-hidden="true"
          className="flex min-w-0 flex-wrap gap-2 border-y border-[var(--app-divider)] py-2"
          data-testid="portfolio-loading-filters"
        >
          <span className="block h-9 w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)] sm:w-64" />
          <span className="block h-9 w-40 rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
          <span className="block h-9 w-40 rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
        </div>
        <div
          aria-hidden="true"
          className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
          data-testid="portfolio-loading-rows"
        >
          {Array.from({ length: 4 }, (_, index) => (
            <div
              key={index}
              className="grid min-h-16 min-w-0 grid-cols-[minmax(0,1fr)_7rem] items-center gap-4 px-3 py-3 md:min-h-14 md:grid-cols-[minmax(9rem,1fr)_repeat(4,minmax(5rem,0.55fr))_minmax(8rem,0.75fr)]"
            >
              <span className="block h-3 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
              {Array.from({ length: 5 }, (_, metricIndex) => (
                <span
                  key={metricIndex}
                  className={`h-3 rounded-[var(--app-radius-control)] bg-[var(--app-divider)] ${
                    metricIndex > 0 ? 'hidden md:block' : 'block'
                  }`}
                />
              ))}
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
