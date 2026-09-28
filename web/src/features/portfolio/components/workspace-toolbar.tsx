import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

import { useCopy } from '../../../shared/i18n/context';
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

function ToolbarSelect<T extends string>({
  'aria-label': ariaLabel,
  value,
  onChange,
  options,
  className,
}: {
  'aria-label': string;
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  className?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedOption =
    options.find((opt) => opt.value === value) ?? options[0];
  const displayLabel = selectedOption?.label ?? value;

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  return (
    <div ref={containerRef} className="relative inline-block">
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="sr-only"
        tabIndex={-1}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className={`app-field inline-flex h-10 items-center justify-between gap-1.5 rounded-[var(--app-radius-control)] pl-2.5 pr-2 text-xs sm:h-8 cursor-pointer bg-[var(--app-surface-raised)] text-[var(--app-text)] hover:border-[var(--app-border)] focus:border-[var(--app-focus-ring)] focus:outline-none ${className ?? ''}`}
      >
        <span className="truncate">{displayLabel}</span>
        <ChevronDown
          size={13}
          className={`shrink-0 text-[var(--app-text-tertiary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] ${
            isOpen ? 'rotate-180' : ''
          }`}
          aria-hidden="true"
        />
      </button>

      {isOpen ? (
        <div
          role="listbox"
          aria-label={ariaLabel}
          className="absolute left-0 top-full z-50 mt-1 min-w-full w-max max-w-xs rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-1 shadow-lg"
        >
          {options.map((opt) => {
            const isSelected = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  onChange(opt.value);
                  setIsOpen(false);
                }}
                className={`flex w-full items-center justify-between gap-3 rounded-[calc(var(--app-radius-control)-2px)] px-2.5 py-1.5 text-xs text-left transition-colors cursor-pointer ${
                  isSelected
                    ? 'bg-[var(--app-accent-bg)] font-semibold text-[var(--app-accent)]'
                    : 'text-[var(--app-text)] hover:bg-[var(--app-surface)]'
                }`}
              >
                <span className="truncate">{opt.label}</span>
                {isSelected ? (
                  <Check
                    size={13}
                    className="shrink-0 text-[var(--app-accent)]"
                    aria-hidden="true"
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

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
  const inputClassName =
    'app-field h-10 rounded-[var(--app-radius-control)] px-3 text-xs sm:h-8';

  return (
    <FilterBar label={labels.helper}>
      <div className="grid w-full min-w-0 gap-2 md:grid-cols-[minmax(220px,1fr)_auto] md:items-center">
        <label className="min-w-0">
          <span className="sr-only">{labels.search}</span>
          <input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={labels.searchPlaceholder}
            className={`${inputClassName} w-full`}
          />
        </label>

        {summary ? (
          <div className="text-xs text-[var(--app-text-tertiary)] tabular-nums md:text-right">
            {summary}
          </div>
        ) : null}

        <div className="flex min-w-0 flex-wrap items-center gap-2 md:col-span-2">
          <ToolbarSelect
            aria-label={labels.assetClass}
            value={assetClassFilter}
            onChange={onAssetClassFilterChange}
            options={[
              { value: 'all', label: labels.allAssetClasses },
              ...assetClasses.map((assetClass) => ({
                value: assetClass,
                label: formatAssetClassLabel(assetClass, copy.common),
              })),
            ]}
          />

          <ToolbarSelect
            aria-label={labels.pnlFocus}
            value={pnlFilter}
            onChange={onPnlFilterChange}
            options={[
              { value: 'all', label: labels.allHoldings },
              { value: 'winners', label: labels.winnersOnly },
              { value: 'losers', label: labels.losersOnly },
            ]}
          />

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
            <ToolbarSelect
              aria-label={labels.quoteFilter}
              value={quoteFilter}
              onChange={(value) => onQuoteFilterChange?.(value as QuoteFilter)}
              options={[
                { value: 'all', label: labels.allQuoteStates },
                { value: 'healthy', label: labels.healthyQuotes },
                { value: 'review', label: labels.reviewQuotes },
              ]}
            />

            <ToolbarSelect
              aria-label={labels.evidenceFilter}
              value={evidenceFilter}
              onChange={(value) =>
                onEvidenceFilterChange?.(value as EvidenceFilter)
              }
              options={[
                { value: 'all', label: labels.allEvidenceStates },
                { value: 'review', label: labels.evidenceReviewOnly },
                { value: 'clear', label: labels.evidenceClearOnly },
              ]}
            />

            <ToolbarSelect
              aria-label={labels.sortBy}
              value={sortBy}
              onChange={(value) => onSortByChange?.(value as PositionSort)}
              options={[
                { value: 'market_value', label: labels.sortMarketValue },
                { value: 'weight', label: labels.sortWeight },
                { value: 'today_change', label: labels.sortTodayPnl },
                {
                  value: 'unrealized_pnl',
                  label: labels.sortUnrealizedPnl,
                },
                { value: 'realized_pnl', label: labels.sortRealizedPnl },
              ]}
            />
          </div>
        </div>
      </div>
    </FilterBar>
  );
}
