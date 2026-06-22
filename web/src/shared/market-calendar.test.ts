import { describe, expect, test } from 'vitest';

import {
  MARKET_CALENDAR_SCHEMA_VERSION,
  explainMarketCalendarDate,
} from './market-calendar';

describe('market calendar', () => {
  test('explains trading days, weekends, and configured market holidays', () => {
    expect(MARKET_CALENDAR_SCHEMA_VERSION).toBe('karkinos.market_calendar.v1');

    expect(explainMarketCalendarDate('2026-01-02').dayType).toBe('trading_day');
    expect(explainMarketCalendarDate('2026-01-02').isTradingDay).toBe(true);
    expect(explainMarketCalendarDate('2026-01-04').dayType).toBe('weekend');
    expect(explainMarketCalendarDate('2026-01-04').isTradingDay).toBe(false);

    const holiday = explainMarketCalendarDate('2026-01-01', {
      holidays: { '2026-01-01': "New Year's Day" },
    });

    expect(holiday.dayType).toBe('holiday');
    expect(holiday.reasonCode).toBe('market_holiday');
    expect(holiday.reason).toBe("New Year's Day");
    expect(holiday.isTradingDay).toBe(false);
  });
});
