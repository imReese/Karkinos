import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatPercent,
  formatQuantity,
} from '../../../shared/format';
import type { LiveHoldingGroup } from '../api';

function toneClass(value: number | null) {
  if (value === null || value === 0) {
    return 'text-[var(--app-foreground)]';
  }
  return value > 0 ? 'app-positive' : 'app-negative';
}

function baselineLabel(
  baselineSource: string,
  previousCloseLabel: string,
  fallbackCloseLabel: string,
  unavailableLabel: string,
) {
  if (baselineSource === 'previous_close') {
    return previousCloseLabel;
  }
  if (baselineSource === 'fallback_close') {
    return fallbackCloseLabel;
  }
  return unavailableLabel;
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
            className="app-panel-strong rounded-2xl px-4 py-4"
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">
                  {group.label || assetClassLabel(group.asset_class, copy.common)}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {labels.positionCount(group.items.length)}
                </div>
              </div>
              <div
                className={`text-sm font-semibold ${toneClass(group.total_today_change)}`}
              >
                {formatCurrency(group.total_today_change)}
              </div>
            </div>
            <div className="mt-3 text-lg font-semibold">
              {formatCurrency(group.total_market_value)}
            </div>
            <div className="mt-2 flex items-center justify-between gap-3 text-xs">
              <span className="app-muted">{labels.todayMove}</span>
              <span className={toneClass(group.total_since_buy_pnl)}>
                {labels.sinceBuyReturn}{' '}
                {formatCurrency(group.total_since_buy_pnl)}
              </span>
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
                  {group.label || assetClassLabel(group.asset_class, copy.common)}
                </span>
                <span className="truncate text-base font-semibold">
                  {labels.positionCount(group.items.length)}
                </span>
              </div>
              <div className="app-muted text-sm">
                {formatCurrency(group.total_market_value)}
              </div>
            </div>
            <div className="grid gap-3">
              {group.items.map((item) => (
                <div
                  key={item.symbol}
                  className="app-panel-strong rounded-2xl px-4 py-4"
                >
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <div className="truncate text-sm font-semibold">
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
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="app-button-secondary rounded-full px-3 py-1">
                        {item.quote_status === 'live'
                          ? labels.quoteLive
                          : labels.quoteStale}
                      </span>
                      <span className="app-button-secondary rounded-full px-3 py-1">
                        {labels.baseline}:{' '}
                        {baselineLabel(
                          item.baseline_source,
                          labels.baselinePreviousClose,
                          labels.baselineFallbackClose,
                          labels.baselineUnavailable,
                        )}
                      </span>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <Metric
                      label={labels.latestPrice}
                      value={formatCurrency(item.latest_price)}
                    />
                    <Metric
                      label={labels.todayMove}
                      value={formatCurrency(item.today_change)}
                      tone={toneClass(item.today_change)}
                      hint={formatPercent(item.today_change_pct)}
                    />
                    <Metric
                      label={labels.sinceBuyReturn}
                      value={formatCurrency(item.since_buy_pnl)}
                      tone={toneClass(item.since_buy_pnl)}
                      hint={formatPercent(item.since_buy_pnl_pct)}
                    />
                    <Metric
                      label={copy.portfolio.table.marketValue}
                      value={formatCurrency(item.market_value)}
                      hint={`${copy.portfolio.table.avgCost} ${formatCurrency(item.avg_cost)}`}
                    />
                  </div>

                  <div className="app-muted mt-3 text-xs">
                    {labels.updatedAt}: {item.quote_timestamp ?? '--'}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function Metric({
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
    <div className="rounded-2xl border border-[var(--app-border)] px-4 py-4">
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
        {label}
      </div>
      <div className={`mt-2 text-sm font-semibold ${tone ?? ''}`}>{value}</div>
      {hint ? <div className="app-muted mt-2 text-xs">{hint}</div> : null}
    </div>
  );
}
