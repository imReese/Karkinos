import type { LedgerEntry } from '../api';

export type LedgerEntryCategory =
  'all' | 'trade' | 'cash' | 'dividend' | 'adjustment' | 'other';

export type LedgerSubcategory =
  | 'all'
  | 'stock'
  | 'fund'
  | 'cashAccount'
  | 'otherAsset'
  | 'cashDeposit'
  | 'cashWithdrawal'
  | 'cashInterest'
  | 'otherCash';

export type SpecificLedgerSubcategory = Exclude<LedgerSubcategory, 'all'>;

export const LEDGER_ENTRY_CATEGORIES: LedgerEntryCategory[] = [
  'all',
  'trade',
  'cash',
  'dividend',
  'adjustment',
  'other',
];

export const ACTIVITY_PAGE_SIZE = 8;

export const LEDGER_SUBCATEGORIES_BY_CATEGORY: Partial<
  Record<LedgerEntryCategory, SpecificLedgerSubcategory[]>
> = {
  trade: ['stock', 'fund', 'otherAsset'],
  cash: ['cashDeposit', 'cashWithdrawal', 'cashInterest', 'otherCash'],
  dividend: ['stock', 'fund', 'otherAsset'],
  adjustment: ['stock', 'fund', 'cashAccount', 'otherAsset'],
};
export function classifyLedgerEntry(entry: LedgerEntry): LedgerEntryCategory {
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

export function classifyLedgerSubcategory(
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

export function ledgerEntryMatchesQuery(
  entry: LedgerEntry,
  normalizedQuery: string,
) {
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
