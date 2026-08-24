import type { AppCopy } from '../../../shared/i18n/context';
import {
  formatCurrency as formatCurrencyValue,
  formatPercent as formatPercentValue,
} from '../../../shared/format';
import {
  MARKET_CALENDAR_SCHEMA_VERSION,
  type MarketCalendarDay,
  type MarketCalendarDayType,
} from '../../../shared/market-calendar';

export type ReturnCalendarPeriod = 'day' | 'week' | 'month' | 'year';
export type ReturnCalendarMetric = 'amount' | 'percent';
export type ReturnCalendarViewMode = 'calendar' | 'table' | 'curve';

export type ReturnCalendarBreakdownItem = {
  key: string;
  label: string;
  value: number;
};

export type ReturnCalendarTimelinePoint = {
  date: string;
  equity: number;
  delta: number;
  external_flow: number;
  market_pnl: number;
  valuation_status?: string;
  missing_price_symbols?: string[];
  market_breakdown?: ReturnCalendarBreakdownItem[];
  external_flow_breakdown?: ReturnCalendarBreakdownItem[];
};

export type ReturnCalendarRow = {
  label: string;
  delta: number;
  externalFlow: number;
  marketPnl: number;
  percentChange: number;
  valuationStatus: string;
  missingPriceSymbols: string[];
  marketBreakdown: ReturnCalendarBreakdownItem[];
  externalFlowBreakdown: ReturnCalendarBreakdownItem[];
};

export type ReturnCalendarPosition = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  asset_class?: string | null;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
};

export type ReturnCalendarMarketCalendar = {
  status: string;
  days: Array<{
    schema_version: string;
    date: string;
    day_type: MarketCalendarDayType;
    reason_code: MarketCalendarDay['reasonCode'];
    reason: string;
    is_trading_day: boolean;
  }>;
};

export function aggregateReturnTimeline(
  timeline: ReturnCalendarTimelinePoint[],
  bucket: ReturnCalendarPeriod,
) {
  const groups = new Map<
    string,
    {
      label: string;
      delta: number;
      externalFlow: number;
      marketPnl: number;
      startEquity: number;
      endEquity: number;
      valuationStatus: string;
      missingPriceSymbols: Set<string>;
      marketBreakdown: Map<string, ReturnCalendarBreakdownItem>;
      externalFlowBreakdown: Map<string, ReturnCalendarBreakdownItem>;
    }
  >();

  timeline.forEach((point) => {
    const label = toReturnBucket(point.date, bucket);
    const existing = groups.get(label);
    const previousEquity = point.equity - point.delta;
    const missingPriceSymbols = point.missing_price_symbols ?? [];
    const valuationStatus =
      missingPriceSymbols.length > 0
        ? 'missing'
        : normalizeValuationStatus(point.valuation_status);
    if (existing) {
      existing.delta += point.delta;
      existing.externalFlow += point.external_flow;
      existing.marketPnl += point.market_pnl;
      existing.endEquity = point.equity;
      existing.valuationStatus = combineValuationStatus(
        existing.valuationStatus,
        valuationStatus,
      );
      mergeBreakdownItems(existing.marketBreakdown, point.market_breakdown);
      mergeBreakdownItems(
        existing.externalFlowBreakdown,
        point.external_flow_breakdown,
      );
      missingPriceSymbols.forEach((symbol) =>
        existing.missingPriceSymbols.add(symbol),
      );
      return;
    }
    groups.set(label, {
      label,
      delta: point.delta,
      externalFlow: point.external_flow,
      marketPnl: point.market_pnl,
      startEquity: previousEquity,
      endEquity: point.equity,
      valuationStatus,
      missingPriceSymbols: new Set(missingPriceSymbols),
      marketBreakdown: buildBreakdownMap(point.market_breakdown),
      externalFlowBreakdown: buildBreakdownMap(point.external_flow_breakdown),
    });
  });

  return Array.from(groups.values()).map((row) => ({
    ...row,
    missingPriceSymbols: Array.from(row.missingPriceSymbols).sort(),
    marketBreakdown: Array.from(row.marketBreakdown.values()).filter(
      (item) => Math.abs(item.value) > 0.000001,
    ),
    externalFlowBreakdown: Array.from(
      row.externalFlowBreakdown.values(),
    ).filter((item) => Math.abs(item.value) > 0.000001),
    percentChange:
      row.startEquity === 0 ? 0 : row.marketPnl / Math.abs(row.startEquity),
  }));
}

function buildBreakdownMap(items: ReturnCalendarBreakdownItem[] | undefined) {
  const map = new Map<string, ReturnCalendarBreakdownItem>();
  mergeBreakdownItems(map, items);
  return map;
}

function mergeBreakdownItems(
  target: Map<string, ReturnCalendarBreakdownItem>,
  items: ReturnCalendarBreakdownItem[] | undefined,
) {
  (items ?? []).forEach((item) => {
    const existing = target.get(item.key);
    if (existing) {
      target.set(item.key, {
        ...existing,
        value: existing.value + item.value,
      });
      return;
    }
    target.set(item.key, { ...item });
  });
}

function normalizeValuationStatus(status: string | undefined) {
  const normalized =
    status
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_') ?? '';
  if (
    ['missing', 'unavailable', 'missing_price_symbols'].includes(normalized)
  ) {
    return 'missing';
  }
  if (
    [
      'partial',
      'cache',
      'cached',
      'cache_only',
      'estimated',
      'estimate',
      'stale',
      'quote_older_than_expected_session',
      'confirmed_nav_missing',
      'confirmed_fund_nav_missing_estimate_only',
    ].includes(normalized)
  ) {
    return 'partial';
  }
  return 'complete';
}

function combineValuationStatus(left: string, right: string) {
  if (left === 'missing' || right === 'missing') {
    return 'missing';
  }
  if (left === 'partial' || right === 'partial') {
    return 'partial';
  }
  return 'complete';
}

function toReturnBucket(dateText: string, bucket: ReturnCalendarPeriod) {
  if (bucket === 'day') {
    return dateText;
  }
  const date = new Date(`${dateText}T00:00:00`);
  if (bucket === 'month') {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  }
  if (bucket === 'year') {
    return `${date.getFullYear()}`;
  }
  return toReturnWeekBucket(date);
}

function toReturnWeekBucket(date: Date) {
  const year = date.getFullYear();
  const slot = buildReturnWeekSlots(String(year)).find(
    (item) => date >= item.startDate && date <= item.endDate,
  );
  return slot?.label ?? `${year}-W01`;
}

export function buildReturnWeekSlots(yearText: string) {
  const year = Number(yearText);
  if (!Number.isFinite(year)) {
    return [];
  }

  const slots: Array<{
    label: string;
    weekNumber: number;
    startDate: Date;
    endDate: Date;
    rangeLabel: string;
  }> = [];
  const yearEnd = new Date(year, 11, 31);
  const cursor = new Date(year, 0, 1);
  let weekNumber = 1;

  while (cursor <= yearEnd) {
    const startDate = new Date(cursor);
    const endDate = new Date(cursor);
    endDate.setDate(endDate.getDate() + (6 - startDate.getDay()));
    if (endDate > yearEnd) {
      endDate.setTime(yearEnd.getTime());
    }

    slots.push({
      label: `${year}-W${String(weekNumber).padStart(2, '0')}`,
      weekNumber,
      startDate,
      endDate,
      rangeLabel: `${formatReturnMonthDay(startDate)}-${formatReturnMonthDay(
        endDate,
      )}`,
    });

    cursor.setTime(endDate.getTime());
    cursor.setDate(cursor.getDate() + 1);
    weekNumber += 1;
  }

  return slots;
}

export function formatReturnWeekHeading(weekNumber: number, copy: AppCopy) {
  if (copy.explainability.week === '周') {
    return `第${weekNumber}周`;
  }
  return `${copy.explainability.week} ${weekNumber}`;
}

export function formatReturnCalendarDetailTitle(
  row: ReturnCalendarRow,
  period: ReturnCalendarPeriod,
  copy: AppCopy,
) {
  if (period !== 'week') {
    return row.label;
  }

  const match = /^(\d{4})-W(\d{2})$/.exec(row.label);
  const slot = match
    ? buildReturnWeekSlots(match[1]).find(
        (item) => item.weekNumber === Number(match[2]),
      )
    : null;
  if (!slot) {
    return row.label;
  }

  return `${formatReturnWeekHeading(slot.weekNumber, copy)} · ${
    slot.rangeLabel
  }`;
}

function formatReturnMonthDay(date: Date) {
  return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(
    date.getDate(),
  ).padStart(2, '0')}`;
}

export function formatReturnPercent(value: number) {
  return formatPercentValue(value, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}

export function formatReturnCurrency(value: number) {
  return formatCurrencyValue(value);
}

export function formatCompactReturnCurrency(value: number) {
  if (value === 0) {
    return '0';
  }
  const sign = value > 0 ? '+' : '-';
  const absoluteValue = Math.abs(value);
  if (absoluteValue < 10) {
    return `${sign}${absoluteValue.toFixed(1)}`;
  }
  if (absoluteValue < 1_000) {
    return `${sign}${Math.round(absoluteValue)}`;
  }

  const { divisor, suffix } =
    absoluteValue >= 1_000_000_000
      ? { divisor: 1_000_000_000, suffix: 'b' }
      : absoluteValue >= 1_000_000
        ? { divisor: 1_000_000, suffix: 'm' }
        : { divisor: 1_000, suffix: 'k' };
  const scaledValue = absoluteValue / divisor;
  const compactValue = scaledValue
    .toFixed(scaledValue < 10 ? 1 : 0)
    .replace(/\.0$/, '');
  return `${sign}${compactValue}${suffix}`;
}

export function summarizeReturnCalendarStatus(rows: ReturnCalendarRow[]) {
  if (rows.some((row) => row.valuationStatus === 'missing')) {
    return 'missing';
  }
  if (rows.some((row) => row.valuationStatus === 'partial')) {
    return 'partial';
  }
  return 'complete';
}

export function buildMarketCalendarDayMap(
  marketCalendar?: ReturnCalendarMarketCalendar | null,
) {
  const days =
    marketCalendar?.status === 'missing' ? [] : (marketCalendar?.days ?? []);
  return new Map(
    days.map((day) => [
      day.date,
      {
        schemaVersion: MARKET_CALENDAR_SCHEMA_VERSION,
        date: day.date,
        dayType: day.day_type,
        reasonCode: day.reason_code,
        reason: day.reason,
        isTradingDay: day.is_trading_day,
      } satisfies MarketCalendarDay,
    ]),
  );
}
