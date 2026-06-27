import type { Locale } from '../app/preferences';
import { formatCurrency, formatQuantity } from './format';
import {
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicStatus,
} from './public-labels';

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
    broker_statement_manual_correction: 'Reconciliation adjustment',
    manual: 'Manual entry',
    portfolio_trade: 'Portfolio trade',
    review: 'Source needs review',
    system: 'System entry',
    unknown: 'Source unknown',
  },
  zh: {
    broker_statement_manual_correction: '对账校正',
    manual: '手工录入',
    portfolio_trade: '交易流水',
    review: '账本来源待确认',
    system: '系统生成',
    unknown: '来源未知',
  },
};

const FEE_RULE_LABELS: Record<Locale, Record<string, string>> = {
  en: {
    manual_configured_commission: 'Configured account fee rule',
    manual_fee_input: 'Manual fee override',
    review: 'Fee rule needs review',
  },
  zh: {
    manual_configured_commission: '账户配置费用规则',
    manual_fee_input: '手工费用覆盖',
    review: '费用规则待确认',
  },
};

const COST_BASIS_METHOD_LABELS: Record<Locale, Record<string, string>> = {
  en: {
    broker_remaining_cost: 'Broker displayed remaining cost',
    moving_average_buy_cost: 'Moving average buy cost',
    projected_from_ledger: 'Projected from local ledger',
    review: 'Cost basis method needs review',
  },
  zh: {
    broker_remaining_cost: '券商剩余持仓成本',
    moving_average_buy_cost: '移动平均买入成本',
    projected_from_ledger: '本地流水推算',
    review: '成本口径待确认',
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
    cash_interest: '结息入账',
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
      cashImpactLabel: '成交回款',
      tone: 'credit',
    },
    cash_deposit: {
      label: '资金转入',
      shortLabel: '入',
      cashImpactLabel: '现金增加',
      tone: 'credit',
    },
    cash_withdrawal: {
      label: '资金转出',
      shortLabel: '出',
      cashImpactLabel: '现金减少',
      tone: 'debit',
    },
    cash_interest: {
      label: '结息入账',
      shortLabel: '息',
      cashImpactLabel: '现金利息',
      tone: 'credit',
    },
    dividend: {
      label: '分红入账',
      shortLabel: '息',
      cashImpactLabel: '持仓现金收入',
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
  const instrumentName = formatLedgerInstrumentLabel(entry, locale);
  const detailLines = formatLedgerExecutionDetailLines(
    entry,
    labels,
    locale,
  ).map((detail) => `${detail.label} ${detail.value}`);

  return {
    title: instrumentName ? `${entryType} ${instrumentName}` : entryType,
    details: [assetClassLabel, ...detailLines],
    amount:
      formatSignedCurrency(summarizeLedgerEntry(entry).cashImpact) ??
      formatCurrency(calculateLedgerEntryAmount(entry)),
    publicNote: formatLedgerPublicNote(entry, locale),
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

export function formatLedgerOrderSideLabel(side: string, locale: Locale) {
  const normalized = side.trim().toLowerCase();
  if (normalized === 'buy') {
    return formatLedgerEntryTypeLabel('trade_buy', locale);
  }
  if (normalized === 'sell') {
    return formatLedgerEntryTypeLabel('trade_sell', locale);
  }
  return formatPublicStatus(side, locale);
}

export function formatLedgerSourceLabel(
  source: string | null | undefined,
  locale: Locale,
) {
  const normalized = (source ?? '').trim().toLowerCase();
  if (!normalized) {
    return SOURCE_LABELS[locale].unknown;
  }
  return SOURCE_LABELS[locale][normalized] ?? SOURCE_LABELS[locale].review;
}

export function formatLedgerFeeRuleLabel(
  feeRuleId: string | null | undefined,
  locale: Locale,
) {
  const normalized = (feeRuleId ?? '').trim().toLowerCase();
  if (!normalized) {
    return FEE_RULE_LABELS[locale].review;
  }
  return FEE_RULE_LABELS[locale][normalized] ?? FEE_RULE_LABELS[locale].review;
}

export function formatLedgerCostBasisMethodLabel(
  method: string | null | undefined,
  locale: Locale,
) {
  const normalized = (method ?? '').trim().toLowerCase();
  if (!normalized) {
    return COST_BASIS_METHOD_LABELS[locale].review;
  }
  return (
    COST_BASIS_METHOD_LABELS[locale][normalized] ??
    COST_BASIS_METHOD_LABELS[locale].review
  );
}

export function formatLedgerEvidenceReference(
  reference: string,
  locale: Locale,
  instrumentNames?: Map<string, string>,
) {
  const brokerReference = parseBrokerEvidenceReference(reference);
  if (brokerReference) {
    const subject = formatEvidenceSubject(
      brokerReference.subject,
      instrumentNames,
    );
    return [
      locale === 'zh' ? '券商证据' : 'Broker evidence',
      subject,
      formatBrokerEvidenceTypeLabel(brokerReference.eventType, locale),
      brokerReference.importRunId,
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
  const shouldShowInstrument =
    !isCashLedgerEntry(entry) || Boolean(entry.symbol || entry.display_name);
  const instrument = shouldShowInstrument
    ? formatLedgerInstrumentLabel(entry, locale)
    : '';
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
  const publicNote = formatLedgerPublicNote(entry, locale);
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

export function formatLedgerInstrumentLabel(
  entry: PublicLedgerEntry,
  locale?: Locale,
) {
  const name = resolveLedgerInstrumentName(entry, locale);
  const symbol = entry.symbol?.trim();
  if (!symbol) {
    return name;
  }
  if (!name || name === symbol) {
    return symbol;
  }
  return `${name} ${symbol}`;
}

export function resolveLedgerInstrumentName(
  entry: PublicLedgerEntry,
  locale?: Locale,
) {
  const displayName = entry.display_name?.trim();
  if (displayName) {
    return displayName;
  }
  const symbol = entry.symbol?.trim();
  if (!symbol && isCashLedgerEntry(entry)) {
    return locale === 'en' ? 'Cash account' : '人民币现金';
  }
  const noteName = readableLedgerNoteSegments(entry.note)
    .map((segment) => extractInstrumentNameFromSegment(segment, entry.symbol))
    .find(Boolean);
  return noteName ?? entry.symbol ?? '';
}

export function formatLedgerPublicNote(
  entry: PublicLedgerEntry,
  locale: Locale = 'en',
) {
  const instrumentName = resolveLedgerInstrumentName(entry).trim();
  const segments = readableLedgerNoteSegments(entry.note)
    .map((segment) => stripLedgerNotePrefix(segment).trim())
    .map((segment) =>
      stripGeneratedLedgerContextPrefix(segment, entry.symbol, instrumentName),
    )
    .filter((segment) => !isInstrumentIdentitySegment(segment, entry))
    .map((segment) => removeDuplicateSymbolFromSegment(segment, entry))
    .filter((segment) => !isGeneratedStructuredTradeNote(segment, entry))
    .filter((segment) => !isGeneratedStructuredCashNote(segment, entry))
    .filter((segment) => !isGeneratedFeeRuleNote(segment, entry))
    .map((segment) => formatLedgerPublicNoteSegment(segment, locale))
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
  const isCashEntry = isCashLedgerEntry(entry);
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
    if (isCashEntry) {
      const cashFee = sumBreakdownNumbers(
        breakdown,
        'commission',
        'stamp_tax',
        'tax',
        'transfer_fee',
        'other_fees',
      );
      if (cashFee !== null && cashFee !== 0) {
        addLine(lines, labels.fee, formatCurrency(cashFee));
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
    if (
      (!isFundLedgerEntry(entry) && !isCashEntry) ||
      (fee !== null && fee !== 0)
    ) {
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
    .split(/[|;；\r\n]+/u)
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

function parseBrokerEvidenceReference(reference: string) {
  const [sourceType, importRunId, subject, ...eventTypeParts] =
    reference.split(':');
  const eventType = eventTypeParts.join(':');
  if (
    sourceType !== 'broker_event' ||
    !importRunId ||
    !subject ||
    eventTypeParts.length === 0
  ) {
    return null;
  }

  return {
    importRunId,
    subject,
    eventType,
  };
}

function formatBrokerEvidenceTypeLabel(eventType: string, locale: Locale) {
  if (eventType === 'trade_buy' || eventType === 'trade_sell') {
    return formatLedgerEntryTypeLabel(eventType, locale);
  }
  const formatted = formatPublicEvidenceReference(
    `broker_event:import-run:subject:${eventType}`,
    locale,
  );
  return formatted.split(' · ')[2] ?? formatted;
}

function formatEvidenceSubject(
  subject: string,
  instrumentNames?: Map<string, string>,
) {
  const displayName = resolveMappedInstrumentName(subject, instrumentNames);
  if (!displayName || displayName === subject) {
    return subject;
  }
  return `${displayName} ${subject}`;
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

function isCashLedgerEntry(entry: PublicLedgerEntry) {
  return (
    entry.asset_class?.trim().toLowerCase() === 'cash' ||
    normalizeLedgerKind(entry.entry_type).startsWith('cash_')
  );
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

function formatLedgerPublicNoteSegment(segment: string, locale: Locale) {
  const normalized = segment.trim();
  if (isRawInternalNoteCode(normalized)) {
    return formatPublicNote(normalized, locale);
  }
  return normalized;
}

function isRawInternalNoteCode(segment: string) {
  return /^[a-z][a-z0-9]*(?:[._][a-z0-9]+)+$/i.test(segment);
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
    /^(?:数量|价格|手续费|佣金|份额|金额|成交|成本|成本价|净现金影响|现金影响|净额|净金额|quantity\b|price\b|fee\b|commission\b|amount\b|cost\b|cost basis\b|net cash\b|cash impact\b)/i.test(
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
    /(佣金|手续费|费率|计费|申购金额|赎回金额|买入金额|卖出金额|成交|份额|数量|价格|成本|净现金影响|现金影响|净额|净金额|元|gross|net cash|cash impact|amount|quantity|price|fee|commission|cost|basis|subscription|redemption)/i;

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
          ? /(现金入金|资金转入|入金|转入|开户时间|人民币|cash deposit|deposit)/i
          : /(现金出金|资金转出|出金|转出|cash withdrawal|withdrawal|withdraw)/i;
  return keywordPattern.test(normalized);
}

function isGeneratedFeeRuleNote(segment: string, entry: PublicLedgerEntry) {
  if (!entry.fee_breakdown && !entry.fee_rule_id && !entry.fee_rule_version) {
    return false;
  }
  return /^账户佣金配置[:：]/u.test(segment.trim());
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
    .replace(
      /^手工录入(?:持仓|基金申购|现金入金|现金出金|(?:股票|证券)?交易)[:：\-－—]\s*/,
      '',
    );
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
  const cleaned = stripGeneratedLedgerContextPrefix(
    stripLedgerNotePrefix(segment).trim(),
    symbol,
  );
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

function stripGeneratedLedgerContextPrefix(
  segment: string,
  symbol: string | null | undefined,
  instrumentName?: string | null,
) {
  const normalized = segment.trim();
  const match = normalized.match(/^.+?[:：]\s*(.+)$/u);
  if (!match) {
    return normalized;
  }
  const remainder = match[1].trim();
  return looksLikeGeneratedLedgerTradeSegment(remainder, symbol, instrumentName)
    ? remainder
    : normalized;
}

function looksLikeGeneratedLedgerTradeSegment(
  segment: string,
  symbol: string | null | undefined,
  instrumentName?: string | null,
) {
  const normalized = segment.trim();
  const hasTradeAction = /(买入|卖出|申购|赎回|buy|bought|sell|sold)/i.test(
    normalized,
  );
  if (!hasTradeAction) {
    return false;
  }

  const normalizedSymbol = symbol?.trim();
  const normalizedName = instrumentName?.trim();
  const instrumentPrefixes = [
    normalizedName,
    normalizedSymbol,
    normalizedName && normalizedSymbol
      ? `${normalizedName} ${normalizedSymbol}`
      : null,
  ].filter((value): value is string => Boolean(value));
  if (
    instrumentPrefixes.some(
      (prefix) =>
        normalized === prefix ||
        normalized.startsWith(`${prefix} `) ||
        normalized.startsWith(`${prefix}买入`) ||
        normalized.startsWith(`${prefix}卖出`) ||
        normalized.startsWith(`${prefix}申购`) ||
        normalized.startsWith(`${prefix}赎回`),
    )
  ) {
    return true;
  }

  if (
    /^[\u4e00-\u9fffA-Za-z0-9（）()·\-\s]+?\s+(?:买入|卖出|申购|赎回|buy|bought|sell|sold)/i.test(
      normalized,
    )
  ) {
    return true;
  }

  return Boolean(
    normalizedSymbol &&
    new RegExp(`(^|\\s)${escapeRegExp(normalizedSymbol)}(\\s|$)`).test(
      normalized,
    ),
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
