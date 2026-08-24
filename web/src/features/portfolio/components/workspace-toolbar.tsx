import { useState } from 'react';

import { useCopy } from '../../../app/copy';
import { FilterBar } from '../../../shared/ui/workbench';
import { formatAssetClassLabel } from '../../../shared/asset-class';

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
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const activeSecondaryFilterCount = [
    quoteFilter !== 'all',
    evidenceFilter !== 'all',
    sortBy !== 'market_value',
  ].filter(Boolean).length;
  const moreFiltersLabel = showMoreFilters
    ? labels.hideMoreFilters
    : labels.showMoreFilters;
  const moreFiltersAccessibleLabel = activeSecondaryFilterCount
    ? `${moreFiltersLabel} · ${labels.activeFilters(activeSecondaryFilterCount)}`
    : moreFiltersLabel;
  const fieldClassName =
    'app-field h-10 rounded-[var(--app-radius-control)] px-2 text-xs sm:h-8';

  return (
    <FilterBar label={labels.helper}>
      <div className="grid w-full min-w-0 gap-2 md:grid-cols-[minmax(220px,1fr)_auto] md:items-center">
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

        <div className="flex min-w-0 flex-wrap items-center gap-2 md:col-span-2">
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

          <button
            type="button"
            className="app-button-secondary inline-flex min-h-10 items-center gap-1.5 rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold md:hidden"
            aria-expanded={showMoreFilters}
            aria-controls="portfolio-secondary-filters"
            aria-label={moreFiltersAccessibleLabel}
            onClick={() => setShowMoreFilters((current) => !current)}
          >
            <span>{moreFiltersLabel}</span>
            {activeSecondaryFilterCount > 0 ? (
              <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-[var(--app-accent-bg)] px-1.5 text-[length:var(--app-font-size-micro)] tabular-nums text-[var(--app-accent)]">
                {activeSecondaryFilterCount}
              </span>
            ) : null}
          </button>

          <div
            id="portfolio-secondary-filters"
            data-testid="portfolio-secondary-filters"
            className={showMoreFilters ? 'contents' : 'hidden md:contents'}
          >
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
                <option value="unrealized_pnl">
                  {labels.sortUnrealizedPnl}
                </option>
                <option value="realized_pnl">{labels.sortRealizedPnl}</option>
              </select>
            </label>
          </div>
        </div>
      </div>
    </FilterBar>
  );
}
