import { useMemo, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatTimestamp } from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import type { LedgerEntry } from '../api';
import {
  formatLedgerActivitySummary,
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  formatLedgerPublicNote,
  formatLedgerSourceLabel,
  type LedgerActivitySummaryTone,
} from '../ledger-format';

type LedgerEntryCategory =
  'all' | 'trade' | 'cash' | 'dividend' | 'adjustment' | 'other';

type LedgerSubcategory =
  | 'all'
  | 'stock'
  | 'fund'
  | 'cashAccount'
  | 'otherAsset'
  | 'cashDeposit'
  | 'cashWithdrawal'
  | 'cashInterest'
  | 'otherCash';

type SpecificLedgerSubcategory = Exclude<LedgerSubcategory, 'all'>;

const LEDGER_ENTRY_CATEGORIES: LedgerEntryCategory[] = [
  'all',
  'trade',
  'cash',
  'dividend',
  'adjustment',
  'other',
];

const ACTIVITY_PAGE_SIZE = 8;

const LEDGER_SUBCATEGORIES_BY_CATEGORY: Partial<
  Record<LedgerEntryCategory, SpecificLedgerSubcategory[]>
> = {
  trade: ['stock', 'fund', 'otherAsset'],
  cash: ['cashDeposit', 'cashWithdrawal', 'cashInterest', 'otherCash'],
  dividend: ['stock', 'fund', 'otherAsset'],
  adjustment: ['stock', 'fund', 'cashAccount', 'otherAsset'],
};

export function ActivityFeedLoading() {
  const copy = useCopy();
  const labels = copy.activity.feed;

  return (
    <section
      aria-busy="true"
      aria-live="polite"
      className="app-workbench-section min-w-0 overflow-hidden"
      data-testid="activity-history-loading"
    >
      <span className="sr-only">{copy.activity.loading}</span>
      <div className="flex flex-wrap items-start justify-between gap-3 px-3 py-4 sm:px-5">
        <div>
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="app-type-section-title mt-2">{labels.title}</h2>
        </div>
        <span
          aria-hidden="true"
          className="block h-6 w-14 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse"
        />
      </div>
      <div
        aria-hidden="true"
        className="border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-3 sm:px-5"
      >
        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
          {[4.5, 3.5, 4, 3.5, 4.5].map((width, index) => (
            <span
              key={index}
              className="block h-8 shrink-0 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse"
              style={{ width: `${width}rem` }}
            />
          ))}
          <span className="ml-auto hidden h-8 w-52 shrink-0 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse lg:block" />
        </div>
      </div>
      <div
        aria-hidden="true"
        className="min-w-0 max-w-full overflow-auto overscroll-contain"
      >
        <table className="app-data-table w-full min-w-[760px] text-left text-sm">
          <thead>
            <tr>
              <th className="px-4 py-2.5">{labels.columns.time}</th>
              <th className="px-4 py-2.5">{labels.columns.activity}</th>
              <th className="px-4 py-2.5">{labels.columns.instrument}</th>
              <th className="px-4 py-2.5 text-right">
                {labels.columns.amount}
              </th>
              <th className="px-4 py-2.5">{labels.columns.detail}</th>
            </tr>
          </thead>
          <tbody data-testid="activity-history-loading-rows">
            {Array.from({ length: 4 }, (_, index) => (
              <tr key={index}>
                <td className="w-[9.5rem] px-4 py-3">
                  <span className="block h-3 w-24 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                </td>
                <td className="w-[10rem] px-4 py-3">
                  <span className="block h-3 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                </td>
                <td className="px-4 py-3">
                  <span className="block h-3 w-32 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                </td>
                <td className="w-36 px-4 py-3">
                  <span className="ml-auto block h-3 w-16 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                </td>
                <td className="px-4 py-3">
                  <span className="block h-3 w-40 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ActivityFeed({ entries }: { entries: LedgerEntry[] }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.activity.feed;
  const [selectedCategory, setSelectedCategory] =
    useState<LedgerEntryCategory>('all');
  const [selectedSubcategory, setSelectedSubcategory] =
    useState<LedgerSubcategory>('all');
  const [query, setQuery] = useState('');
  const [visibleEntryCount, setVisibleEntryCount] =
    useState(ACTIVITY_PAGE_SIZE);
  const normalizedQuery = query.trim().toLowerCase();
  const categorizedEntries = useMemo(
    () =>
      entries.map((entry) => ({
        entry,
        category: classifyLedgerEntry(entry),
      })),
    [entries],
  );
  const categoryCounts = useMemo(() => {
    const counts = new Map<LedgerEntryCategory, number>();
    for (const category of LEDGER_ENTRY_CATEGORIES) {
      counts.set(category, category === 'all' ? entries.length : 0);
    }
    for (const item of categorizedEntries) {
      counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
    }
    return counts;
  }, [categorizedEntries, entries.length]);
  const subcategoryOptions = useMemo(() => {
    if (selectedCategory === 'all') {
      return [];
    }
    const selectedCategoryEntries = categorizedEntries.filter(
      (item) => item.category === selectedCategory,
    );
    if (selectedCategoryEntries.length === 0) {
      return [];
    }
    const counts = new Map<SpecificLedgerSubcategory, number>();
    for (const item of categorizedEntries) {
      if (item.category !== selectedCategory) {
        continue;
      }
      const subcategory = classifyLedgerSubcategory(
        item.entry,
        selectedCategory,
      );
      counts.set(subcategory, (counts.get(subcategory) ?? 0) + 1);
    }

    const configuredSubcategories =
      LEDGER_SUBCATEGORIES_BY_CATEGORY[selectedCategory] ?? [];
    return [
      {
        key: 'all' as LedgerSubcategory,
        label: labels.subcategoryAllLabels[selectedCategory],
        count: selectedCategoryEntries.length,
      },
      ...configuredSubcategories
        .map((subcategory) => ({
          key: subcategory as LedgerSubcategory,
          label: labels.subcategoryLabels[subcategory],
          count: counts.get(subcategory) ?? 0,
        }))
        .filter((option) => option.count > 0),
    ];
  }, [categorizedEntries, labels, selectedCategory]);
  const effectiveSubcategory = subcategoryOptions.some(
    (option) => option.key === selectedSubcategory,
  )
    ? selectedSubcategory
    : 'all';
  const filteredEntries =
    selectedCategory === 'all' && normalizedQuery === ''
      ? entries
      : categorizedEntries
          .filter((item) => {
            const matchesCategory =
              selectedCategory === 'all' || item.category === selectedCategory;
            const matchesSubcategory =
              selectedCategory === 'all' ||
              effectiveSubcategory === 'all' ||
              classifyLedgerSubcategory(item.entry, selectedCategory) ===
                effectiveSubcategory;
            return (
              matchesCategory &&
              matchesSubcategory &&
              ledgerEntryMatchesQuery(item.entry, normalizedQuery)
            );
          })
          .map((item) => item.entry);
  const visibleEntries = filteredEntries.slice(0, visibleEntryCount);
  const remainingEntryCount = Math.max(
    filteredEntries.length - visibleEntries.length,
    0,
  );

  if (entries.length === 0) {
    return (
      <div
        className="app-workbench-section p-5 text-sm app-muted"
        data-testid="activity-history-empty"
      >
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="app-workbench-section min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-3 py-4 sm:px-5">
        <div>
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="app-type-section-title mt-2">{labels.title}</h2>
        </div>
        <span className="app-chip px-2.5 py-1 text-xs font-semibold">
          {labels.count(filteredEntries.length)}
        </span>
      </div>
      <div className="border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-3 sm:px-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div
            aria-label={labels.categoryFilter}
            className="app-activity-filter-rail app-horizontal-scroll-cue flex min-w-0 max-w-full flex-nowrap gap-1.5 overflow-x-auto overscroll-x-contain pb-1 sm:flex-wrap sm:overflow-visible sm:pb-0"
            role="group"
          >
            {LEDGER_ENTRY_CATEGORIES.map((category) => {
              const count = categoryCounts.get(category) ?? 0;
              const isSelected = selectedCategory === category;
              return (
                <button
                  key={category}
                  aria-label={`${labels.categoryLabels[category]} ${labels.count(count)}`}
                  aria-pressed={isSelected}
                  className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-[var(--app-radius-control)] border px-2.5 py-1.5 text-xs font-semibold transition-colors xl:min-h-8 ${
                    isSelected
                      ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-strong)]'
                      : 'border-transparent bg-transparent text-[var(--app-muted)] hover:border-[var(--app-border)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] hover:text-[var(--app-soft)]'
                  }`}
                  onClick={() => {
                    setSelectedCategory(category);
                    setSelectedSubcategory('all');
                    setVisibleEntryCount(ACTIVITY_PAGE_SIZE);
                  }}
                  type="button"
                >
                  <span>{labels.categoryLabels[category]}</span>
                  <span
                    aria-hidden="true"
                    className="app-type-micro font-mono tabular-nums"
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
          <label className="min-w-0 lg:w-[260px]">
            <span className="sr-only">{labels.searchLabel}</span>
            <input
              aria-label={labels.searchLabel}
              className="app-field h-9 w-full rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
              onChange={(event) => {
                setQuery(event.target.value);
                setVisibleEntryCount(ACTIVITY_PAGE_SIZE);
              }}
              placeholder={labels.searchPlaceholder}
              type="search"
              value={query}
            />
          </label>
        </div>
        {subcategoryOptions.length > 1 ? (
          <div
            aria-label={labels.subcategoryFilter}
            className="app-activity-filter-rail app-horizontal-scroll-cue mt-3 flex min-w-0 max-w-full flex-nowrap gap-1.5 overflow-x-auto overscroll-x-contain pb-1 sm:flex-wrap sm:overflow-visible sm:pb-0"
            role="group"
          >
            {subcategoryOptions.map((option) => {
              const isSelected = effectiveSubcategory === option.key;
              return (
                <button
                  key={option.key}
                  aria-label={`${option.label} ${labels.count(option.count)}`}
                  aria-pressed={isSelected}
                  className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-[var(--app-radius-control)] border px-2.5 py-1.5 text-xs font-semibold transition-colors xl:min-h-8 ${
                    isSelected
                      ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-strong)]'
                      : 'border-transparent bg-transparent text-[var(--app-muted)] hover:border-[var(--app-border)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] hover:text-[var(--app-soft)]'
                  }`}
                  onClick={() => {
                    setSelectedSubcategory(option.key);
                    setVisibleEntryCount(ACTIVITY_PAGE_SIZE);
                  }}
                  type="button"
                >
                  <span>{option.label}</span>
                  <span
                    aria-hidden="true"
                    className="app-type-micro font-mono tabular-nums"
                  >
                    {option.count}
                  </span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
      <div
        aria-label={labels.title}
        className="min-w-0 max-w-full"
        role="region"
      >
        {visibleEntries.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-[var(--app-muted)]">
            {labels.filteredEmpty}
          </div>
        ) : (
          <div
            className="min-w-0 max-w-full md:overflow-x-auto md:overscroll-x-contain"
            data-testid="activity-history-table-scroll"
          >
            <table
              aria-label={labels.tableScrollLabel}
              className="app-data-table block w-full min-w-0 text-left text-sm md:table md:min-w-[760px]"
              data-testid="activity-history-table"
            >
              <thead className="hidden md:table-header-group">
                <tr>
                  <th className="px-4 py-2.5">{labels.columns.time}</th>
                  <th className="px-4 py-2.5">{labels.columns.activity}</th>
                  <th className="px-4 py-2.5">{labels.columns.instrument}</th>
                  <th className="px-4 py-2.5 text-right">
                    {labels.columns.amount}
                  </th>
                  <th className="px-4 py-2.5">{labels.columns.detail}</th>
                </tr>
              </thead>
              <tbody
                className="block divide-y divide-[color-mix(in_srgb,var(--app-border)_24%,transparent)] md:table-row-group"
                data-testid="activity-history-rows"
              >
                {visibleEntries.map((entry) => {
                  const summary = formatLedgerActivitySummary(entry, locale);
                  const publicNote =
                    formatLedgerPublicNote(entry, locale) ?? labels.noDetail;
                  return (
                    <tr
                      key={entry.id}
                      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-3 px-3 py-4 md:table-row md:p-0"
                    >
                      <td className="col-start-2 row-start-2 block p-0 text-right align-top md:table-cell md:px-4 md:py-3 md:text-left">
                        <div className="font-mono text-xs font-semibold text-[var(--app-soft)]">
                          {formatTimestamp(entry.timestamp)}
                        </div>
                        <div className="app-muted app-type-micro mt-1">
                          {formatLedgerSourceLabel(entry.source, locale)}
                        </div>
                      </td>
                      <td className="col-start-1 row-start-1 block p-0 align-top md:table-cell md:px-4 md:py-3">
                        <div className="flex items-center gap-2.5">
                          <span
                            className={`app-type-micro inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] font-bold ${activityBadgeClass(summary.tone)}`}
                          >
                            {summary.shortLabel}
                          </span>
                          <div>
                            <div className="font-semibold">{summary.label}</div>
                            <div className="app-muted mt-1 text-xs">
                              {summary.cashImpactLabel}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="col-start-1 row-start-2 block min-w-0 p-0 align-top md:table-cell md:px-4 md:py-3">
                        <ActivityInstrument
                          copy={copy}
                          entry={entry}
                          labels={labels}
                          locale={locale}
                        />
                      </td>
                      <td
                        className={`col-start-2 row-start-1 block p-0 text-right align-top font-mono text-sm font-semibold tabular-nums md:table-cell md:px-4 md:py-3 ${activityAmountClass(summary.tone)}`}
                      >
                        {summary.amount}
                        <LedgerExecutionDetails
                          entry={entry}
                          labels={labels}
                          locale={locale}
                        />
                      </td>
                      <td className="col-span-2 row-start-3 block min-w-0 max-w-none p-0 align-top text-[var(--app-muted)] md:table-cell md:max-w-[280px] md:px-4 md:py-3">
                        <span
                          className="block break-words [overflow-wrap:anywhere]"
                          data-testid="activity-note"
                        >
                          {publicNote}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {visibleEntries.length > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-3 sm:px-5">
            <span
              aria-live="polite"
              className="app-muted text-xs font-semibold"
              data-testid="activity-history-progress"
            >
              {labels.showing(visibleEntries.length, filteredEntries.length)}
            </span>
            {remainingEntryCount > 0 ? (
              <button
                className="app-button-secondary min-h-11 px-4 text-sm"
                data-testid="activity-history-show-more"
                onClick={() =>
                  setVisibleEntryCount((count) =>
                    Math.min(
                      count + ACTIVITY_PAGE_SIZE,
                      filteredEntries.length,
                    ),
                  )
                }
                type="button"
              >
                {labels.showMore(
                  Math.min(ACTIVITY_PAGE_SIZE, remainingEntryCount),
                )}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ActivityInstrument({
  copy,
  entry,
  labels,
  locale,
}: {
  copy: ReturnType<typeof useCopy>;
  entry: LedgerEntry;
  labels: ReturnType<typeof useCopy>['activity']['feed'];
  locale: ReturnType<typeof usePreferences>['locale'];
}) {
  return (
    <div className="min-w-0">
      {entry.symbol ? (
        <a
          href={`/portfolio/${encodeURIComponent(entry.symbol)}`}
          className="break-words font-semibold text-[var(--app-text)] underline-offset-4 transition-colors hover:text-[var(--app-accent)] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
          aria-label={labels.openHoldingDetail(entry.symbol)}
        >
          {formatLedgerInstrumentLabel(entry, locale) || entry.symbol}
        </a>
      ) : (
        <div className="font-semibold">--</div>
      )}
      <div className="app-muted mt-1 flex items-center gap-2 text-xs">
        <span className="app-type-overline rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2 py-0.5">
          {formatAssetClass(entry.asset_class, copy)}
        </span>
      </div>
    </div>
  );
}

function activityAmountClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'text-[var(--app-pnl-positive)]';
  }
  if (tone === 'debit') {
    return 'text-[var(--app-pnl-negative)]';
  }
  return 'text-[var(--app-pnl-neutral)]';
}

function activityBadgeClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'bg-[color-mix(in_srgb,var(--app-pnl-positive)_10%,transparent)] text-[var(--app-pnl-positive)] ring-1 ring-[color-mix(in_srgb,var(--app-pnl-positive)_38%,transparent)]';
  }
  if (tone === 'debit') {
    return 'bg-[color-mix(in_srgb,var(--app-pnl-negative)_10%,transparent)] text-[var(--app-pnl-negative)] ring-1 ring-[color-mix(in_srgb,var(--app-pnl-negative)_38%,transparent)]';
  }
  return 'bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-soft)] ring-1 ring-[color-mix(in_srgb,var(--app-border)_34%,transparent)]';
}

function LedgerExecutionDetails({
  entry,
  labels,
  locale,
}: {
  entry: LedgerEntry;
  labels: ReturnType<typeof useCopy>['activity']['feed'];
  locale: ReturnType<typeof usePreferences>['locale'];
}) {
  const details = formatLedgerExecutionDetailLines(
    entry,
    labels.detailFields,
    locale,
  );

  if (details.length === 0) {
    return <div className="app-muted app-type-micro mt-1">--</div>;
  }

  return (
    <div className="app-muted app-type-label mt-1 ml-auto flex max-w-[240px] flex-wrap items-center justify-end gap-x-2 gap-y-0.5">
      {details.map((item) => (
        <span key={item.label} className="whitespace-nowrap">
          {item.label} {item.value}
        </span>
      ))}
    </div>
  );
}

function formatAssetClass(
  assetClass: string,
  copy: ReturnType<typeof useCopy>,
) {
  return formatAssetClassLabel(assetClass, copy.common);
}

function classifyLedgerEntry(entry: LedgerEntry): LedgerEntryCategory {
  const entryType = entry.entry_type.toLowerCase();
  const assetClass = entry.asset_class.toLowerCase();
  const direction = entry.direction?.toLowerCase() ?? '';

  if (
    entryType.includes('trade') ||
    direction === 'buy' ||
    direction === 'sell'
  ) {
    return 'trade';
  }
  if (entryType.includes('dividend')) {
    return 'dividend';
  }
  if (entryType.includes('adjust')) {
    return 'adjustment';
  }
  if (
    assetClass === 'cash' ||
    entryType.includes('cash') ||
    entryType.includes('deposit') ||
    entryType.includes('withdraw')
  ) {
    return 'cash';
  }
  return 'other';
}

function classifyLedgerSubcategory(
  entry: LedgerEntry,
  category: LedgerEntryCategory,
): SpecificLedgerSubcategory {
  if (category === 'cash') {
    return classifyCashLedgerSubcategory(entry);
  }
  return classifyLedgerAssetSubcategory(entry, category === 'adjustment');
}

function classifyLedgerAssetSubcategory(
  entry: LedgerEntry,
  includeCash: boolean,
): SpecificLedgerSubcategory {
  const assetClass = entry.asset_class.toLowerCase();

  if (assetClass === 'stock') {
    return 'stock';
  }
  if (assetClass === 'fund' || assetClass === 'etf') {
    return 'fund';
  }
  if (includeCash && assetClass === 'cash') {
    return 'cashAccount';
  }
  return 'otherAsset';
}

function classifyCashLedgerSubcategory(
  entry: LedgerEntry,
): SpecificLedgerSubcategory {
  const entryType = entry.entry_type.toLowerCase();

  if (entryType.includes('interest')) {
    return 'cashInterest';
  }
  if (entryType.includes('deposit')) {
    return 'cashDeposit';
  }
  if (entryType.includes('withdraw')) {
    return 'cashWithdrawal';
  }
  return 'otherCash';
}

function ledgerEntryMatchesQuery(entry: LedgerEntry, normalizedQuery: string) {
  if (normalizedQuery === '') {
    return true;
  }

  const searchableText = [
    entry.display_name,
    entry.symbol,
    entry.entry_type,
    entry.asset_class,
    entry.direction,
    entry.note,
    entry.source,
    entry.source_ref,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  return searchableText.includes(normalizedQuery);
}
