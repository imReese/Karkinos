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
    },
    {
      label: labels.cashBuffer,
      value: formatPercent(overview.cash_ratio),
      hint: overview.cash_ratio >= 0.2 ? labels.cashHealthy : labels.cashWatch,
    },
    {
      label: labels.deployment,
      value: formatPercent(deploymentRatio),
      hint:
        deploymentRatio >= 0.8
          ? labels.deploymentHigh
          : labels.deploymentBalanced,
    },
    {
      label: labels.positions,
      value: String(overview.positions_count),
      hint: labels.positionsHint(overview.positions_count),
    },
  ];

  return (
    <div className="app-surface-card p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between">
        <div className="app-card-title">{labels.title}</div>
      </div>
      <div className="grid overflow-hidden rounded-lg border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] sm:grid-cols-2">
        {items.map((item, index) => (
          <div
            key={item.label}
            className={`px-4 py-3 transition-colors duration-200 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] ${
              index > 0
                ? 'border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)]'
                : ''
            } ${index === 1 ? 'sm:border-t-0' : ''} ${
              index % 2 === 1
                ? 'sm:border-l sm:border-[color-mix(in_srgb,var(--app-border)_24%,transparent)]'
                : ''
            }`}
          >
            <div className="app-kicker app-tier-4-label">{item.label}</div>
            <div className="mt-2 text-lg font-semibold tabular-nums">
              {item.value}
            </div>
            <div className="app-muted mt-1.5 text-xs">{item.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
