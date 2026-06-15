import { useCopy } from '../../../app/copy';
import { formatPercent } from '../../../shared/format';
import type { AccountOverview } from '../api';
import type { PortfolioSnapshot } from '../../portfolio/api';

export function RiskSummaryCard({
  overview,
  snapshot,
}: {
  overview: AccountOverview;
  snapshot: PortfolioSnapshot;
}) {
  const copy = useCopy();
  const labels = copy.overview.risk;
  const topHoldingWeight = Math.max(
    ...snapshot.allocation.map((item) => item.weight),
    0,
  );
  const deploymentRatio =
    snapshot.total_equity > 0
      ? Math.max(snapshot.total_equity - snapshot.cash, 0) /
        snapshot.total_equity
      : 0;

  const items = [
    {
      label: labels.concentration,
      value: formatPercent(topHoldingWeight),
      hint: snapshot.allocation[0]?.name ?? '--',
      boundary: labels.concentrationBoundary,
    },
    {
      label: labels.cashBuffer,
      value: formatPercent(overview.cash_ratio),
      hint: overview.cash_ratio >= 0.2 ? labels.cashHealthy : labels.cashWatch,
      boundary: labels.cashBoundary,
    },
    {
      label: labels.deployment,
      value: formatPercent(deploymentRatio),
      hint:
        deploymentRatio >= 0.8
          ? labels.deploymentHigh
          : labels.deploymentBalanced,
      boundary: labels.deploymentBoundary,
    },
    {
      label: labels.positions,
      value: String(overview.positions_count),
      hint: labels.positionsHint(overview.positions_count),
      boundary: labels.positionsBoundary,
    },
  ];

  return (
    <div
      data-testid="risk-boundary-register"
      className="app-surface-card min-w-0 p-4 sm:p-5"
    >
      <div className="mb-4 min-w-0">
        <div className="app-kicker app-tier-4-label">
          {labels.registerKicker}
        </div>
        <div className="mt-1 app-card-title">{labels.title}</div>
        <div className="app-muted mt-2 text-sm">{labels.subtitle}</div>
      </div>
      <div className="grid min-w-0 gap-3">
        {items.map((item) => (
          <div
            key={item.label}
            aria-label={`Risk boundary item: ${item.label} ${item.value} ${item.hint}`}
            className="app-panel-strong min-w-0 rounded-2xl px-4 py-3"
          >
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="app-kicker app-tier-4-label">{item.label}</div>
                <div className="app-muted mt-1 break-words text-xs">
                  {item.boundary}
                </div>
              </div>
              <div className="text-right">
                <div className="text-base font-semibold tabular-nums">
                  {item.value}
                </div>
                <div className="app-muted mt-1 text-xs">{labels.current}</div>
              </div>
            </div>
            <div className="mt-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
              <span className="rounded-full bg-[color-mix(in_srgb,var(--app-accent)_12%,transparent)] px-2.5 py-1 text-xs font-semibold text-[var(--app-accent-strong)]">
                {labels.boundary}
              </span>
              <span className="app-muted min-w-0 break-words text-xs">
                {item.hint}
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="app-panel-strong mt-4 min-w-0 rounded-2xl px-4 py-3">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold">
              {labels.executionBoundary}
            </div>
            <div className="app-muted mt-1 break-words text-xs">
              {labels.executionBoundaryDetail}
            </div>
          </div>
          <span className="shrink-0 rounded-full bg-[color-mix(in_srgb,var(--app-warning)_18%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-warning)]">
            {labels.manualConfirmationRequired}
          </span>
        </div>
      </div>
    </div>
  );
}
