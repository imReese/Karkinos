import { formatCurrency } from './format';
import type {
  LedgerSummaryKind,
  PublicLedgerEntry,
} from './ledger-format-contracts';

export function normalizeLedgerKind(entryType: string): LedgerSummaryKind {
  const normalized = entryType.trim().toLowerCase();
  if (
    normalized === 'trade_buy' ||
    normalized === 'trade_sell' ||
    normalized === 'cash_deposit' ||
    normalized === 'cash_withdrawal' ||
    normalized === 'cash_interest' ||
    normalized === 'interest_income' ||
    normalized === 'dividend' ||
    normalized === 'manual_adjustment'
  ) {
    return normalized === 'interest_income' ? 'cash_interest' : normalized;
  }
  return 'other';
}

export function finiteNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function finiteBreakdownNumber(
  breakdown: Record<string, number | string | null | undefined>,
  ...keys: string[]
) {
  for (const key of keys) {
    const raw = breakdown[key];
    if (raw === null || raw === undefined || raw === '') {
      continue;
    }
    const numeric = typeof raw === 'number' ? raw : Number(raw);
    if (Number.isFinite(numeric)) {
      return numeric;
    }
  }
  return null;
}

export function sumBreakdownNumbers(
  breakdown: Record<string, number | string | null | undefined>,
  ...keys: string[]
) {
  let total = 0;
  let hasValue = false;
  for (const key of keys) {
    const value = finiteBreakdownNumber(breakdown, key);
    if (value === null) {
      continue;
    }
    total += value;
    hasValue = true;
  }
  return hasValue ? total : null;
}

export function formatSignedCurrency(value: number | null) {
  if (value === null) {
    return null;
  }
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${prefix}${formatCurrency(Math.abs(value))}`;
}

export function isFundLedgerEntry(entry: PublicLedgerEntry) {
  return entry.asset_class?.trim().toLowerCase() === 'fund';
}

export function isCashLedgerEntry(entry: PublicLedgerEntry) {
  return (
    entry.asset_class?.trim().toLowerCase() === 'cash' ||
    normalizeLedgerKind(entry.entry_type).startsWith('cash_')
  );
}

export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
