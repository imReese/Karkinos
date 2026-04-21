import { useCopy } from "../../../app/copy";

type WorkspaceMode = "account" | "strategy";
type PnlFilter = "all" | "winners" | "losers";

export function WorkspaceToolbar({
  mode,
  onModeChange,
  search,
  onSearchChange,
  assetClassFilter,
  onAssetClassFilterChange,
  pnlFilter,
  onPnlFilterChange,
  assetClasses,
}: {
  mode: WorkspaceMode;
  onModeChange: (mode: WorkspaceMode) => void;
  search: string;
  onSearchChange: (value: string) => void;
  assetClassFilter: string;
  onAssetClassFilterChange: (value: string) => void;
  pnlFilter: PnlFilter;
  onPnlFilterChange: (value: PnlFilter) => void;
  assetClasses: string[];
}) {
  const copy = useCopy();
  const labels = copy.portfolio.toolbar;

  return (
    <div className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,1fr))]">
        <div className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.view}
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              { value: "account", label: copy.mode.accountShort },
              { value: "strategy", label: copy.mode.strategyShort },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => onModeChange(item.value as WorkspaceMode)}
                className={`rounded-xl px-3 py-2 text-sm transition sm:px-4 ${
                  mode === item.value ? "app-button-primary" : "app-button-secondary"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="app-muted text-sm">{labels.helper}</div>
        </div>

        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.search}
          </div>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={labels.searchPlaceholder}
            className="app-field w-full rounded-xl px-3 py-2 text-sm"
          />
        </label>

        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.assetClass}
          </div>
          <select
            value={assetClassFilter}
            onChange={(event) => onAssetClassFilterChange(event.target.value)}
            className="app-field w-full rounded-xl px-3 py-2 text-sm"
          >
            <option value="all">{labels.allAssetClasses}</option>
            {assetClasses.map((assetClass) => (
              <option key={assetClass} value={assetClass}>
                {assetClass}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.pnlFocus}
          </div>
          <select
            value={pnlFilter}
            onChange={(event) => onPnlFilterChange(event.target.value as PnlFilter)}
            className="app-field w-full rounded-xl px-3 py-2 text-sm"
          >
            <option value="all">{labels.allHoldings}</option>
            <option value="winners">{labels.winnersOnly}</option>
            <option value="losers">{labels.losersOnly}</option>
          </select>
        </label>
      </div>
    </div>
  );
}
