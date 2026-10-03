import '@testing-library/jest-dom/vitest';
import { render, screen, within } from '@testing-library/react';
import { expect, test } from 'vitest';
import type { BacktestReport } from '../api';
import { BacktestCostEvidencePanel } from './backtest-cost-evidence-panel';

const report: BacktestReport = {
  id: 1,
  created_at: '2026-01-02T08:00:00Z',
  config: {
    start_date: '2025-01-01',
    end_date: '2025-12-31',
    initial_cash: 100000,
    strategy: 'dual_ma',
    cost_assumptions: { slippage_bps: 999 },
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 100000,
    total_return: 0,
    annual_return: 0,
    sharpe: 0,
    sortino: 0,
    max_drawdown: 0,
    win_rate: 0,
    duration_days: 365,
  },
  equity_curve: [],
  metrics_json: {
    cost_assumptions: {
      schema_version: 'karkinos.backtest_cost_assumptions.v1',
      source: 'research_simulation',
      slippage_model: 'percent_of_reference_price',
      slippage_bps: '7.25',
      stock: {
        commission_rate: '0.00019',
        min_commission: '0',
        transfer_fee_rate: '0.00002',
        sell_stamp_tax_rate: '0.001',
        fee_rule_id: 'historical_recorded_rule',
      },
      etf: { commission_rate: '0', min_commission: '2' },
    },
    capacity_review: {
      schema_version: 'karkinos.backtest_capacity.v2',
      status: 'blocked',
      capacity_utilization_pct: '0.31',
      liquidity_utilization_pct: '1.25',
      max_daily_volume_participation: '0.08',
      observation_count: 2,
      fill_count: 3,
      issues: ['capacity_bar_identity_missing:2'],
    },
  },
};

test('shows the saved effective assumptions and capacity ratios, including zero fees', () => {
  render(<BacktestCostEvidencePanel report={report} />);
  expect(screen.getByText('7.25 bps')).toBeVisible();
  const stock = screen.getByRole('rowheader', { name: 'Stock' }).closest('tr')!;
  expect(within(stock).getByText('1.9')).toBeVisible();
  expect(within(stock).getByText('0')).toBeVisible();
  expect(within(stock).getByText('10')).toBeVisible();
  expect(within(stock).getByText('0.2')).toBeVisible();
  expect(screen.getByText('31%')).toBeVisible();
  expect(screen.getByText('125%')).toBeVisible();
  expect(screen.getByText('8%')).toBeVisible();
  expect(screen.getByText('2 / 3')).toBeVisible();
  expect(
    screen.getByText('Limits exceeded or evidence incomplete'),
  ).toBeVisible();
  expect(screen.getByText('capacity_bar_identity_missing:2')).toBeVisible();
  expect(screen.queryByText('999 bps')).toBeNull();
});

test('does not reconstruct old reports from submitted inputs or current defaults', () => {
  render(
    <BacktestCostEvidencePanel report={{ ...report, metrics_json: {} }} />,
  );
  expect(
    screen.getByText(/did not save its effective cost assumptions/),
  ).toBeVisible();
  expect(
    screen.getByText('No capacity check was saved with this report.'),
  ).toBeVisible();
  expect(screen.queryByRole('table')).toBeNull();
  expect(screen.queryByText('999 bps')).toBeNull();
});

test('identifies legacy capacity as a per-fill check rather than current aggregate evidence', () => {
  render(
    <BacktestCostEvidencePanel
      report={{
        ...report,
        metrics_json: {
          capacity_review: {
            ...report.metrics_json!.capacity_review!,
            schema_version: 'karkinos.backtest_capacity.v1',
            status: 'pass',
          },
        },
      }}
    />,
  );
  expect(screen.getByText(/did not aggregate same-bar fills/)).toBeVisible();
});
