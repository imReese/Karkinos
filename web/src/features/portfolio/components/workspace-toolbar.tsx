import { useCopy } from '../../../app/copy';
import { FilterBar } from '../../../app/components/workbench';
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
  summary,
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
  summary?: string;
}) {
  const copy = useCopy();
  const labels = copy.portfolio.toolbar;
  const fieldClassName =
    'app-field h-8 rounded-[var(--app-radius-control)] px-2 text-xs';

  return (
    <FilterBar label={labels.helper}>
      <div className="grid w-full min-w-0 gap-2 md:grid-cols-[auto_minmax(180px,1fr)_auto] md:items-center">
        <div
          className="inline-flex h-8 overflow-hidden rounded-[var(--app-radius-control)] border border-[var(--app-border)]"
          aria-label={labels.view}
        >
          {[
            { value: 'account', label: copy.mode.accountShort },
            { value: 'strategy', label: copy.mode.strategyShort },
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={mode === item.value}
              onClick={() => onModeChange(item.value as WorkspaceMode)}
              className={`px-3 text-xs font-semibold ${
                mode === item.value
                  ? 'bg-[var(--app-accent)] text-[var(--app-text-inverse)]'
                  : 'bg-transparent text-[var(--app-text-secondary)] hover:bg-[var(--app-accent-bg)]'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <label className="min-w-0">
          <span className="sr-only">{labels.search}</span>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={labels.searchPlaceholder}
            className={`${fieldClassName} w-full`}
          />
        </label>

        {summary ? (
          <div className="text-xs text-[var(--app-text-tertiary)] tabular-nums md:text-right">
            {summary}
          </div>
        ) : null}

        <div className="flex min-w-0 flex-wrap items-center gap-2 md:col-span-3">
          <label>
            <span className="sr-only">{labels.assetClass}</span>
            <select
              aria-label={labels.assetClass}
              value={assetClassFilter}
              onChange={(event) => onAssetClassFilterChange(event.target.value)}
              className={fieldClassName}
            >
              <option value="all">{labels.allAssetClasses}</option>
              {assetClasses.map((assetClass) => (
                <option key={assetClass} value={assetClass}>
                  {formatAssetClassLabel(assetClass, copy.common)}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span className="sr-only">{labels.pnlFocus}</span>
            <select
              aria-label={labels.pnlFocus}
              value={pnlFilter}
              onChange={(event) =>
                onPnlFilterChange(event.target.value as PnlFilter)
              }
              className={fieldClassName}
            >
              <option value="all">{labels.allHoldings}</option>
              <option value="winners">{labels.winnersOnly}</option>
              <option value="losers">{labels.losersOnly}</option>
            </select>
          </label>

          <label>
            <span className="sr-only">{labels.quoteFilter}</span>
            <select
              aria-label={labels.quoteFilter}
              value={quoteFilter}
              onChange={(event) =>
                onQuoteFilterChange?.(event.target.value as QuoteFilter)
              }
              className={fieldClassName}
            >
              <option value="all">{labels.allQuoteStates}</option>
              <option value="healthy">{labels.healthyQuotes}</option>
              <option value="review">{labels.reviewQuotes}</option>
            </select>
          </label>

          <label>
            <span className="sr-only">{labels.evidenceFilter}</span>
            <select
              aria-label={labels.evidenceFilter}
              value={evidenceFilter}
              onChange={(event) =>
                onEvidenceFilterChange?.(event.target.value as EvidenceFilter)
              }
              className={fieldClassName}
            >
              <option value="all">{labels.allEvidenceStates}</option>
              <option value="review">{labels.evidenceReviewOnly}</option>
              <option value="clear">{labels.evidenceClearOnly}</option>
            </select>
          </label>

          <label>
            <span className="sr-only">{labels.sortBy}</span>
            <select
              aria-label={labels.sortBy}
              value={sortBy}
              onChange={(event) =>
                onSortByChange?.(event.target.value as PositionSort)
              }
              className={fieldClassName}
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
    </FilterBar>
  );
}
