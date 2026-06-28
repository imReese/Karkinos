export const MARKET_CALENDAR_SCHEMA_VERSION = 'karkinos.market_calendar.v1';

export type MarketCalendarDayType =
  | 'trading_day'
  | 'weekend'
  | 'holiday'
  | 'closed';

export type MarketCalendarDay = {
  schemaVersion: typeof MARKET_CALENDAR_SCHEMA_VERSION;
  date: string;
  dayType: MarketCalendarDayType;
  reasonCode:
    | 'trading_day'
    | 'extra_trading_day'
    | 'weekend'
    | 'market_holiday'
    | 'market_closed';
  reason: string;
  isTradingDay: boolean;
};

export type MarketCalendarOptions = {
  holidays?: Record<string, string>;
  extraTradingDays?: string[];
  closedDays?: Record<string, string>;
};

const DEFAULT_MARKET_HOLIDAYS: Record<string, string> = Object.freeze({});

export function explainMarketCalendarDate(
  value: string | Date,
  options: MarketCalendarOptions = {},
): MarketCalendarDay {
  const dateText = normalizeCalendarDate(value);
  const holidays = { ...DEFAULT_MARKET_HOLIDAYS, ...(options.holidays ?? {}) };
  const extraTradingDays = new Set(options.extraTradingDays ?? []);
  const closedDays = options.closedDays ?? {};

  if (extraTradingDays.has(dateText)) {
    return buildMarketCalendarDay({
      date: dateText,
      dayType: 'trading_day',
      reasonCode: 'extra_trading_day',
      reason: 'Configured trading day',
      isTradingDay: true,
    });
  }

  if (closedDays[dateText]) {
    return buildMarketCalendarDay({
      date: dateText,
      dayType: 'closed',
      reasonCode: 'market_closed',
      reason: closedDays[dateText],
      isTradingDay: false,
    });
  }

  if (holidays[dateText]) {
    return buildMarketCalendarDay({
      date: dateText,
      dayType: 'holiday',
      reasonCode: 'market_holiday',
      reason: holidays[dateText],
      isTradingDay: false,
    });
  }

  const date = new Date(`${dateText}T00:00:00`);
  if (date.getDay() === 0 || date.getDay() === 6) {
    return buildMarketCalendarDay({
      date: dateText,
      dayType: 'weekend',
      reasonCode: 'weekend',
      reason: 'Weekend',
      isTradingDay: false,
    });
  }

  return buildMarketCalendarDay({
    date: dateText,
    dayType: 'trading_day',
    reasonCode: 'trading_day',
    reason: 'Trading day',
    isTradingDay: true,
  });
}

function buildMarketCalendarDay(
  day: Omit<MarketCalendarDay, 'schemaVersion'>,
): MarketCalendarDay {
  return {
    schemaVersion: MARKET_CALENDAR_SCHEMA_VERSION,
    ...day,
  };
}

function normalizeCalendarDate(value: string | Date) {
  if (value instanceof Date) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(
      2,
      '0',
    )}-${String(value.getDate()).padStart(2, '0')}`;
  }
  return value.slice(0, 10);
}
