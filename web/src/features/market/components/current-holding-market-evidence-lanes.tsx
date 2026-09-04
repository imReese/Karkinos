import { useCopy } from '../../../shared/i18n/context';
import { findMarketEvidenceLane } from '../../../shared/portfolio-evidence/market-evidence-lanes';
import type { CurrentHoldingMarketEvidenceLane } from '../../../shared/portfolio-evidence/contracts';
import { StatusBadge } from '../../../shared/ui/workbench';
import type { CurrentHoldingMarketEvidenceReview } from '../market-feature-boundary';

type Props = {
  report?: CurrentHoldingMarketEvidenceReview | null;
};

function laneTone(status: CurrentHoldingMarketEvidenceLane['status']) {
  if (status === 'complete') return 'success' as const;
  if (status === 'degraded') return 'warning' as const;
  if (status === 'missing' || status === 'blocked_identity') {
    return 'danger' as const;
  }
  return 'neutral' as const;
}

export function CurrentHoldingMarketEvidenceLanes({ report }: Props) {
  const labels = useCopy().market;
  const evidenceLanes = (['stock', 'fund'] as const)
    .map((assetClass) => findMarketEvidenceLane(report, assetClass))
    .filter(
      (lane): lane is CurrentHoldingMarketEvidenceLane => lane !== undefined,
    );

  if (evidenceLanes.length === 0) return null;

  return (
    <div
      className="grid divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] sm:grid-cols-2 sm:divide-x sm:divide-y-0"
      data-testid="holding-evidence-asset-lanes"
    >
      {evidenceLanes.map((lane) => {
        const isStockLane = lane.asset_class === 'stock';
        return (
          <div
            key={lane.asset_class}
            className="min-w-0 px-3 py-2.5"
            data-testid={`holding-evidence-lane-${lane.asset_class}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-semibold text-[var(--app-text)]">
                {isStockLane
                  ? labels.holdingEvidenceStockLane
                  : labels.holdingEvidenceFundLane}
              </span>
              <StatusBadge tone={laneTone(lane.status)}>
                {labels.holdingEvidenceLaneStatuses[lane.status]}
              </StatusBadge>
            </div>
            <p className="mt-1.5 text-xs leading-5 text-[var(--app-text-secondary)]">
              {isStockLane
                ? labels.holdingEvidenceStockLaneDetail(lane.status)
                : labels.holdingEvidenceFundLaneDetail(lane.status)}
            </p>
            {lane.current_holding_count > 0 ? (
              <p className="mt-1 app-type-micro tabular-nums text-[var(--app-text-tertiary)]">
                {labels.holdingEvidenceLaneCoverage(
                  lane.confirmed_holding_count,
                  lane.current_holding_count,
                )}
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
