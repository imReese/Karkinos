import type { Locale } from '../../../shared/preferences/context';
import { formatCurrency, formatQuantity } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatLedgerEntryTypeLabel } from '../../../shared/ledger-format';
import type { StatusTone } from '../../../shared/ui/workbench';
import type { CiticHistoryEventTypeCount } from '../api';

export function formatCiticEventTypeCounts(
  counts: CiticHistoryEventTypeCount[],
  locale: Locale,
) {
  if (counts.length === 0) {
    return locale === 'zh' ? '无' : 'none';
  }
  return counts
    .map(
      ({ event_type: eventType, count }) =>
        `${formatLedgerEntryTypeLabel(eventType, locale)} ${count}`,
    )
    .join(' · ');
}

const currencyReconciliationCategories = new Set([
  'cash',
  'fee',
  'tax',
  'trade_gross_amount',
  'net_cash_impact',
  'transfer_fee',
]);

function parseReconciliationNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed || trimmed === '--') {
    return null;
  }
  const parsed = Number(trimmed.replace(/,/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatReconciliationValue(
  category: string,
  value: string,
  locale: Locale,
) {
  const parsed = parseReconciliationNumber(value);
  if (parsed === null) {
    return value || '--';
  }

  if (category === 'position') {
    return `${formatQuantity(parsed)} ${locale === 'zh' ? '股' : 'shares'}`;
  }

  if (category === 'cost_basis') {
    return formatCurrency(parsed, {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    });
  }

  if (currencyReconciliationCategories.has(category)) {
    return formatCurrency(parsed);
  }

  return value;
}

export function statusTone(status: string): StatusTone {
  const normalized = status.trim().toLowerCase();
  if (
    [
      'pass',
      'ready',
      'available',
      'healthy',
      'fresh',
      'imported',
      'unchanged',
    ].includes(normalized)
  ) {
    return 'success';
  }
  if (
    ['warning', 'degraded', 'stale', 'partial', 'pending_stability'].includes(
      normalized,
    )
  ) {
    return 'warning';
  }
  if (
    ['mismatch', 'blocked', 'error', 'missing', 'unreconciled'].includes(
      normalized,
    )
  ) {
    return 'danger';
  }
  if (['waiting_for_file', 'checking'].includes(normalized)) {
    return 'info';
  }
  return 'neutral';
}

export function formatCode(
  value: string,
  locale: Locale,
  kind: 'status' | 'code',
) {
  return kind === 'status'
    ? formatPublicStatus(value, locale)
    : formatPublicCode(value, locale);
}
