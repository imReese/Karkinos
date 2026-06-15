import { useCopy } from '../../../app/copy';
import { formatCurrency } from '../../../shared/format';
import type { LiveHoldingGroup } from '../api';

function toneClass(value: number | null) {
  if (value === null || value === 0) {
    return 'text-[var(--app-foreground)]';
  }
  return value > 0 ? 'app-positive' : 'app-negative';
}

function assetClassLabel(
  assetClass: string,
  labels: {
    assetClassStock: string;
    assetClassEtf: string;
    assetClassFund: string;
    assetClassGold: string;
    assetClassBond: string;
  },
) {
  switch (assetClass) {
    case 'stock':
      return labels.assetClassStock;
    case 'etf':
      return labels.assetClassEtf;
    case 'fund':
      return labels.assetClassFund;
    case 'gold':
      return labels.assetClassGold;
    case 'bond':
      return labels.assetClassBond;
    default:
      return assetClass;
  }
}

export function LiveHoldingsBoard({ groups }: { groups: LiveHoldingGroup[] }) {
  const copy = useCopy();
  const labels = copy.portfolio.liveBoard;

  if (groups.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-4 text-sm app-muted sm:p-5">
        {labels.empty}
      </div>
    );
  }

  return (
    <div
      data-testid="live-holdings-board"
      className="app-panel rounded-2xl p-4 sm:p-5"
    >
      <div className="app-card-header">
        <div className="app-card-title">{labels.title}</div>
      </div>

      <div className="mt-5 grid gap-3 lg:grid-cols-3">
        {groups.map((group) => (
          <div
            key={group.asset_class}
            data-testid={`live-holdings-group-summary-${group.asset_class}`}
            className="app-panel-strong rounded-2xl px-4 py-4"
          >
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">
                  {group.label ||
                    assetClassLabel(group.asset_class, copy.common)}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {labels.positionCount(group.items.length)}
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-2">
              <SummaryMetric
                testId={`live-holdings-group-summary-${group.asset_class}-market-value`}
                label={copy.portfolio.table.marketValue}
                value={formatCurrency(group.total_market_value)}
                valueClassName="text-base"
              />
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
                <SummaryMetric
                  testId={`live-holdings-group-summary-${group.asset_class}-today-move`}
                  label={labels.todayMove}
                  value={formatCurrency(group.total_today_change)}
                  valueClassName={toneClass(group.total_today_change)}
                />
                <SummaryMetric
                  testId={`live-holdings-group-summary-${group.asset_class}-since-buy`}
                  label={labels.sinceBuyReturn}
                  value={formatCurrency(group.total_since_buy_pnl)}
                  valueClassName={toneClass(group.total_since_buy_pnl)}
                />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="app-muted mt-4 text-xs">{labels.summaryOnly}</div>
    </div>
  );
}

function SummaryMetric({
  testId,
  label,
  value,
  valueClassName,
}: {
  testId: string;
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-3"
    >
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
        {label}
      </div>
      <div
        className={`mt-2 truncate text-sm font-semibold tabular-nums ${valueClassName ?? ''}`}
      >
        {value}
      </div>
    </div>
  );
}
