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
}: {
  overview: AccountOverview;
  snapshot: PortfolioSnapshot;
  mode: BreakdownMode;
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
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="app-card-header">
        <div className="app-card-title">
          {mode === "account" ? labels.accountTitle : labels.strategyTitle}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <div key={item.label} className="app-panel-strong rounded-2xl px-4 py-4">
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
