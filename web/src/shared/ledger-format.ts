import type { Locale } from '../app/preferences';
import { formatCurrency, formatQuantity } from './format';

export type PublicLedgerEntry = {
  entry_type: string;
  amount?: number | null;
  symbol?: string | null;
  display_name?: string | null;
  direction?: string | null;
  quantity?: number | null;
  price?: number | null;
  commission?: number | null;
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  cost_basis_method?: string | null;
  note?: string | null;
};

export type LedgerSummaryKind =
  | 'trade_buy'
  | 'trade_sell'
  | 'cash_deposit'
  | 'cash_withdrawal'
  | 'dividend'
  | 'manual_adjustment'
  | 'other';

export type LedgerEntrySummary = {
  kind: LedgerSummaryKind;
  grossAmount: number | null;
  cashImpact: number | null;
};

export type LedgerExecutionDetailLabels = {
  amount: string;
  grossAmount: string;
  netCashImpact: string;
  quantity: string;
  price: string;
  fee: string;
  commission: string;
  stampTax: string;
  transferFee: string;
  otherFees: string;
  costBasis: string;
};

export type LedgerExecutionDetailLine = {
  label: string;
  value: string;
};

const COST_BASIS_METHOD_LABELS: Record<Locale, Record<string, string>> = {
  en: {
    moving_average_buy_cost: 'Moving average buy cost',
    broker_remaining_cost: 'Broker displayed cost basis',
  },
  zh: {
    moving_average_buy_cost: '移动平均买入成本',
    broker_remaining_cost: '券商展示成本',
  },
};

const ENTRY_TYPE_LABELS: Record<Locale, Record<LedgerSummaryKind, string>> = {
  en: {
    trade_buy: 'Buy',
    trade_sell: 'Sell',
    cash_deposit: 'Cash deposit',
    cash_withdrawal: 'Cash withdrawal',
    dividend: 'Dividend',
    manual_adjustment: 'Manual adjustment',
    other: 'Ledger movement',
  },
  zh: {
    trade_buy: '买入',
    trade_sell: '卖出',
    cash_deposit: '资金转入',
    cash_withdrawal: '资金转出',
    dividend: '分红',
    manual_adjustment: '手动调整',
    other: '账本变动',
  },
};

export function summarizeLedgerEntry(
  entry: PublicLedgerEntry,
): LedgerEntrySummary {
  const grossAmount = calculateLedgerEntryAmount(entry);
  const netCashImpact = finiteNumber(entry.net_cash_impact);
  const kind = normalizeLedgerKind(entry.entry_type);

  if (kind === 'trade_buy' || kind === 'cash_withdrawal') {
    return {
      kind,
      grossAmount,
      cashImpact: netCashImpact ?? (grossAmount === null ? null : -grossAmount),
    };
  }
  if (kind === 'trade_sell' || kind === 'cash_deposit' || kind === 'dividend') {
    return { kind, grossAmount, cashImpact: netCashImpact ?? grossAmount };
  }
  return { kind, grossAmount, cashImpact: null };
}

export function calculateLedgerEntryAmount(entry: PublicLedgerEntry) {
  if (
    typeof entry.gross_amount === 'number' &&
    Number.isFinite(entry.gross_amount)
  ) {
    return entry.gross_amount;
  }
  if (typeof entry.amount === 'number' && Number.isFinite(entry.amount)) {
    return entry.amount;
  }
  if (
    typeof entry.price === 'number' &&
    Number.isFinite(entry.price) &&
    typeof entry.quantity === 'number' &&
    Number.isFinite(entry.quantity)
  ) {
    return entry.price * entry.quantity;
  }
  return null;
}

export function formatLedgerEntryTypeLabel(
  entryOrType: PublicLedgerEntry | string,
  locale: Locale,
) {
  const entryType =
    typeof entryOrType === 'string' ? entryOrType : entryOrType.entry_type;
  const kind = normalizeLedgerKind(entryType);
  return ENTRY_TYPE_LABELS[locale][kind];
}

export function formatLedgerInstrumentLabel(entry: PublicLedgerEntry) {
  const name = resolveLedgerInstrumentName(entry);
  const symbol = entry.symbol?.trim();
  if (!symbol) {
    return name;
  }
  if (!name || name === symbol) {
    return symbol;
  }
  return `${name} ${symbol}`;
}

export function resolveLedgerInstrumentName(entry: PublicLedgerEntry) {
  const displayName = entry.display_name?.trim();
  if (displayName) {
    return displayName;
  }
  const noteName = readableLedgerNoteSegments(entry.note)
    .map((segment) => extractInstrumentNameFromSegment(segment, entry.symbol))
    .find(Boolean);
  return noteName ?? entry.symbol ?? '';
}

export function formatLedgerPublicNote(entry: PublicLedgerEntry) {
  const segments = readableLedgerNoteSegments(entry.note)
    .map((segment) => stripLedgerNotePrefix(segment).trim())
    .filter((segment) => !isInstrumentIdentitySegment(segment, entry))
    .map((segment) => removeDuplicateSymbolFromSegment(segment, entry))
    .filter(Boolean);
  return segments.length > 0 ? segments.slice(0, 2).join(' · ') : null;
}

export function formatLedgerExecutionDetailLines(
  entry: PublicLedgerEntry,
  labels: LedgerExecutionDetailLabels,
  locale: Locale,
): LedgerExecutionDetailLine[] {
  const hasStructuredCosts =
    finiteNumber(entry.gross_amount) !== null ||
    finiteNumber(entry.net_cash_impact) !== null ||
    Boolean(entry.fee_breakdown);
  const breakdown = entry.fee_breakdown ?? null;
  const lines: LedgerExecutionDetailLine[] = [];

  addLine(
    lines,
    hasStructuredCosts ? labels.grossAmount : labels.amount,
    formatCurrency(finiteNumber(entry.gross_amount ?? entry.amount)),
  );
  if (hasStructuredCosts) {
    addLine(
      lines,
      labels.netCashImpact,
      formatSignedCurrency(finiteNumber(entry.net_cash_impact)),
    );
  }
  addLine(lines, labels.quantity, formatQuantity(finiteNumber(entry.quantity)));
  addLine(lines, labels.price, formatCurrency(finiteNumber(entry.price)));

  if (breakdown) {
    addLine(
      lines,
      labels.commission,
      formatCurrency(finiteBreakdownNumber(breakdown, 'commission')),
    );
    addLine(
      lines,
      labels.stampTax,
      formatCurrency(finiteBreakdownNumber(breakdown, 'stamp_tax', 'tax')),
    );
    addLine(
      lines,
      labels.transferFee,
      formatCurrency(finiteBreakdownNumber(breakdown, 'transfer_fee')),
    );
    const otherFees = finiteBreakdownNumber(breakdown, 'other_fees');
    if (otherFees !== null && otherFees !== 0) {
      addLine(lines, labels.otherFees, formatCurrency(otherFees));
    }
  } else {
    addLine(lines, labels.fee, formatCurrency(finiteNumber(entry.commission)));
  }

  const costBasisMethod = formatCostBasisMethod(
    entry.cost_basis_method,
    locale,
  );
  if (costBasisMethod) {
    addLine(lines, labels.costBasis, costBasisMethod);
  }

  return lines;
}

export function readableLedgerNoteSegments(note: string | null | undefined) {
  if (!note) {
    return [];
  }
  return note
    .split('|')
    .map((segment) => segment.trim())
    .filter((segment) => segment && !isTechnicalNoteSegment(segment));
}

function normalizeLedgerKind(entryType: string): LedgerSummaryKind {
  const normalized = entryType.trim().toLowerCase();
  if (
    normalized === 'trade_buy' ||
    normalized === 'trade_sell' ||
    normalized === 'cash_deposit' ||
    normalized === 'cash_withdrawal' ||
    normalized === 'dividend' ||
    normalized === 'manual_adjustment'
  ) {
    return normalized;
  }
  return 'other';
}

function addLine(
  lines: LedgerExecutionDetailLine[],
  label: string,
  value: string | null,
) {
  if (value === null || value === '--') {
    return;
  }
  lines.push({ label, value });
}

function finiteNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function finiteBreakdownNumber(
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

function formatSignedCurrency(value: number | null) {
  if (value === null) {
    return null;
  }
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${prefix}${formatCurrency(Math.abs(value))}`;
}

function formatCostBasisMethod(
  value: string | null | undefined,
  locale: Locale,
) {
  const normalized = value?.trim();
  if (!normalized) {
    return null;
  }
  return COST_BASIS_METHOD_LABELS[locale][normalized] ?? normalized;
}

function isTechnicalNoteSegment(segment: string) {
  return (
    /(^|\s)[a-z][a-z0-9_]*=/i.test(segment) ||
    /auto-confirmed/i.test(segment) ||
    /confirmed_(trade_date|nav|quantity)/i.test(segment) ||
    /gross_amount/i.test(segment) ||
    /^RMB cash (deposit|withdrawal) recorded from user request$/i.test(segment)
  );
}

function stripLedgerNotePrefix(segment: string) {
  return segment
    .replace(/^用户记录[:：]\s*/, '')
    .replace(/^手工录入(?:持仓|基金申购|现金入金|现金出金)[:：]\s*/, '');
}

function looksLikeInstrumentNameOnly(segment: string) {
  return /^[\u4e00-\u9fffA-Za-z0-9（）()·\-\s]+[A-C]?$/.test(segment);
}

function isInstrumentIdentitySegment(
  segment: string,
  entry: PublicLedgerEntry,
) {
  const normalized = segment.trim();
  const symbol = entry.symbol?.trim();
  const name = resolveLedgerInstrumentName(entry).trim();
  return [name, symbol, name && symbol ? `${name} ${symbol}` : null]
    .filter(Boolean)
    .some((candidate) => candidate === normalized);
}

function extractInstrumentNameFromSegment(
  segment: string,
  symbol: string | null | undefined,
) {
  const cleaned = stripLedgerNotePrefix(segment).trim();
  if (!/[\u4e00-\u9fff]/.test(cleaned)) {
    return null;
  }
  if (cleaned.includes('保存') || cleaned.includes('成本价')) {
    return null;
  }
  const candidate = cleaned
    .split(/\s+(买入|卖出|申购|赎回|分红|调整|加仓)/u)[0]
    .split(/[，；:：]/u)[0]
    .trim();
  const normalizedCandidate = removeTrailingSymbol(candidate, symbol);
  if (!normalizedCandidate || normalizedCandidate === cleaned) {
    return looksLikeInstrumentNameOnly(cleaned) ? cleaned : null;
  }
  return normalizedCandidate;
}

function removeDuplicateSymbolFromSegment(
  segment: string,
  entry: PublicLedgerEntry,
) {
  const symbol = entry.symbol?.trim();
  const displayName = entry.display_name?.trim();
  if (!symbol) {
    return segment;
  }
  if (displayName && segment.startsWith(`${displayName} ${symbol} `)) {
    return `${displayName} ${segment.slice(`${displayName} ${symbol} `.length)}`;
  }
  return segment.replace(
    new RegExp(`^(.+?)\\s+${escapeRegExp(symbol)}\\s+`),
    '$1 ',
  );
}

function removeTrailingSymbol(
  value: string,
  symbol: string | null | undefined,
) {
  const normalizedSymbol = symbol?.trim();
  if (!normalizedSymbol) {
    return value;
  }
  return value.replace(
    new RegExp(`\\s+${escapeRegExp(normalizedSymbol)}$`),
    '',
  );
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
