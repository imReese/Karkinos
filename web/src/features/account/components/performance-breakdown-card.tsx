import { useCopy } from '../../../app/copy';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { AccountOverview } from '../api';
import type { PortfolioSnapshot } from '../../portfolio/api';

type BreakdownMode = 'account' | 'strategy';

export function PerformanceBreakdownCard({
  overview,
  snapshot,
  mode,
  onModeChange,
  accountLabel,
  strategyLabel,
}: {
  overview: AccountOverview;
  snapshot: PortfolioSnapshot;
  mode: BreakdownMode;
  onModeChange: (mode: BreakdownMode) => void;
  accountLabel: string;
  strategyLabel: string;
}) {
  const copy = useCopy();
  const labels = copy.overview.breakdown;
  const investedCapital = Math.max(snapshot.total_equity - snapshot.cash, 0);
  const totalPnl = overview.realized_pnl + overview.unrealized_pnl;
  const deploymentRatio =
    snapshot.total_equity > 0 ? investedCapital / snapshot.total_equity : 0;

  const items =
    mode === 'account'
      ? [
          {
            label: labels.marketValue,
            value: formatCurrency(investedCapital),
            hint: labels.activePositions(overview.positions_count),
          },
          {
            label: labels.cashReserve,
            value: formatCurrency(snapshot.cash),
            hint: formatPercent(overview.cash_ratio),
          },
          {
            label: labels.netDeposits,
            value: formatCurrency(snapshot.total_deposits),
            hint: labels.capitalBase,
          },
          {
            label: labels.deployment,
            value: formatPercent(deploymentRatio),
            hint: labels.capitalAtWork,
          },
        ]
      : [
          {
            label: labels.unrealizedPnl,
            value: formatCurrency(overview.unrealized_pnl),
            hint: labels.openPositions,
          },
          {
            label: labels.realizedPnl,
            value: formatCurrency(overview.realized_pnl),
            hint: labels.closedActivity,
          },
          {
            label: labels.totalPnl,
            value: formatCurrency(totalPnl),
            hint: labels.totalPnlHint,
          },
          {
            label: labels.payoutBuffer,
            value: formatCurrency(snapshot.cash),
            hint: labels.payoutBufferHint,
          },
        ];

  return (
    <div className="app-surface-card p-4 sm:p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[10px] uppercase tracking-[0.18em]">
            {mode === 'account' ? labels.accountKicker : labels.strategyKicker}
          </div>
          <div className="app-card-title mt-1.5">
            {mode === 'account' ? labels.accountTitle : labels.strategyTitle}
          </div>
        </div>
        <div
          data-testid="breakdown-perspective-switcher"
          className="app-inline-segmented shrink-0 rounded-full"
        >
          {[
            { value: 'account', label: accountLabel },
            { value: 'strategy', label: strategyLabel },
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={mode === item.value}
              onClick={() => onModeChange(item.value as BreakdownMode)}
              className={`app-inline-segmented-btn ${
                mode === item.value ? 'app-inline-segmented-btn-active' : ''
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] sm:grid-cols-2">
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
            <div className="mt-2 text-lg font-semibold tracking-[-0.02em] tabular-nums">
              {item.value}
            </div>
            <div className="app-muted mt-1.5 text-xs">{item.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
