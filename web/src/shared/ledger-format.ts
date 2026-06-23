import type { Locale } from '../app/preferences';
import { formatCurrency, formatQuantity } from './format';
import { formatPublicEvidenceReference } from './public-labels';

export type PublicLedgerEntry = {
  id?: number;
  entry_type: string;
  timestamp?: string | null;
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
  asset_class?: string | null;
  note?: string | null;
  source?: string | null;
  source_ref?: string | null;
  created_at?: string | null;
};

export type LedgerSummaryKind =
  | 'trade_buy'
  | 'trade_sell'
  | 'cash_deposit'
  | 'cash_withdrawal'
  | 'cash_interest'
  | 'dividend'
  | 'manual_adjustment'
  | 'other';

export type LedgerEntrySummary = {
  kind: LedgerSummaryKind;
  grossAmount: number | null;
  cashImpact: number | null;
};

export type LedgerActivitySummaryTone =
  | 'credit'
  | 'debit'
  | 'adjustment'
  | 'neutral';

export type LedgerActivitySummary = {
  label: string;
  shortLabel: string;
  amount: string;
  cashImpactLabel: string;
  tone: LedgerActivitySummaryTone;
};

export type LedgerDashboardPresentation = {
  title: string;
  details: string[];
  amount: string;
  publicNote: string | null;
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

export type LedgerExplainabilityItem = {
  kind?: string;
  title?: string;
  detail?: string;
  timestamp?: string;
  symbol?: string | null;
  amount?: number | null;
  quantity?: number | null;
  price?: number | null;
  commission?: number | null;
  gross_amount?: number | null;
  net_cash_impact?: number | null;
  fee_breakdown?: Record<string, number | string | null | undefined> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
  asset_class?: string | null;
};

const SOURCE_LABELS: Record<Locale, Record<string, string>> = {
  en: {
    broker_statement_manual_correction: 'Broker statement correction',
    manual: 'Manual entry',
    portfolio_trade: 'Portfolio trade',
    system: 'System entry',
    unknown: 'Source unknown',
  },
  zh: {
    broker_statement_manual_correction: '券商对账修正',
    manual: '手工录入',
    portfolio_trade: '组合交易',
    system: '系统生成',
    unknown: '来源未知',
  },
};

const ENTRY_TYPE_LABELS: Record<Locale, Record<LedgerSummaryKind, string>> = {
  en: {
    trade_buy: 'Buy',
    trade_sell: 'Sell',
    cash_deposit: 'Cash deposit',
    cash_withdrawal: 'Cash withdrawal',
    cash_interest: 'Cash interest',
    dividend: 'Dividend',
    manual_adjustment: 'Manual adjustment',
    other: 'Ledger movement',
  },
  zh: {
    trade_buy: '买入',
    trade_sell: '卖出',
    cash_deposit: '资金转入',
    cash_withdrawal: '资金转出',
    cash_interest: '现金利息',
    dividend: '分红',
    manual_adjustment: '手动调整',
    other: '账本变动',
  },
};

const EXPLAINABILITY_DETAIL_LABELS: Record<
  Locale,
  LedgerExecutionDetailLabels
> = {
  en: {
    amount: 'Amount',
    grossAmount: 'Gross amount',
    netCashImpact: 'Cash impact',
    quantity: 'Quantity',
    price: 'Price',
    fee: 'Fee',
    commission: 'Commission',
    stampTax: 'Stamp tax',
    transferFee: 'Transfer fee',
    otherFees: 'Other fees',
    costBasis: 'Cost basis',
  },
  zh: {
    amount: '金额',
    grossAmount: '成交金额',
    netCashImpact: '现金影响',
    quantity: '数量',
    price: '价格',
    fee: '手续费',
    commission: '佣金',
    stampTax: '印花税',
    transferFee: '过户费',
    otherFees: '其他费用',
    costBasis: '成本价',
  },
};

const ACTIVITY_LABELS: Record<
  Locale,
  Record<
    LedgerSummaryKind,
    {
      label: string;
      shortLabel: string;
      cashImpactLabel: string;
      tone: LedgerActivitySummaryTone;
    }
  >
> = {
  en: {
    trade_buy: {
      label: 'Security buy',
      shortLabel: 'B',
      cashImpactLabel: 'Consumes cash',
      tone: 'debit',
    },
    trade_sell: {
      label: 'Security sell',
      shortLabel: 'S',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    cash_deposit: {
      label: 'Cash deposit',
      shortLabel: '+',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    cash_withdrawal: {
      label: 'Cash withdrawal',
      shortLabel: '-',
      cashImpactLabel: 'Consumes cash',
      tone: 'debit',
    },
    cash_interest: {
      label: 'Cash interest',
      shortLabel: 'I',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    dividend: {
      label: 'Dividend received',
      shortLabel: 'D',
      cashImpactLabel: 'Adds cash or realized proceeds',
      tone: 'credit',
    },
    manual_adjustment: {
      label: 'Manual adjustment',
      shortLabel: 'A',
      cashImpactLabel: 'Operator adjustment',
      tone: 'adjustment',
    },
    other: {
      label: 'Ledger entry',
      shortLabel: 'L',
      cashImpactLabel: 'Reference ledger movement',
      tone: 'neutral',
    },
  },
  zh: {
    trade_buy: {
      label: '证券买入',
      shortLabel: '买',
      cashImpactLabel: '占用现金',
      tone: 'debit',
    },
    trade_sell: {
      label: '证券卖出',
      shortLabel: '卖',
      cashImpactLabel: '增加现金或确认回款',
      tone: 'credit',
    },
    cash_deposit: {
      label: '现金入金',
      shortLabel: '入',
      cashImpactLabel: '增加现金或确认回款',
      tone: 'credit',
    },
    cash_withdrawal: {
      label: '现金出金',
      shortLabel: '出',
      cashImpactLabel: '占用现金',
      tone: 'debit',
    },
    cash_interest: {
      label: '现金利息',
      shortLabel: '息',
      cashImpactLabel: '增加现金或确认回款',
      tone: 'credit',
    },
    dividend: {
      label: '分红入账',
      shortLabel: '息',
      cashImpactLabel: '增加现金或确认回款',
      tone: 'credit',
    },
    manual_adjustment: {
      label: '手工调整',
      shortLabel: '调',
      cashImpactLabel: '人工校正',
      tone: 'adjustment',
    },
    other: {
      label: '账本流水',
      shortLabel: '流',
      cashImpactLabel: '参考流水',
      tone: 'neutral',
    },
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
  if (
    kind === 'trade_sell' ||
    kind === 'cash_deposit' ||
    kind === 'cash_interest' ||
    kind === 'dividend'
  ) {
    return { kind, grossAmount, cashImpact: netCashImpact ?? grossAmount };
  }
  return { kind, grossAmount, cashImpact: null };
}

export function formatLedgerActivitySummary(
  entry: PublicLedgerEntry,
  locale: Locale,
): LedgerActivitySummary {
  const summary = summarizeLedgerEntry(entry);
  const labels = ACTIVITY_LABELS[locale][summary.kind];
  const amount =
    labels.tone === 'credit' || labels.tone === 'debit'
      ? (formatSignedCurrency(summary.cashImpact) ?? '--')
      : formatCurrency(summary.grossAmount);

  return {
    ...labels,
    amount,
  };
}

export function formatLedgerDashboardPresentation(
  entry: PublicLedgerEntry,
  labels: LedgerExecutionDetailLabels,
  locale: Locale,
  assetClassLabel: string,
): LedgerDashboardPresentation {
  const entryType = formatLedgerEntryTypeLabel(entry, locale);
  const instrumentName = formatLedgerInstrumentLabel(entry);
  const detailLines = formatLedgerExecutionDetailLines(
    entry,
    labels,
    locale,
  ).map((detail) => `${detail.label} ${detail.value}`);

  return {
    title: instrumentName ? `${entryType} ${instrumentName}` : entryType,
    details: [assetClassLabel, ...detailLines],
    amount: formatCurrency(calculateLedgerEntryAmount(entry)),
    publicNote: formatLedgerPublicNote(entry),
  };
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

export function formatLedgerSourceLabel(
  source: string | null | undefined,
  locale: Locale,
) {
  const normalized = (source ?? '').trim().toLowerCase();
  if (!normalized) {
    return SOURCE_LABELS[locale].unknown;
  }
  return (
    SOURCE_LABELS[locale][normalized] ?? source ?? SOURCE_LABELS[locale].unknown
  );
}

export function formatLedgerEvidenceReference(
  reference: string,
  locale: Locale,
) {
  const brokerTradeReference = parseBrokerTradeEvidenceReference(reference);
  if (brokerTradeReference) {
    return [
      locale === 'zh' ? '券商证据' : 'Broker evidence',
      brokerTradeReference.subject,
      formatLedgerEntryTypeLabel(brokerTradeReference.eventType, locale),
      brokerTradeReference.importRunId,
    ].join(' · ');
  }

  return formatPublicEvidenceReference(reference, locale);
}

export function formatLedgerExplainabilityTitle(
  item: LedgerExplainabilityItem,
  locale: Locale,
  instrumentNames?: Map<string, string>,
) {
  if (!isGeneratedExplainabilityTitle(item) && item.title) {
    return item.title;
  }
  const entry = toExplainabilityLedgerEntry(item, instrumentNames);
  const entryType = formatLedgerEntryTypeLabel(entry, locale);
  const instrument = formatLedgerInstrumentLabel(entry);
  return instrument ? `${entryType} ${instrument}` : entryType;
}

export function formatLedgerExplainabilityDetail(
  item: LedgerExplainabilityItem,
  locale: Locale,
  instrumentNames?: Map<string, string>,
) {
  const entry = toExplainabilityLedgerEntry(
    { ...item, title: undefined },
    instrumentNames,
  );
  const structuredDetails = formatLedgerExecutionDetailLines(
    entry,
    EXPLAINABILITY_DETAIL_LABELS[locale],
    locale,
  ).map((line) => `${line.label} ${line.value}`);
  const publicNote = formatLedgerPublicNote(entry);
  if (structuredDetails.length > 0 || publicNote) {
    return [...structuredDetails, publicNote].filter(Boolean).join(' · ');
  }

  switch (item.kind) {
    case 'cash_deposit':
      return locale === 'zh'
        ? '现金流入组合。'
        : 'Cash inflow into the portfolio.';
    case 'cash_withdrawal':
      return locale === 'zh'
        ? '现金流出组合。'
        : 'Cash outflow from the portfolio.';
    case 'dividend':
      return locale === 'zh' ? '持仓现金收入。' : 'Cash income from a holding.';
    case 'manual_adjustment':
      return locale === 'zh' ? '手工账本调整。' : 'Manual ledger adjustment.';
    default:
      return item.detail || null;
  }
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
    .filter((segment) => !isGeneratedStructuredTradeNote(segment, entry))
    .filter((segment) => !isGeneratedStructuredCashNote(segment, entry))
    .filter(Boolean);
  return segments.length > 0 ? segments.slice(0, 2).join(' · ') : null;
}

export function formatLedgerExecutionDetailLines(
  entry: PublicLedgerEntry,
  labels: LedgerExecutionDetailLabels,
  _locale: Locale,
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
      formatCurrency(finiteNumber(entry.net_cash_impact)),
    );
  }
  addLine(lines, labels.quantity, formatQuantity(finiteNumber(entry.quantity)));
  addLine(lines, labels.price, formatCurrency(finiteNumber(entry.price)));

  if (breakdown) {
    if (isFundLedgerEntry(entry)) {
      const fundFee = sumBreakdownNumbers(
        breakdown,
        'commission',
        'subscription_fee',
        'redemption_fee',
      );
      if (fundFee !== null && fundFee !== 0) {
        addLine(lines, labels.fee, formatCurrency(fundFee));
      }
      const otherFees = finiteBreakdownNumber(breakdown, 'other_fees');
      if (otherFees !== null && otherFees !== 0) {
        addLine(lines, labels.otherFees, formatCurrency(otherFees));
      }
      return lines;
    }
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
    const fee = finiteNumber(entry.commission);
    if (!isFundLedgerEntry(entry) || (fee !== null && fee !== 0)) {
      addLine(lines, labels.fee, formatCurrency(fee));
    }
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
    normalized === 'cash_interest' ||
    normalized === 'interest_income' ||
    normalized === 'dividend' ||
    normalized === 'manual_adjustment'
  ) {
    return normalized === 'interest_income' ? 'cash_interest' : normalized;
  }
  return 'other';
}

function parseBrokerTradeEvidenceReference(reference: string) {
  const [sourceType, importRunId, subject, ...eventTypeParts] =
    reference.split(':');
  const eventType = eventTypeParts.join(':');
  if (
    sourceType !== 'broker_event' ||
    !importRunId ||
    !subject ||
    (eventType !== 'trade_buy' && eventType !== 'trade_sell')
  ) {
    return null;
  }

  return {
    importRunId,
    subject,
    eventType,
  };
}

function toExplainabilityLedgerEntry(
  item: LedgerExplainabilityItem,
  instrumentNames?: Map<string, string>,
) {
  const symbol = item.symbol?.trim() ?? null;
  return {
    id: 0,
    entry_type: item.kind ?? 'other',
    timestamp: item.timestamp ?? '',
    amount: item.amount ?? null,
    symbol,
    display_name: resolveMappedInstrumentName(symbol, instrumentNames),
    direction:
      item.kind === 'trade_buy'
        ? 'buy'
        : item.kind === 'trade_sell'
          ? 'sell'
          : null,
    quantity: item.quantity ?? null,
    price: item.price ?? null,
    commission: item.commission ?? null,
    gross_amount: item.gross_amount ?? null,
    net_cash_impact: item.net_cash_impact ?? null,
    fee_breakdown: item.fee_breakdown ?? null,
    fee_rule_id: item.fee_rule_id ?? null,
    fee_rule_version: item.fee_rule_version ?? null,
    asset_class: item.asset_class ?? 'other',
    note: [item.title, item.detail].filter(Boolean).join(' | '),
    source: 'explainability',
    source_ref: null,
    created_at: null,
  } satisfies PublicLedgerEntry;
}

function isGeneratedExplainabilityTitle(item: LedgerExplainabilityItem) {
  const title = item.title?.trim();
  if (!title) {
    return true;
  }
  return (
    title === item.kind ||
    title.includes('_') ||
    /^(bought|sold)\s+\S+/i.test(title) ||
    /^(买入|卖出|申购|赎回)\s*\S+/u.test(title)
  );
}

function resolveMappedInstrumentName(
  symbol: string | null | undefined,
  instrumentNames?: Map<string, string>,
) {
  const normalizedSymbol = symbol?.trim();
  if (!normalizedSymbol) {
    return null;
  }
  return instrumentNames?.get(normalizedSymbol.toLowerCase()) ?? null;
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

function sumBreakdownNumbers(
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

function formatSignedCurrency(value: number | null) {
  if (value === null) {
    return null;
  }
  const prefix = value > 0 ? '+' : value < 0 ? '-' : '';
  return `${prefix}${formatCurrency(Math.abs(value))}`;
}

function isFundLedgerEntry(entry: PublicLedgerEntry) {
  return entry.asset_class?.trim().toLowerCase() === 'fund';
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

function isGeneratedStructuredTradeNote(
  segment: string,
  entry: PublicLedgerEntry,
) {
  const kind = normalizeLedgerKind(entry.entry_type);
  if (kind !== 'trade_buy' && kind !== 'trade_sell') {
    return false;
  }
  const hasStructuredTradeFields =
    finiteNumber(entry.quantity) !== null ||
    finiteNumber(entry.price) !== null ||
    finiteNumber(entry.gross_amount ?? entry.amount) !== null ||
    finiteNumber(entry.commission) !== null ||
    Boolean(entry.fee_breakdown);
  if (!hasStructuredTradeFields) {
    return false;
  }

  const normalized = segment.trim();
  const symbol = entry.symbol?.trim();
  const name = resolveLedgerInstrumentName(entry).trim();
  const instrumentPrefixes = [
    name,
    symbol,
    name && symbol && `${name} ${symbol}`,
  ]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.trim());
  const startsWithInstrument = instrumentPrefixes.some(
    (prefix) =>
      normalized === prefix ||
      normalized.startsWith(`${prefix} `) ||
      normalized.startsWith(`${prefix}买入`) ||
      normalized.startsWith(`${prefix}卖出`) ||
      normalized.startsWith(`${prefix}申购`) ||
      normalized.startsWith(`${prefix}赎回`),
  );
  const startsWithStructuredFact =
    /^(?:数量|价格|手续费|佣金|份额|金额|成交|quantity\b|price\b|fee\b|commission\b|amount\b)/i.test(
      normalized,
    );
  const startsWithActionFact =
    /^(?:买入|卖出|申购|赎回|buy\b|bought\b|sell\b|sold\b)/i.test(normalized);
  if (
    !startsWithInstrument &&
    !startsWithStructuredFact &&
    !startsWithActionFact
  ) {
    return false;
  }

  const directionPattern =
    kind === 'trade_buy' ? /(买入|申购|buy|bought)/i : /(卖出|赎回|sell|sold)/i;
  const structuredFactPattern =
    /(佣金|手续费|申购金额|赎回金额|买入金额|卖出金额|成交|份额|数量|价格|成本|元|gross|amount|quantity|price|fee|commission|subscription|redemption)/i;

  if (startsWithStructuredFact || startsWithActionFact) {
    return structuredFactPattern.test(normalized);
  }
  return (
    directionPattern.test(normalized) && structuredFactPattern.test(normalized)
  );
}

function isGeneratedStructuredCashNote(
  segment: string,
  entry: PublicLedgerEntry,
) {
  const kind = normalizeLedgerKind(entry.entry_type);
  if (
    kind !== 'cash_deposit' &&
    kind !== 'cash_withdrawal' &&
    kind !== 'cash_interest' &&
    kind !== 'dividend'
  ) {
    return false;
  }
  const amount = finiteNumber(
    entry.gross_amount ?? entry.amount ?? entry.net_cash_impact,
  );
  if (amount === null || !segmentMentionsAmount(segment, amount)) {
    return false;
  }

  const normalized = segment.trim();
  const keywordPattern =
    kind === 'cash_interest'
      ? /(现金利息|结息|interest)/i
      : kind === 'dividend'
        ? /(分红|股息|红利|dividend)/i
        : kind === 'cash_deposit'
          ? /(现金入金|资金转入|入金|转入|cash deposit|deposit)/i
          : /(现金出金|资金转出|出金|转出|cash withdrawal|withdrawal|withdraw)/i;
  return keywordPattern.test(normalized);
}

function segmentMentionsAmount(segment: string, amount: number) {
  const normalized = segment.replace(/[,，]/g, '');
  const absolute = Math.abs(amount);
  const rawCandidates = [
    String(absolute),
    absolute.toFixed(2),
    absolute.toFixed(4),
  ];
  const candidates = new Set(
    rawCandidates
      .flatMap((candidate) =>
        candidate.includes('.')
          ? [candidate, candidate.replace(/\.?0+$/, '')]
          : [candidate],
      )
      .filter(Boolean),
  );
  return [...candidates].some((candidate) =>
    new RegExp(`(^|[^0-9.])${escapeRegExp(candidate)}([^0-9.]|$)`).test(
      normalized,
    ),
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
