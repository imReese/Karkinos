import { useCopy } from "../../../app/copy";
import type { AccountOverview } from "../api";
import type { PortfolioSnapshot } from "../../portfolio/api";

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

type BreakdownMode = "account" | "strategy";

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
    mode === "account"
      ? [
          {
            label: labels.marketValue,
            value: currency.format(investedCapital),
            hint: labels.activePositions(overview.positions_count),
          },
          {
            label: labels.cashReserve,
            value: currency.format(snapshot.cash),
            hint: percent.format(overview.cash_ratio),
          },
          {
            label: labels.netDeposits,
            value: currency.format(snapshot.total_deposits),
            hint: labels.capitalBase,
          },
          {
            label: labels.deployment,
            value: percent.format(deploymentRatio),
            hint: labels.capitalAtWork,
          },
        ]
      : [
          {
            label: labels.unrealizedPnl,
            value: currency.format(overview.unrealized_pnl),
            hint: labels.openPositions,
          },
          {
            label: labels.realizedPnl,
            value: currency.format(overview.realized_pnl),
            hint: labels.closedActivity,
          },
          {
            label: labels.totalPnl,
            value: currency.format(totalPnl),
            hint: labels.totalPnlHint,
          },
          {
            label: labels.payoutBuffer,
            value: currency.format(snapshot.cash),
            hint: labels.payoutBufferHint,
          },
        ];

  return (
    <div className="app-surface-card p-5 sm:p-6">
      <div className="app-card-header items-end">
        <div className="app-card-title">
          {mode === "account" ? labels.accountTitle : labels.strategyTitle}
        </div>
        <div className="app-inline-segmented">
          {[
            { value: "account", label: accountLabel },
            { value: "strategy", label: strategyLabel },
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onModeChange(item.value as BreakdownMode)}
              className={`app-inline-segmented-btn ${
                mode === item.value ? "app-inline-segmented-btn-active" : ""
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item, index) => (
          <div
            key={item.label}
            className={`app-surface-metric-row sm:px-2 ${
              index > 1 ? "app-surface-metric-row-divider" : ""
            }`}
          >
            <div className="app-kicker text-xs uppercase tracking-[0.16em]">
              {item.label}
            </div>
            <div className="mt-3 text-xl font-semibold">{item.value}</div>
            <div className="app-muted mt-2 text-sm">{item.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
