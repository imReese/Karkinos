import { useCopy } from '../../../app/copy';
import { formatAssetClassLabel } from '../../../shared/asset-class';

type WorkspaceMode = 'account' | 'strategy';
type PnlFilter = 'all' | 'winners' | 'losers';
export type QuoteFilter = 'all' | 'healthy' | 'review';
export type EvidenceFilter = 'all' | 'review' | 'clear';
export type PositionSort =
  | 'market_value'
  | 'weight'
  | 'today_change'
  | 'unrealized_pnl'
  | 'realized_pnl';

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
  quoteFilter = 'all',
  onQuoteFilterChange,
  evidenceFilter = 'all',
  onEvidenceFilterChange,
  sortBy = 'market_value',
  onSortByChange,
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
  quoteFilter?: QuoteFilter;
  onQuoteFilterChange?: (value: QuoteFilter) => void;
  evidenceFilter?: EvidenceFilter;
  onEvidenceFilterChange?: (value: EvidenceFilter) => void;
  sortBy?: PositionSort;
  onSortByChange?: (value: PositionSort) => void;
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
              { value: 'account', label: copy.mode.accountShort },
              { value: 'strategy', label: copy.mode.strategyShort },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => onModeChange(item.value as WorkspaceMode)}
                className={`rounded-2xl px-3 py-2 text-sm font-semibold transition sm:px-4 ${
                  mode === item.value
                    ? 'app-button-primary'
                    : 'app-button-secondary'
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
            className="app-field w-full rounded-2xl px-3 py-2 text-sm"
          />
        </label>

        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.assetClass}
          </div>
          <select
            value={assetClassFilter}
            onChange={(event) => onAssetClassFilterChange(event.target.value)}
            className="app-field w-full rounded-2xl px-3 py-2 text-sm"
          >
            <option value="all">{labels.allAssetClasses}</option>
            {assetClasses.map((assetClass) => (
              <option key={assetClass} value={assetClass}>
                {formatAssetClassLabel(assetClass, copy.common)}
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
            onChange={(event) =>
              onPnlFilterChange(event.target.value as PnlFilter)
            }
            className="app-field w-full rounded-2xl px-3 py-2 text-sm"
          >
            <option value="all">{labels.allHoldings}</option>
            <option value="winners">{labels.winnersOnly}</option>
            <option value="losers">{labels.losersOnly}</option>
          </select>
        </label>
      </div>
      <div className="mt-4 grid gap-4 border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] pt-4 sm:grid-cols-3">
        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.quoteFilter}
          </div>
          <select
            value={quoteFilter}
            onChange={(event) =>
              onQuoteFilterChange?.(event.target.value as QuoteFilter)
            }
            className="app-field w-full rounded-2xl px-3 py-2 text-sm"
          >
            <option value="all">{labels.allQuoteStates}</option>
            <option value="healthy">{labels.healthyQuotes}</option>
            <option value="review">{labels.reviewQuotes}</option>
          </select>
        </label>

        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.evidenceFilter}
          </div>
          <select
            value={evidenceFilter}
            onChange={(event) =>
              onEvidenceFilterChange?.(event.target.value as EvidenceFilter)
            }
            className="app-field w-full rounded-2xl px-3 py-2 text-sm"
          >
            <option value="all">{labels.allEvidenceStates}</option>
            <option value="review">{labels.evidenceReviewOnly}</option>
            <option value="clear">{labels.evidenceClearOnly}</option>
          </select>
        </label>

        <label className="space-y-2">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.sortBy}
          </div>
          <select
            value={sortBy}
            onChange={(event) =>
              onSortByChange?.(event.target.value as PositionSort)
            }
            className="app-field w-full rounded-2xl px-3 py-2 text-sm"
          >
            <option value="market_value">{labels.sortMarketValue}</option>
            <option value="weight">{labels.sortWeight}</option>
            <option value="today_change">{labels.sortTodayPnl}</option>
            <option value="unrealized_pnl">{labels.sortUnrealizedPnl}</option>
            <option value="realized_pnl">{labels.sortRealizedPnl}</option>
          </select>
        </label>
      </div>
    </div>
  );
}
