import type { Locale } from './locale';
import type { PublicLedgerEntry } from './ledger-format-contracts';
import { formatPublicNote } from './public-labels';
import {
  escapeRegExp,
  finiteNumber,
  isCashLedgerEntry,
  normalizeLedgerKind,
} from './ledger-format-values';

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

export function readableLedgerNoteSegments(note: string | null | undefined) {
  if (!note) {
    return [];
  }
  return note
    .split(/[|;；\r\n]+/u)
    .map((segment) => segment.trim())
    .filter((segment) => segment && !isTechnicalNoteSegment(segment));
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
      /^手工记录[:：]\s*(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?\s*)?/u,
      '',
    )
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
