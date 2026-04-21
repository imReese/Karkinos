import { useCopy } from "../../../app/copy";
import type { LiveHoldingGroup } from "../../portfolio/api";

function formatCurrency(value: number) {
  const locale =
    typeof document !== "undefined" && document.documentElement.lang.startsWith("zh")
      ? "zh-CN"
      : "en-US";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2,
  }).format(value);
}

function toneClass(value: number) {
  if (value === 0) {
    return "text-[var(--app-foreground)]";
  }
  return value > 0 ? "app-positive" : "app-negative";
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
    case "stock":
      return labels.assetClassStock;
    case "etf":
      return labels.assetClassEtf;
    case "fund":
      return labels.assetClassFund;
    case "gold":
      return labels.assetClassGold;
    case "bond":
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
      <div className="app-panel rounded-2xl p-4 text-sm app-muted sm:p-5">
        <div className="app-card-title text-[var(--app-text)]">{labels.title}</div>
        <div className="mt-3">{labels.empty}</div>
      </div>
    );
  }

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="app-card-header">
        <div className="app-card-title">{labels.title}</div>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {groups.map((group) => (
          <button
            key={group.asset_class}
            type="button"
            onClick={() => onSelectAssetClass?.(group.asset_class)}
            className="app-panel-strong rounded-2xl px-4 py-4 text-left transition hover:border-[var(--app-border)]"
          >
            <div className="text-sm font-semibold">
              {assetClassLabel(group.asset_class, copy.common)}
            </div>
            <div className="mt-4 grid gap-3">
              <Metric label={labels.marketValue} value={formatCurrency(group.total_market_value)} />
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
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">{label}</div>
      <div className={`mt-2 text-sm font-semibold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}
