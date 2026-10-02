import { render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { BacktestReport } from '../api';
import { MetricsGrid } from './metrics-grid';

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

function report(): BacktestReport {
  return {
    id: 1,
    created_at: '2026-06-23T09:30:00+08:00',
    config: {
      start_date: '2026-01-01',
      end_date: '2026-06-20',
      initial_cash: 10000,
      strategy: 'dual_ma',
    },
    metrics: {
      initial_cash: 10000,
      final_equity: 10500,
      total_return: 0.05,
      annual_return: 0.1,
      sharpe: 1.2,
      sortino: 1.4,
      max_drawdown: 0.03,
      win_rate: 0.55,
      duration_days: 120,
    },
    equity_curve: [],
  };
}

test.each([
  [
    'en',
    'Simulated equity return; excludes dividends and other corporate actions, so this is not total economic return.',
  ],
  ['zh', '模拟权益收益；未计入分红等公司行动，不代表完整经济收益。'],
])(
  'qualifies bound Dataset return next to the metric in %s',
  (locale, note) => {
    window.localStorage.setItem('karkinos.locale', locale);
    const bound = report();
    bound.metrics_json = {
      dataset_snapshot: {
        immutable_dataset_id: 'sha256:bound-dataset',
        snapshot_id: 'sha256:backtest-snapshot',
        provider: {},
        cache: { store_available: false, metadata_available: false },
        date_range: { start: '2026-01-01', end: '2026-06-20' },
        row_count: 100,
        data_quality: { status: 'ok', issues: [] },
        symbol_universe: [],
      },
    };

    render(
      <PreferencesProvider>
        <MetricsGrid report={bound} />
      </PreferencesProvider>,
    );

    const noteElement = screen.getByText(note);
    const returnMetric = noteElement.closest('.app-metric-strip-item');
    expect(returnMetric?.textContent).toContain('5.0%');
    expect(returnMetric?.textContent).toContain(note);
  },
);

test('does not label unbound backtests as Dataset returns', () => {
  window.localStorage.setItem('karkinos.locale', 'en');

  render(
    <PreferencesProvider>
      <MetricsGrid report={report()} />
    </PreferencesProvider>,
  );

  expect(screen.queryByText(/Simulated equity return/)).toBeNull();
});

test.each([
  { price_basis: 'unadjusted' },
  { adjustment_mode: 'none' },
  {
    research_limitations: [{ code: 'unadjusted_corporate_actions_unmodeled' }],
  },
])(
  'qualifies receipt-bound raw returns from research semantics: %j',
  (semantics) => {
    window.localStorage.setItem('karkinos.locale', 'en');
    const receiptBound = report();
    receiptBound.metrics_json = {
      dataset_snapshot: {
        snapshot_id: 'sha256:receipt-bound-snapshot',
        provider: {},
        cache: { store_available: false, metadata_available: false },
        date_range: { start: '2026-01-01', end: '2026-06-20' },
        row_count: 100,
        data_quality: { status: 'ok', issues: [] },
        symbol_universe: [],
        ...semantics,
      },
    };

    render(
      <PreferencesProvider>
        <MetricsGrid report={receiptBound} />
      </PreferencesProvider>,
    );

    expect(screen.getByText(/Simulated equity return/)).toBeTruthy();
  },
);
