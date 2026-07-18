import { useCopy } from '../../../app/copy';
import {
  EvidenceState,
  MetricStrip,
  type MetricStripItem,
} from '../../../app/components/workbench';
import { formatPercent } from '../../../shared/format';
import type { PortfolioSnapshot } from '../../portfolio/api';

function groupWeight(snapshot: PortfolioSnapshot, assetClass: string) {
  return (
    snapshot.allocation_grouped.find(
      (group) => group.asset_class === assetClass,
    )?.weight ?? null
  );
}

export function PortfolioExposureSummary({
  snapshot,
}: {
  snapshot: PortfolioSnapshot;
}) {
  const labels = useCopy().overview.cards;
  if (!(snapshot.total_equity > 0)) {
    return (
      <div data-testid="portfolio-exposure-summary">
        <EvidenceState kind="missing" title={labels.exposureUnavailable} />
      </div>
    );
  }

  const stockWeight = groupWeight(snapshot, 'stock');
  const fundWeight = groupWeight(snapshot, 'fund');
  const cashWeight = groupWeight(snapshot, 'cash');
  const largest = snapshot.allocation
    .filter((item) => item.asset_class !== 'cash')
    .sort((left, right) => right.weight - left.weight)[0];
  const isPartial = snapshot.valuation_status !== 'complete';
  const metrics: MetricStripItem[] = [
    {
      id: 'stock',
      label: labels.stockExposure,
      value: stockWeight === null ? '--' : formatPercent(stockWeight),
    },
    {
      id: 'fund',
      label: labels.fundExposure,
      value: fundWeight === null ? '--' : formatPercent(fundWeight),
    },
    {
      id: 'cash',
      label: labels.cashExposure,
      value: cashWeight === null ? '--' : formatPercent(cashWeight),
    },
    {
      id: 'largest',
      label: labels.largestHolding,
      value: largest ? formatPercent(largest.weight) : '--',
      detail: largest ? `${largest.name} · ${largest.symbol}` : undefined,
    },
  ];

  return (
    <section
      data-testid="portfolio-exposure-summary"
      className="min-w-0"
      aria-label={labels.exposureSummary}
    >
      <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {labels.exposureSummary}
        </div>
        {isPartial ? (
          <span className="text-xs font-semibold text-[var(--app-warning-text)]">
            {labels.exposurePartial}
          </span>
        ) : null}
      </div>
      <MetricStrip
        items={metrics}
        ariaLabel={labels.exposureSummary}
        className="sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-col lg:grid-cols-none"
      />
    </section>
  );
}
