import { render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { BacktestReport } from '../api';
import { ValidationEvidencePanel } from './validation-evidence-panel';

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

function reportWithOosStrategy(strategyId: string): BacktestReport {
  return {
    id: 1,
    created_at: '2026-06-23T09:30:00+08:00',
    config: {
      start_date: '2026-01-01',
      end_date: '2026-06-20',
      initial_cash: 10000,
      strategy: strategyId,
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
    metrics_json: {
      oos_validation: {
        strategy_id: strategyId,
        benchmark_role: 'trend_following',
        split_timestamp: '2026-03-01T00:00:00+08:00',
        validation_status: 'benchmark_passed',
        passed_benchmark: true,
        benchmark_return: 0.02,
        excess_return: 0.03,
        out_of_sample: {
          net_return: 0.05,
          fill_count: 3,
        },
        limitations: [
          'Validation evidence is not investment advice or a profitability guarantee.',
        ],
      },
    },
    equity_curve: [],
  };
}

test('shows localized strategy name before internal id in OOS evidence', () => {
  render(<ValidationEvidencePanel report={reportWithOosStrategy('dual_ma')} />);

  expect(screen.getByText('Dual Moving Average')).toBeTruthy();
  expect(screen.getByText('Audit id')).toBeTruthy();
  expect(screen.getByText('dual_ma')).toBeTruthy();
  expect(screen.queryByText('Dual Moving Average · dual_ma')).toBeNull();
  expect(screen.getByText('Trend-following benchmark')).toBeTruthy();
  expect(screen.queryByText('trend_following')).toBeNull();
});

test('localizes OOS evidence notes for Chinese report review', () => {
  window.localStorage.setItem('karkinos.locale', 'zh');

  render(
    <PreferencesProvider>
      <ValidationEvidencePanel report={reportWithOosStrategy('dual_ma')} />
    </PreferencesProvider>,
  );

  expect(
    screen.getByText('验证证据不构成投资建议，也不保证收益。'),
  ).toBeTruthy();
  expect(
    screen.queryByText(
      'Validation evidence is not investment advice or a profitability guarantee.',
    ),
  ).toBeNull();
});
