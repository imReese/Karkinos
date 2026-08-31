import { useCopy } from '../../../shared/i18n/context';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
} from '../../../shared/format';
import { type Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  formatInstrumentDisplayLabel,
  type InstrumentDisplayRecord,
} from '../../../shared/instrument-display';
import {
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  formatLedgerOrderSideLabel,
  type LedgerExecutionDetailLabels,
  type PublicLedgerEntry,
} from '../../../shared/ledger-format';
import type {
  FillFact,
  ManualOrder,
  ManualOrderStatus,
  OrderFact,
} from '../api';

export type SideFilter = 'all' | 'buy' | 'sell';
export type InstrumentNameLookup = Map<string, string>;

export const STATUS_OPTIONS: ManualOrderStatus[] = [
  'all',
  'pending_confirm',
  'confirmed',
  'rejected',
  'canceled',
];

export function statusLabel(
  status: string,
  labels: ReturnType<typeof useCopy>['trading']['page'],
  locale?: Locale,
) {
  if (status === 'pending_confirm') {
    return labels.statusPendingConfirm;
  }
  if (status === 'confirmed') {
    return labels.statusConfirmed;
  }
  if (status === 'rejected') {
    return labels.statusRejected;
  }
  if (status === 'canceled') {
    return labels.statusCanceled;
  }
  return locale ? formatPublicStatus(status, locale) : status;
}

export function getLatestOrderTimestamp(orders: ManualOrder[]) {
  const latest = orders
    .map((order) => order.updated_at || order.created_at || order.timestamp)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => right - left)[0];

  return latest ? new Date(latest).toISOString() : null;
}

export function parsePayload(
  value: string,
): Record<string, string | null> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === 'object'
      ? (parsed as Record<string, string | null>)
      : null;
  } catch {
    return null;
  }
}

export function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function instrumentDisplayLabel(
  instrument: InstrumentDisplayRecord | string,
  instrumentNames: InstrumentNameLookup,
) {
  const record =
    typeof instrument === 'string' ? { symbol: instrument } : instrument;
  return formatInstrumentDisplayLabel({
    ...record,
    display_name:
      record.display_name ??
      record.name ??
      instrumentNames.get(record.symbol ?? '') ??
      null,
  });
}

export function sideLabel(side: string, locale: Locale = 'en') {
  return formatLedgerOrderSideLabel(side, locale);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseJsonObject(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function parseFillMetadata(fill: FillFact) {
  if (isRecord(fill.metadata)) {
    return fill.metadata;
  }
  if (typeof fill.metadata === 'string') {
    return parseJsonObject(fill.metadata) ?? {};
  }
  return parseJsonObject(fill.metadata_json) ?? {};
}

function finiteMetadataNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function firstFiniteNumber(...values: unknown[]) {
  for (const value of values) {
    const numeric = finiteMetadataNumber(value);
    if (numeric !== null) {
      return numeric;
    }
  }
  return null;
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }
  return null;
}

function feeBreakdownFromMetadata(
  value: unknown,
): PublicLedgerEntry['fee_breakdown'] {
  return isRecord(value)
    ? (value as Record<string, number | string | null | undefined>)
    : null;
}

function fillToLedgerEntry(
  fill: FillFact,
  instrumentNames: InstrumentNameLookup,
): PublicLedgerEntry {
  const metadata = parseFillMetadata(fill);
  const quantity = firstFiniteNumber(fill.fill_quantity, metadata.quantity);
  const price = firstFiniteNumber(fill.fill_price, metadata.price);
  const grossAmount = firstFiniteNumber(
    fill.gross_amount,
    metadata.gross_amount,
    quantity !== null && price !== null ? quantity * price : null,
  );
  const normalizedSide = fill.side.trim().toLowerCase();
  const entryType = normalizedSide === 'sell' ? 'trade_sell' : 'trade_buy';

  return {
    id: fill.id,
    entry_type: entryType,
    timestamp: fill.timestamp,
    amount: grossAmount,
    symbol: fill.symbol,
    display_name:
      fill.display_name ??
      fill.name ??
      instrumentNames.get(fill.symbol) ??
      instrumentNames.get(fill.symbol.toLowerCase()) ??
      null,
    direction: normalizedSide || null,
    quantity,
    price,
    commission: firstFiniteNumber(fill.commission, metadata.commission),
    gross_amount: grossAmount,
    net_cash_impact: firstFiniteNumber(
      fill.net_cash_impact,
      metadata.net_cash_impact,
    ),
    fee_breakdown:
      fill.fee_breakdown ?? feeBreakdownFromMetadata(metadata.fee_breakdown),
    fee_rule_id: firstString(fill.fee_rule_id, metadata.fee_rule_id),
    fee_rule_version: firstString(
      fill.fee_rule_version,
      metadata.fee_rule_version,
    ),
    asset_class: firstString(fill.asset_class, metadata.asset_class) ?? 'stock',
    note: firstString(metadata.note),
    source: firstString(fill.source, metadata.source),
    source_ref: firstString(fill.source_ref, metadata.source_ref),
    created_at: null,
  };
}

function orderToLedgerEntry(
  order: OrderFact,
  instrumentNames: InstrumentNameLookup,
): PublicLedgerEntry {
  const quantity = finiteMetadataNumber(order.quantity);
  const price = finiteMetadataNumber(order.price);
  const normalizedSide = order.side.trim().toLowerCase();
  const entryType = normalizedSide === 'sell' ? 'trade_sell' : 'trade_buy';
  const grossAmount =
    quantity !== null && price !== null ? quantity * price : null;

  return {
    id: order.id,
    entry_type: entryType,
    timestamp: order.timestamp,
    amount: grossAmount,
    symbol: order.symbol,
    display_name:
      order.display_name ??
      order.name ??
      instrumentNames.get(order.symbol) ??
      instrumentNames.get(order.symbol.toLowerCase()) ??
      null,
    direction: normalizedSide || null,
    quantity,
    price,
    commission: null,
    gross_amount: null,
    net_cash_impact: null,
    fee_breakdown: null,
    fee_rule_id: null,
    fee_rule_version: null,
    asset_class: order.asset_class ?? 'stock',
    note: order.note ?? null,
    source: order.source ?? null,
    source_ref: order.source_ref ?? null,
    created_at: order.created_at ?? null,
  };
}

export function formatOrderFactTitle(
  order: OrderFact,
  locale: Locale,
  instrumentNames: InstrumentNameLookup,
) {
  const entry = orderToLedgerEntry(order, instrumentNames);
  const action = sideLabel(order.side, locale);
  const instrument = formatLedgerInstrumentLabel(entry);
  return instrument ? `${action} ${instrument}` : action;
}

export function formatOrderFactDetail(
  order: OrderFact,
  labels: ReturnType<typeof useCopy>['trading']['page'],
  detailLabels: LedgerExecutionDetailLabels,
  locale: Locale,
  instrumentNames: InstrumentNameLookup,
) {
  const entry = orderToLedgerEntry(order, instrumentNames);
  const structuredDetails = formatLedgerExecutionDetailLines(
    entry,
    detailLabels,
    locale,
  ).map((detail) => `${detail.label} ${detail.value}`);
  structuredDetails.push(
    `${labels.statusFilter} ${statusLabel(order.status, labels, locale)}`,
  );
  return structuredDetails.join(' · ');
}

export function formatFillDetail(
  fill: FillFact,
  labels: ReturnType<typeof useCopy>['trading']['page'],
  detailLabels: LedgerExecutionDetailLabels,
  locale: Locale,
  instrumentNames: InstrumentNameLookup,
) {
  const structuredDetails = formatLedgerExecutionDetailLines(
    fillToLedgerEntry(fill, instrumentNames),
    detailLabels,
    locale,
  ).map((detail) => `${detail.label} ${detail.value}`);

  if (structuredDetails.length > 0) {
    return structuredDetails.join(' · ');
  }

  return `${formatQuantity(fill.fill_quantity)} @ ${formatPrice(
    fill.fill_price,
  )} · ${labels.commission} ${formatCurrency(fill.commission)}`;
}
