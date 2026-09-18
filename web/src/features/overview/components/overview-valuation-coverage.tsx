import { useCopy } from '../../../shared/i18n/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import type { PortfolioSnapshot } from '../overview-feature-boundary';

function laneLabel(assetClass: string, labels: Record<string, string>) {
  return labels[assetClass] ?? assetClass;
}

export function OverviewValuationCoverage({
  snapshot,
}: {
  snapshot: PortfolioSnapshot;
}) {
  const copy = useCopy();
  const lanes = snapshot.valuation_lanes ?? [];
  if (snapshot.valuation_status === 'complete' || !lanes.length) return null;

  const dashboard = copy.overview.dashboard;
  const assetClassLabels = dashboard.valuationCoverageAssetClasses as Record<
    string,
    string
  >;

  return (
    <section
      className="min-w-0 border-b border-[var(--app-divider)] py-3.5"
      data-testid="overview-valuation-coverage"
    >
      <SectionHeader
        title={dashboard.valuationCoverage}
        description={dashboard.valuationCoverageDetail}
        meta={snapshot.valuation_status}
      />
      <div className="mt-3 grid min-w-0 gap-x-6 gap-y-3 md:grid-cols-2">
        {lanes
          .filter((lane) => lane.status !== 'not_applicable')
          .map((lane) => {
            const denominator = Math.max(lane.quote_count, 1);
            const coverage = Math.max(
              0,
              Math.min(100, (lane.complete_quote_count / denominator) * 100),
            );
            return (
              <div key={lane.asset_class} className="min-w-0">
                <div className="app-type-compact flex items-baseline justify-between gap-3">
                  <span className="font-semibold text-[var(--app-text)]">
                    {laneLabel(lane.asset_class, assetClassLabels)}
                  </span>
                  <span className="tabular-nums text-[var(--app-text-secondary)]">
                    {lane.complete_quote_count}/{lane.quote_count}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-[var(--app-radius-control)] bg-[var(--app-divider)]">
                  <div
                    className="h-full bg-[var(--app-accent)]"
                    style={{ width: `${coverage}%` }}
                    aria-hidden="true"
                  />
                </div>
                <div className="app-type-micro mt-1 flex min-w-0 flex-wrap gap-x-2 text-[var(--app-text-tertiary)]">
                  <span>
                    {lane.review_required_quote_count > 0
                      ? dashboard.valuationCoverageReview(
                          lane.review_required_quote_count,
                        )
                      : dashboard.valuationCoverageComplete}
                  </span>
                  {lane.blocker_statuses.length ? (
                    <span>{lane.blocker_statuses.join(' · ')}</span>
                  ) : null}
                </div>
              </div>
            );
          })}
      </div>
    </section>
  );
}
