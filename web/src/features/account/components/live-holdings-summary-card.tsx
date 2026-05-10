import { useCopy } from '../../../app/copy';
import { formatCurrency } from '../../../shared/format';
import type { LiveHoldingGroup } from '../../portfolio/api';

function toneClass(value: number) {
  if (value === 0) {
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

export function LiveHoldingsSummaryCard({
  groups,
  onSelectAssetClass,
}: {
  groups: LiveHoldingGroup[];
  onSelectAssetClass?: (assetClass: string) => void;
}) {
  const copy = useCopy();
  const labels = copy.overview.livePulse;

  if (groups.length === 0) {
    return (
      <div className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-4 text-sm app-muted sm:p-5">
        <div className="app-card-title text-[var(--app-text)]">
          {labels.title}
        </div>
        <div className="mt-3">{labels.empty}</div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)]">
      <div className="flex items-center justify-between border-b border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] px-4 py-3 sm:px-5">
        <div className="app-card-title">{labels.title}</div>
      </div>
      <div className="grid divide-y divide-[color-mix(in_srgb,var(--app-border)_24%,transparent)] lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        {groups.map((group) => (
          <button
            key={group.asset_class}
            type="button"
            onClick={() => onSelectAssetClass?.(group.asset_class)}
            className="group relative px-4 py-3 text-left transition-colors duration-200 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)] sm:px-5"
          >
            <span
              className="absolute left-0 top-3 h-7 w-px bg-[var(--app-accent)] opacity-0 transition-opacity duration-200 group-hover:opacity-50"
              aria-hidden="true"
            />
            <div className="text-base font-semibold">
              {assetClassLabel(group.asset_class, copy.common)}
            </div>
            <div className="mt-3 grid gap-2">
              <Metric
                label={labels.marketValue}
                value={formatCurrency(group.total_market_value)}
              />
              <Metric
                label={labels.todayMove}
                value={formatCurrency(group.total_today_change)}
                tone={toneClass(group.total_today_change)}
              />
              <Metric
                label={labels.sinceBuyReturn}
                value={formatCurrency(group.total_since_buy_pnl)}
                tone={toneClass(group.total_since_buy_pnl)}
              />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <div className="app-kicker app-tier-4-label">{label}</div>
      <div className={`mt-1 text-sm font-semibold tabular-nums ${tone ?? ''}`}>
        {value}
      </div>
    </div>
  );
}
