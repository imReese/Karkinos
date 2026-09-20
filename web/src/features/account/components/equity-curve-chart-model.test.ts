import { expect, test } from 'vitest';

import type { EquitySeriesPoint } from '../api';
import {
  filterByRange,
  padRangeWithZeroBaseline,
  resolveRangeStartTimestamp,
  resolveXAxisDomain,
  resolveXAxisTicks,
  toChartPoints,
} from './equity-curve-chart-model';

function point(timestamp: string, total: number): EquitySeriesPoint {
  return {
    timestamp,
    total,
    stocks: total,
    funds: 0,
    others: 0,
    cash: 0,
    quote_status: 'live',
    valuation_status: 'reconstructed',
  };
}

test('year-to-date pads the pre-account part of the year with a flat zero baseline', () => {
  const padded = padRangeWithZeroBaseline(
    [
      point('2026-04-01T15:00:00+08:00', 3000),
      point('2026-04-02T15:00:00+08:00', 3000),
    ],
    'ytd',
  );

  expect(padded).toHaveLength(4);
  expect(padded[0]?.total).toBe(0);
  expect(padded[1]?.total).toBe(0);
  expect(new Date(padded[0]?.timestamp ?? '').getTime()).toBe(
    new Date('2026-01-01T00:00:00+08:00').getTime(),
  );
  expect(padded[1]?.timestamp.slice(0, 10)).toBe('2026-03-31');
  expect(padded[2]?.timestamp.slice(0, 10)).toBe('2026-04-01');
  expect(padded[2]?.total).toBe(3000);
});

test('six-month range uses exact calendar-month semantics', () => {
  const latest = new Date('2026-09-18T15:00:00+08:00').getTime();
  expect(resolveRangeStartTimestamp(latest, '6m')).toBe(
    new Date('2026-03-18T15:00:00+08:00').getTime(),
  );
});

test('six-month range pads missing pre-account history with zero', () => {
  const padded = padRangeWithZeroBaseline(
    [
      point('2026-04-01T15:00:00+08:00', 3000),
      point('2026-09-18T15:00:00+08:00', 19000),
    ],
    '6m',
  );
  expect(padded[0]?.timestamp.slice(0, 10)).toBe('2026-03-18');
  expect(padded[0]?.total).toBe(0);
  expect(padded[1]?.timestamp.slice(0, 10)).toBe('2026-03-31');
  expect(padded[1]?.total).toBe(0);
  expect(padded[2]?.timestamp.slice(0, 10)).toBe('2026-04-01');
  expect(padded[2]?.total).toBe(3000);
});

test('year-to-date filters prior-year points but keeps the calendar axis anchored at January 1', () => {
  const points = toChartPoints([
    point('2025-12-31T15:00:00+08:00', 100),
    point('2026-04-01T15:00:00+08:00', 110),
    point('2026-09-18T15:00:00+08:00', 120),
  ]);

  const filtered = filterByRange(points, 'ytd');
  expect(filtered.map((item) => item.timestamp.slice(0, 10))).toEqual([
    '2026-04-01',
    '2026-09-18',
  ]);

  const domain = resolveXAxisDomain(filtered, 'ytd');
  expect(domain).toEqual([
    new Date('2026-01-01T00:00:00+08:00').getTime(),
    new Date('2026-09-18T15:00:00+08:00').getTime(),
  ]);

  const ticks = resolveXAxisTicks(filtered, 'ytd');
  expect(ticks[0]).toBe(new Date('2026-01-01T00:00:00+08:00').getTime());
});
