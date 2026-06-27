import { useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
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
  | 'all'
  | 'trade'
  | 'cash'
  | 'dividend'
  | 'adjustment'
  | 'other';

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

const LEDGER_SUBCATEGORIES_BY_CATEGORY: Partial<
  Record<LedgerEntryCategory, SpecificLedgerSubcategory[]>
> = {
  trade: ['stock', 'fund', 'otherAsset'],
  cash: ['cashDeposit', 'cashWithdrawal', 'cashInterest', 'otherCash'],
  dividend: ['stock', 'fund', 'otherAsset'],
  adjustment: ['stock', 'fund', 'cashAccount', 'otherAsset'],
};

export function ActivityFeed({ entries }: { entries: LedgerEntry[] }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.activity.feed;
  const [selectedCategory, setSelectedCategory] =
    useState<LedgerEntryCategory>('all');
  const [selectedSubcategory, setSelectedSubcategory] =
    useState<LedgerSubcategory>('all');
  const [query, setQuery] = useState('');
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
  const visibleEntries =
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

  if (entries.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-5 text-sm app-muted">
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="app-panel min-w-0 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div>
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="mt-2 text-base font-semibold">{labels.title}</h2>
        </div>
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-soft)]">
          {labels.count(visibleEntries.length)}
        </span>
      </div>
      <div className="border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-5 py-3">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div
            aria-label={labels.categoryFilter}
            className="flex min-w-0 flex-wrap gap-2"
            role="group"
          >
            {LEDGER_ENTRY_CATEGORIES.map((category) => {
              const count = categoryCounts.get(category) ?? 0;
              const isSelected = selectedCategory === category;
              return (
                <button
                  key={category}
                  aria-pressed={isSelected}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                    isSelected
                      ? 'border-[var(--app-accent)] bg-[var(--app-accent-bg)] text-[var(--app-accent-strong)] shadow-[0_0_0_1px_var(--app-accent-border)]'
                      : 'border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] text-[var(--app-muted)] hover:border-[var(--app-accent-border)] hover:text-[var(--app-soft)]'
                  }`}
                  onClick={() => {
                    setSelectedCategory(category);
                    setSelectedSubcategory('all');
                  }}
                  type="button"
                >
                  {labels.categoryLabels[category]} {labels.count(count)}
                </button>
              );
            })}
          </div>
          <label className="min-w-0 lg:w-[260px]">
            <span className="sr-only">{labels.searchLabel}</span>
            <input
              aria-label={labels.searchLabel}
              className="app-field h-9 w-full rounded-full px-3 text-xs font-semibold"
              onChange={(event) => setQuery(event.target.value)}
              placeholder={labels.searchPlaceholder}
              type="search"
              value={query}
            />
          </label>
        </div>
        {subcategoryOptions.length > 1 ? (
          <div
            aria-label={labels.subcategoryFilter}
            className="mt-3 flex min-w-0 flex-wrap gap-2"
            role="group"
          >
            {subcategoryOptions.map((option) => {
              const isSelected = effectiveSubcategory === option.key;
              return (
                <button
                  key={option.key}
                  aria-pressed={isSelected}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                    isSelected
                      ? 'border-[var(--app-accent)] bg-[var(--app-accent-bg)] text-[var(--app-accent-strong)] shadow-[0_0_0_1px_var(--app-accent-border)]'
                      : 'border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] text-[var(--app-muted)] hover:border-[var(--app-accent-border)] hover:text-[var(--app-soft)]'
                  }`}
                  onClick={() => setSelectedSubcategory(option.key)}
                  type="button"
                >
                  {option.label} {labels.count(option.count)}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
      <div className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
        <table className="app-data-table w-full min-w-[820px] text-left text-sm">
          <thead>
            <tr>
              <th className="px-5 py-3">{labels.columns.time}</th>
              <th className="px-5 py-3">{labels.columns.activity}</th>
              <th className="px-5 py-3">{labels.columns.instrument}</th>
              <th className="px-5 py-3 text-right">{labels.columns.amount}</th>
              <th className="px-5 py-3">{labels.columns.detail}</th>
            </tr>
          </thead>
          <tbody>
            {visibleEntries.length === 0 ? (
              <tr>
                <td
                  className="px-5 py-8 text-center text-sm text-[var(--app-muted)]"
                  colSpan={5}
                >
                  {labels.filteredEmpty}
                </td>
              </tr>
            ) : null}
            {visibleEntries.map((entry) => {
              const summary = formatLedgerActivitySummary(entry, locale);
              return (
                <tr key={entry.id}>
                  <td className="px-5 py-4 align-top">
                    <div className="font-mono text-xs font-semibold text-[var(--app-soft)]">
                      {formatTimestamp(entry.timestamp)}
                    </div>
                    <div className="app-muted mt-1 text-[11px]">
                      {formatLedgerSourceLabel(entry.source, locale)}
                    </div>
                  </td>
                  <td className="px-5 py-4 align-top">
                    <div className="flex items-center gap-3">
                      <span
                        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold ${activityBadgeClass(summary.tone)}`}
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
                  <td className="px-5 py-4 align-top">
                    <div className="font-semibold">
                      {formatLedgerInstrumentLabel(entry, locale) || '--'}
                    </div>
                    <div className="app-muted mt-1 flex items-center gap-2 text-xs">
                      <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]">
                        {formatAssetClass(entry.asset_class, copy)}
                      </span>
                    </div>
                  </td>
                  <td
                    className={`px-5 py-4 text-right align-top font-mono text-sm font-semibold tabular-nums ${activityAmountClass(summary.tone)}`}
                  >
                    {summary.amount}
                    <LedgerExecutionDetails
                      entry={entry}
                      labels={labels}
                      locale={locale}
                    />
                  </td>
                  <td className="max-w-[280px] px-5 py-4 align-top text-[var(--app-muted)]">
                    <span className="line-clamp-2 break-words">
                      {formatLedgerPublicNote(entry, locale) ?? labels.noDetail}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function activityAmountClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'text-[var(--app-success)]';
  }
  if (tone === 'debit') {
    return 'text-[var(--app-danger)]';
  }
  return 'text-[var(--app-soft)]';
}

function activityBadgeClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]';
  }
  if (tone === 'debit') {
    return 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]';
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
    return <div className="app-muted mt-1 text-xs">--</div>;
  }

  return (
    <div className="app-muted mt-1 flex flex-col items-end gap-0.5 text-xs">
      {details.map((item) => (
        <span key={item.label}>
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
