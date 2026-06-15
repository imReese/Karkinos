import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatQuantity,
  formatReturnPercent,
} from '../../../shared/format';
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
    <div className="app-panel rounded-2xl p-4 sm:p-5">
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

      <div className="mt-5 space-y-4">
        {groups.map((group) => (
          <section key={group.asset_class} className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)] px-2.5 py-1 text-xs font-semibold text-[var(--app-soft)]">
                  {group.label ||
                    assetClassLabel(group.asset_class, copy.common)}
                </span>
                <span className="truncate text-base font-semibold">
                  {labels.positionCount(group.items.length)}
                </span>
              </div>
              <div className="app-muted text-sm">{labels.latestPrice}</div>
            </div>
            <div className="grid gap-2">
              {group.items.map((item) => (
                <a
                  key={item.symbol}
                  href={`/portfolio/${encodeURIComponent(item.symbol)}`}
                  aria-label={labels.holdingDetailLink(item.symbol)}
                  className="group grid min-w-0 gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 transition-colors duration-200 hover:border-[color-mix(in_srgb,var(--app-accent)_34%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-accent)_8%,transparent)] md:grid-cols-[minmax(0,1fr)_150px_150px_112px] md:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-semibold text-[var(--app-text)] group-hover:text-[var(--app-accent)]">
                        {item.display_name || item.name || item.symbol}
                      </div>
                      <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--app-muted)]">
                        {assetClassLabel(item.asset_class, copy.common)}
                      </span>
                    </div>
                    <div className="app-muted mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-mono">{item.symbol}</span>
                      <span>{formatQuantity(item.quantity)}</span>
                    </div>
                  </div>
                  <CompactHoldingMetric
                    label={labels.latestPrice}
                    value={formatCurrency(item.latest_price)}
                  />
                  <CompactHoldingMetric
                    label={labels.todayMove}
                    value={formatCurrency(item.today_change)}
                    hint={formatReturnPercent(item.today_change_pct)}
                    tone={toneClass(item.today_change)}
                  />
                  <div className="flex flex-wrap items-center gap-2 text-xs md:justify-end">
                    <span className="app-button-secondary rounded-full px-3 py-1">
                      {item.quote_status === 'live'
                        ? labels.quoteLive
                        : labels.quoteStale}
                    </span>
                  </div>
                </a>
              ))}
            </div>
          </section>
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

function CompactHoldingMetric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {label}
      </div>
      <div className={`mt-1 truncate text-sm font-semibold ${tone ?? ''}`}>
        {value}
      </div>
      {hint ? <div className="app-muted mt-1 text-xs">{hint}</div> : null}
    </div>
  );
}
