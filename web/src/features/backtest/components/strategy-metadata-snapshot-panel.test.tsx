import { render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { BacktestReport } from '../api';
import { StrategyMetadataSnapshotPanel } from './strategy-metadata-snapshot-panel';

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

function reportWithStrategySnapshot(): BacktestReport {
  return {
    id: 7,
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
    metrics_json: {
      strategy_metadata: {
        schema_version: 'karkinos.strategy_metadata.v1',
        strategy_id: 'dual_ma',
        name: 'dual_ma',
        display_name: 'Dual moving-average strategy',
        description: 'A trend-following baseline.',
        benchmark_role: 'trend_following',
        asset_universe: ['stock'],
        supported_frequencies: ['daily'],
        requires_out_of_sample_validation: true,
        requires_after_cost_report: true,
        validation_notes: ['Requires paper/shadow review before promotion.'],
        parameter_schema: [],
        params: {},
      },
    },
    equity_curve: [],
  };
}

test('shows localized strategy name before the internal strategy id in strategy snapshots', () => {
  window.localStorage.setItem('karkinos.locale', 'zh');

  render(
    <PreferencesProvider>
      <StrategyMetadataSnapshotPanel report={reportWithStrategySnapshot()} />
    </PreferencesProvider>,
  );

  expect(screen.getByText('策略')).toBeTruthy();
  expect(screen.getByText('双均线策略 · dual_ma')).toBeTruthy();
  expect(screen.getByText('策略审计标识')).toBeTruthy();
  expect(screen.getByText('股票')).toBeTruthy();
  expect(screen.getByText('日线')).toBeTruthy();
  expect(screen.getByText('进入人工复核前，需要完成模拟盘复盘。')).toBeTruthy();
  expect(screen.queryByText('策略 ID')).toBeNull();
  expect(screen.queryByText('内部策略标识')).toBeNull();
  expect(screen.queryByText('stock')).toBeNull();
  expect(screen.queryByText('daily')).toBeNull();
  expect(
    screen.queryByText('Requires paper/shadow review before promotion.'),
  ).toBeNull();
});

test('labels strategy ids as audit metadata without internal wording', () => {
  render(
    <PreferencesProvider>
      <StrategyMetadataSnapshotPanel report={reportWithStrategySnapshot()} />
    </PreferencesProvider>,
  );

  expect(screen.getByText('Strategy audit id')).toBeTruthy();
  expect(screen.getByText('dual_ma')).toBeTruthy();
  expect(screen.queryByText('Internal strategy id')).toBeNull();
});
