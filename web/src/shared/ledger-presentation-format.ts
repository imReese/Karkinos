import { formatCurrency } from './format';
import type { Locale } from './locale';
import type {
  LedgerActivitySummary,
  LedgerDashboardPresentation,
  LedgerEntrySummary,
  LedgerExecutionDetailLabels,
  LedgerExplainabilityItem,
  PublicLedgerEntry,
} from './ledger-format-contracts';
import { formatLedgerExecutionDetailLines } from './ledger-execution-format';
import {
  ACTIVITY_LABELS,
  COST_BASIS_METHOD_LABELS,
  ENTRY_TYPE_LABELS,
  EXPLAINABILITY_DETAIL_LABELS,
  FEE_RULE_LABELS,
  SOURCE_LABELS,
} from './ledger-format-labels';
import {
  formatLedgerInstrumentLabel,
  formatLedgerPublicNote,
} from './ledger-note-format';
import {
  escapeRegExp,
  finiteNumber,
  formatSignedCurrency,
  isCashLedgerEntry,
  normalizeLedgerKind,
} from './ledger-format-values';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from './public-labels';

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
  const entry = toExplainabilityLedgerEntry(item, instrumentNames);
  const normalizedKind = normalizeLedgerKind(entry.entry_type);
  if (
    normalizedKind === 'other' &&
    !isGeneratedExplainabilityTitle(item) &&
    item.title
  ) {
    return item.title;
  }
  const entryType = formatLedgerEntryTypeLabel(entry, locale);
  const shouldShowInstrument =
    !isCashLedgerEntry(entry) || Boolean(entry.symbol || entry.display_name);
  const symbol = entry.symbol?.trim() ?? '';
  const mappedName = entry.display_name?.trim() ?? '';
  const title = item.title?.trim() ?? '';
  const titleContainsSymbol = Boolean(
    symbol &&
    new RegExp(`(^|\\s)${escapeRegExp(symbol)}(\\s|$)`, 'u').test(title),
  );
  const titleInstrumentName = titleContainsSymbol
    ? title
        .replace(
          /^(?:bought|sold|buy|sell|purchase|redeem|dividend|买入|卖出|申购|赎回|分红)\s*/iu,
          '',
        )
        .replace(new RegExp(`\\s*${escapeRegExp(symbol)}$`, 'u'), '')
        .trim()
    : '';
  const instrumentName = mappedName || titleInstrumentName;
  const instrument = shouldShowInstrument
    ? symbol
      ? instrumentName
        ? `${instrumentName} ${symbol}`
        : symbol
      : instrumentName
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
  const publicNote = formatExplainabilityPublicNote(
    formatLedgerPublicNote(entry, locale),
    item,
    locale,
  );
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

function formatExplainabilityPublicNote(
  note: string | null,
  item: LedgerExplainabilityItem,
  locale: Locale,
) {
  const normalized = note?.trim();
  if (!normalized) return null;

  const kind = normalizeLedgerKind(item.kind ?? '');
  if (
    (kind === 'cash_deposit' && /^现金流入组合[。.]?$/u.test(normalized)) ||
    (kind === 'cash_withdrawal' && /^现金流出组合[。.]?$/u.test(normalized)) ||
    (kind === 'cash_interest' &&
      /^现金(?:利息|结息)[。.]?$/u.test(normalized)) ||
    (kind === 'dividend' && /^.+现金分红[。.]?$/u.test(normalized)) ||
    ((kind === 'trade_buy' || kind === 'trade_sell') &&
      /^[\u4e00-\u9fffA-Za-z0-9（）()·\-\s]+\s+(?:买入|卖出|申购|赎回)[。.]?$/u.test(
        normalized,
      ))
  ) {
    return null;
  }

  const sourceNote = normalized.match(/^(?:用户补录|手工记录)[:：]\s*(.+)$/u);
  if (sourceNote?.[1]) {
    return locale === 'zh'
      ? `用户补录：${sourceNote[1]}`
      : `User note (source text): ${sourceNote[1]}`;
  }

  if (locale === 'en' && /[\u4e00-\u9fff]/u.test(normalized)) {
    return `Source note: ${normalized}`;
  }
  if (locale === 'zh' && /[A-Za-z]/u.test(normalized)) {
    return `来源备注：${normalized}`;
  }
  return normalized;
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
