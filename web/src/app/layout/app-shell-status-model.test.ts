import { describe, expect, it } from 'vitest';

import { copy } from '../copy';
import {
  deriveToolbarStatusModel,
  formatToolbarTimestamp,
} from './app-shell-status-model';

describe('formatToolbarTimestamp', () => {
  const referenceDate = new Date('2026-09-22T12:00:00+08:00');

  it('returns null for empty or invalid values', () => {
    expect(formatToolbarTimestamp(null, 'zh', referenceDate)).toBeNull();
    expect(formatToolbarTimestamp(undefined, 'zh', referenceDate)).toBeNull();
    expect(
      formatToolbarTimestamp('not-a-date', 'zh', referenceDate),
    ).toBeNull();
    expect(
      formatToolbarTimestamp(new Date('invalid'), 'zh', referenceDate),
    ).toBeNull();
  });

  it('formats same-day timestamp as HH:mm', () => {
    expect(
      formatToolbarTimestamp('2026-09-22T11:29:00+08:00', 'zh', referenceDate),
    ).toBe('11:29');
    expect(
      formatToolbarTimestamp('2026-09-22T03:29:00Z', 'zh', referenceDate),
    ).toBe('11:29');
    expect(
      formatToolbarTimestamp('2026-09-22 11:29', 'zh', referenceDate),
    ).toBe('11:29');
    expect(
      formatToolbarTimestamp(
        new Date('2026-09-22T11:29:00+08:00'),
        'zh',
        referenceDate,
      ),
    ).toBe('11:29');
  });

  it('formats cross-day timestamp in same year as MM-DD HH:mm', () => {
    expect(
      formatToolbarTimestamp('2026-09-21T15:00:00+08:00', 'zh', referenceDate),
    ).toBe('09-21 15:00');
    expect(
      formatToolbarTimestamp('2026-05-16T22:40:00+08:00', 'zh', referenceDate),
    ).toBe('05-16 22:40');
    expect(
      formatToolbarTimestamp(
        new Date('2026-05-16T22:40:00+08:00'),
        'zh',
        referenceDate,
      ),
    ).toBe('05-16 22:40');
  });

  it('formats cross-year timestamp as YYYY-MM-DD HH:mm', () => {
    expect(
      formatToolbarTimestamp('2025-12-31T15:00:00+08:00', 'zh', referenceDate),
    ).toBe('2025-12-31 15:00');
    expect(
      formatToolbarTimestamp(
        new Date('2025-12-31T15:00:00+08:00'),
        'zh',
        referenceDate,
      ),
    ).toBe('2025-12-31 15:00');
  });
});

describe('deriveToolbarStatusModel', () => {
  const referenceDate = new Date('2026-09-22T12:00:00+08:00');

  it('formats same-day valuation and market timestamps compactly', () => {
    const model = deriveToolbarStatusModel({
      accountOverview: {
        data: {
          valuation_timestamp: '2026-09-22T11:55:00+08:00',
          quote_status: 'live',
        },
        isError: false,
        isLoading: false,
      },
      marketHealth: {
        data: {
          market_open: true,
          refresh_policy: 'live',
          source_health: 'healthy',
          latest_quote_timestamp: '2026-09-22T11:30:00+08:00',
        },
        isError: false,
        isLoading: false,
      },
      locale: 'zh',
      copy: copy.zh,
      now: referenceDate,
    });

    expect(model.valuationTimestamp).toBe('11:55');
    expect(model.valuationMeta).toBe('估值 11:55');
    expect(model.marketTimestamp).toBe('11:30');
  });

  it('displays date prefix for historical cached quotes', () => {
    const model = deriveToolbarStatusModel({
      accountOverview: {
        data: {
          valuation_timestamp: '2026-09-22T11:55:00+08:00',
          quote_status: 'stale',
        },
        isError: false,
        isLoading: false,
      },
      marketHealth: {
        data: {
          market_open: true,
          refresh_policy: 'live',
          source_health: 'stale',
          latest_quote_timestamp: '2026-09-21T15:00:00+08:00',
        },
        isError: false,
        isLoading: false,
      },
      locale: 'zh',
      copy: copy.zh,
      now: referenceDate,
    });

    expect(model.valuationTimestamp).toBe('11:55');
    expect(model.marketTimestamp).toBe('09-21 15:00');
  });
});
