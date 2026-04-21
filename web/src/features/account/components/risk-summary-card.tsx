import { useCopy } from "../../../app/copy";
import type { AccountOverview } from "../api";
import type { PortfolioSnapshot } from "../../portfolio/api";

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function RiskSummaryCard({
  overview,
  snapshot,
}: {
  overview: AccountOverview;
  snapshot: PortfolioSnapshot;
}) {
  const copy = useCopy();
  const labels = copy.overview.risk;
  const topHoldingWeight = Math.max(...snapshot.allocation.map((item) => item.weight), 0);
  const deploymentRatio =
    snapshot.total_equity > 0
      ? Math.max(snapshot.total_equity - snapshot.cash, 0) / snapshot.total_equity
      : 0;

  const items = [
    {
      label: labels.concentration,
      value: percent.format(topHoldingWeight),
      hint: snapshot.allocation[0]?.name ?? "--",
    },
    {
      label: labels.cashBuffer,
      value: percent.format(overview.cash_ratio),
      hint: overview.cash_ratio >= 0.2 ? labels.cashHealthy : labels.cashWatch,
    },
    {
      label: labels.deployment,
      value: percent.format(deploymentRatio),
      hint: deploymentRatio >= 0.8 ? labels.deploymentHigh : labels.deploymentBalanced,
    },
    {
      label: labels.positions,
      value: String(overview.positions_count),
      hint: labels.positionsHint(overview.positions_count),
    },
  ];

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="app-kicker mb-4 text-xs uppercase tracking-[0.18em]">
        {labels.title}
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
