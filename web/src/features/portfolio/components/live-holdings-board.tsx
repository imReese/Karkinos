import { useCopy } from '../../../shared/i18n/context';
import { formatCurrency } from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import type { LiveHoldingGroup } from '../api';

function toneClass(value: number | null) {
  if (value === null || value === 0) {
    return 'app-pnl-neutral';
  }
  return value > 0 ? 'app-pnl-positive' : 'app-pnl-negative';
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
      className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-4 sm:p-5 space-y-3 shadow-xs"
    >
      <div className="flex items-center justify-between pb-1">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {labels.title}
        </div>
        <span className="text-xs text-[var(--app-text-tertiary)]">
          {labels.summaryOnly}
        </span>
      </div>

      <div className="space-y-2">
        {groups.map((group) => (
          <div
            key={group.asset_class}
            data-testid={`live-holdings-group-summary-${group.asset_class}`}
            className="grid min-w-0 grid-cols-2 gap-2 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-3.5 py-3 sm:grid-cols-[minmax(112px,1.25fr)_repeat(3,minmax(84px,1fr))] sm:items-center"
          >
            <div className="col-span-2 min-w-0 sm:col-span-1">
              <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                {group.label ||
                  formatAssetClassLabel(group.asset_class, copy.common)}
              </div>
              <div className="mt-0.5 text-xs text-[var(--app-text-tertiary)]">
                {labels.positionCount(group.items.length)}
              </div>
            </div>
            <SummaryMetric
              testId={`live-holdings-group-summary-${group.asset_class}-market-value`}
              label={copy.portfolio.table.marketValue}
              value={formatCurrency(group.total_market_value)}
              valueClassName="text-[var(--app-text)] font-mono font-medium"
            />
            <SummaryMetric
              testId={`live-holdings-group-summary-${group.asset_class}-today-move`}
              label={labels.todayMove}
              value={formatCurrency(group.total_today_change)}
              valueClassName={`${toneClass(group.total_today_change)} font-mono font-medium`}
            />
            <SummaryMetric
              testId={`live-holdings-group-summary-${group.asset_class}-since-buy`}
              label={labels.sinceBuyReturn}
              value={formatCurrency(group.total_since_buy_pnl)}
              valueClassName={`${toneClass(group.total_since_buy_pnl)} font-mono font-medium`}
            />
          </div>
        ))}
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
      <dt className="app-type-micro truncate text-[var(--app-text-secondary)]">
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
