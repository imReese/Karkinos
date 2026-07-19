import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { PortfolioSnapshot } from '../../portfolio/api';
import type { AccountOverview } from '../api';
import { OverviewCards, OverviewCardsSkeleton } from './overview-cards';
import { PerformanceBreakdownCard } from './performance-breakdown-card';

function renderWithPreferences(ui: ReactNode) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  render(<PreferencesProvider>{ui}</PreferencesProvider>);
}

const overview: AccountOverview = {
  total_equity: 101_550,
  available_cash: 76_000,
  total_deposits: 100_000,
  positions_count: 5,
  unrealized_pnl: 1_550,
  realized_pnl: 220,
  cash_ratio: 0.7484,
};

const snapshot: PortfolioSnapshot = {
  cash: 76_000,
  total_equity: 101_550,
  total_deposits: 100_000,
  positions: [],
  allocation: [],
  allocation_grouped: [],
};

test('renders canonical account facts as a compact metric strip', () => {
  renderWithPreferences(<OverviewCards overview={overview} />);

  const rail = screen.getByTestId('account-metrics-rail');
  const strip = rail.querySelector('dl');

  expect(rail.className).toContain('min-w-0');
  expect(strip?.className).toContain('account-metric-strip');
  expect(strip?.className).not.toContain('font-mono');
  expect(strip?.className).toContain('tabular-nums');
  expect(screen.getByText('Total Assets')).toBeTruthy();
  expect(screen.getByText('Realized PnL')).toBeTruthy();
  expect(screen.getByText('Available Cash')).toBeTruthy();
  expect(screen.getByText('Cash Ratio 74.8%')).toBeTruthy();
  expect(screen.queryByText('Cumulative Return')).toBeNull();
});

test('shows current drawdown as a signed downside metric', () => {
  renderWithPreferences(
    <OverviewCards
      overview={{
        ...overview,
        current_drawdown: 0.048,
      }}
    />,
  );

  expect(screen.getByText('Current Drawdown')).toBeTruthy();
  expect(screen.getByText('-4.80%')).toBeTruthy();
});

test('renders account metrics in a compact homepage workbench layout', () => {
  renderWithPreferences(
    <OverviewCards
      overview={{
        ...overview,
        current_drawdown: 0.048,
        drawdown_peak_equity: 106_650,
        valuation_snapshot_id: 'valuation-private-fixture',
        valuation_as_of: '2026-02-10T15:00:00+08:00',
        ledger_cutoff_id: 42,
        quote_status: 'confirmed',
      }}
      variant="workbench"
    />,
  );

  const rail = screen.getByTestId('account-metrics-rail');
  const totalAssetsValue = screen.getByTestId('overview-total-assets-value');

  expect(rail.className).toContain('self-start');
  expect(totalAssetsValue.className).toContain('account-primary-metric-value');
  expect(rail.querySelector('.account-overview-summary')).toBeTruthy();
  expect(screen.getByLabelText('Supporting account metrics')).toBeTruthy();
  expect(screen.getByText('Evidence complete')).toBeTruthy();
  expect(
    screen.getByText('Valuation as of 02-10 15:00 · ledger cutoff 42'),
  ).toBeTruthy();
  expect(screen.queryByText(/valuation-private-fixture/)).toBeNull();
  expect(screen.getByText('Peak ¥106,650.00')).toBeTruthy();
  expect(screen.getByText('Cash Ratio 74.8%')).toBeTruthy();
  expect(screen.getByText('¥220.00')).toBeTruthy();
  expect(screen.queryByText(/\+1\.55%/)).toBeNull();
});

test('renders a responsive shimmering metrics rail skeleton', () => {
  render(<OverviewCardsSkeleton />);

  const skeleton = screen.getByTestId('account-metrics-skeleton');

  expect(skeleton.className).toContain('animate-pulse');
  expect(skeleton.className).toContain('account-overview-summary');
  expect(skeleton.className).not.toContain('rounded-');
  expect(skeleton.querySelector('.account-primary-metric')).toBeTruthy();
  expect(skeleton.querySelectorAll('.app-metric-strip-item')).toHaveLength(5);
});

test('shows cached quote copy on stale overview metrics', () => {
  renderWithPreferences(
    <OverviewCards
      overview={{
        ...overview,
        valuation_timestamp: '2026-05-16T22:40:00+08:00',
        quote_status: 'stale',
      }}
    />,
  );

  expect(screen.getByText(/Cached quotes · valuation time/)).toBeTruthy();
});

test('treats a persisted complete valuation with snapshot identity as ready', () => {
  renderWithPreferences(
    <OverviewCards
      overview={{
        ...overview,
        valuation_snapshot_id: 'valuation-complete-fixture',
        valuation_status: 'complete',
        valuation_as_of: '2026-02-10T15:00:00+08:00',
        ledger_cutoff_id: 42,
      }}
      variant="workbench"
    />,
  );

  expect(screen.getByText('Evidence complete')).toBeTruthy();
  expect(
    screen
      .getByTestId('account-metrics-rail')
      .querySelector('[data-evidence-kind="ready"]'),
  ).toBeTruthy();
});

test('keeps the localized perspective switcher in the breakdown header', async () => {
  const user = userEvent.setup();
  const onModeChange = vi.fn();

  renderWithPreferences(
    <PerformanceBreakdownCard
      overview={overview}
      snapshot={snapshot}
      mode="account"
      onModeChange={onModeChange}
      accountLabel="Account Perspective"
      strategyLabel="Strategy Perspective"
    />,
  );

  const switcher = screen.getByTestId('breakdown-perspective-switcher');
  expect(switcher.className).toContain('rounded-full');
  expect(
    screen
      .getByRole('button', { name: 'Account Perspective' })
      .getAttribute('aria-pressed'),
  ).toBe('true');

  await user.click(
    screen.getByRole('button', { name: 'Strategy Perspective' }),
  );

  expect(onModeChange).toHaveBeenCalledWith('strategy');
});
