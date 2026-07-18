import { useCopy } from '../../../app/copy';
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
      <section
        data-testid="portfolio-exposure-summary"
        className="app-terminal-panel rounded-[2rem] p-1.5"
      >
        <div className="app-terminal-inner rounded-[1.65rem] px-4 py-3 text-sm text-[var(--app-muted)] sm:px-5">
          {labels.exposureUnavailable}
        </div>
      </section>
    );
  }

  const stockWeight = groupWeight(snapshot, 'stock');
  const fundWeight = groupWeight(snapshot, 'fund');
  const cashWeight = groupWeight(snapshot, 'cash');
  const largest = snapshot.allocation
    .filter((item) => item.asset_class !== 'cash')
    .sort((left, right) => right.weight - left.weight)[0];
  const isPartial = snapshot.valuation_status !== 'complete';
  const metrics = [
    { key: 'stock', label: labels.stockExposure, weight: stockWeight },
    { key: 'fund', label: labels.fundExposure, weight: fundWeight },
    { key: 'cash', label: labels.cashExposure, weight: cashWeight },
  ];

  return (
    <section
      data-testid="portfolio-exposure-summary"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[2rem] p-1.5"
      aria-label={labels.exposureSummary}
    >
      <div className="app-terminal-inner min-w-0 rounded-[1.65rem] px-4 py-3 sm:px-5">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <div className="app-product-mark">{labels.exposureSummary}</div>
          {isPartial ? (
            <span className="rounded-full border border-[color-mix(in_srgb,var(--app-warning)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_9%,transparent)] px-2 py-0.5 text-[10px] font-semibold text-[var(--app-warning)]">
              {labels.exposurePartial}
            </span>
          ) : null}
        </div>
        <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <div
              key={metric.key}
              className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-3 py-2.5"
            >
              <div className="app-kicker text-[9px] text-[var(--app-text-tertiary)]">
                {metric.label}
              </div>
              <div className="mt-1 font-mono text-sm font-semibold tabular-nums text-[var(--app-soft)]">
                {metric.weight === null ? '--' : formatPercent(metric.weight)}
              </div>
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--app-border)_30%,transparent)]">
                <div
                  className="h-full rounded-full bg-[var(--app-accent)]"
                  style={{
                    width: `${Math.max(0, Math.min(100, (metric.weight ?? 0) * 100))}%`,
                  }}
                />
              </div>
            </div>
          ))}
          {largest ? (
            <a
              href={`/portfolio/${encodeURIComponent(largest.symbol)}`}
              className="group min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-accent)_24%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_7%,transparent)] px-3 py-2.5 transition-colors hover:border-[color-mix(in_srgb,var(--app-accent)_48%,transparent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
            >
              <div className="app-kicker text-[9px] text-[var(--app-text-tertiary)]">
                {labels.largestHolding}
              </div>
              <div className="mt-1 flex min-w-0 items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-xs font-semibold text-[var(--app-text)] group-hover:text-[var(--app-accent)]">
                  {largest.name}
                </span>
                <span className="shrink-0 font-mono text-sm font-semibold tabular-nums text-[var(--app-soft)]">
                  {formatPercent(largest.weight)}
                </span>
              </div>
              <div className="mt-2 truncate font-mono text-[10px] text-[var(--app-text-tertiary)]">
                {largest.symbol}
              </div>
            </a>
          ) : (
            <div className="min-w-0 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2.5 text-xs text-[var(--app-muted)]">
              {labels.largestHoldingUnavailable}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
