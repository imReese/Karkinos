import { useCopy } from '../../../app/copy';
import { formatCurrency } from '../../../shared/format';
import type { LiveHoldingGroup } from '../api';

function toneClass(value: number | null) {
  if (value === null || value === 0) {
    return 'app-pnl-neutral';
  }
  return value > 0 ? 'app-pnl-positive' : 'app-pnl-negative';
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
      <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
        {labels.empty}
      </div>
    );
  }

  return (
    <div
      data-testid="live-holdings-board"
      className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain border-y border-[var(--app-divider)] bg-transparent"
    >
      <div className="border-b border-[var(--app-divider)] px-3 py-2">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {labels.title}
        </div>
      </div>

      <div className="divide-y divide-[var(--app-divider)]">
        {groups.map((group) => (
          <div
            key={group.asset_class}
            data-testid={`live-holdings-group-summary-${group.asset_class}`}
            className="grid min-w-0 grid-cols-2 gap-2 px-3 py-2.5 sm:grid-cols-[minmax(112px,1.25fr)_repeat(3,minmax(84px,1fr))] sm:items-center"
          >
            <div className="col-span-2 min-w-0 sm:col-span-1">
              <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                {group.label || assetClassLabel(group.asset_class, copy.common)}
              </div>
              <div className="mt-0.5 text-xs text-[var(--app-text-tertiary)]">
                {labels.positionCount(group.items.length)}
              </div>
            </div>
            <SummaryMetric
              testId={`live-holdings-group-summary-${group.asset_class}-market-value`}
              label={copy.portfolio.table.marketValue}
              value={formatCurrency(group.total_market_value)}
              valueClassName="text-[var(--app-text)]"
            />
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
        ))}
      </div>

      <div className="border-t border-[var(--app-divider)] px-3 py-2 text-xs text-[var(--app-text-tertiary)]">
        {labels.summaryOnly}
      </div>
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
    <dl data-testid={testId} className="min-w-0 sm:text-right">
      <dt className="truncate text-[11px] text-[var(--app-text-secondary)]">
        {label}
      </dt>
      <dd
        className={`mt-0.5 truncate font-mono text-sm font-semibold tabular-nums ${valueClassName ?? ''}`}
      >
        {value}
      </dd>
    </dl>
  );
}
