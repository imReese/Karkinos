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

test('renders account metrics as a single integrated terminal rail', () => {
  renderWithPreferences(<OverviewCards overview={overview} />);

  const rail = screen.getByTestId('account-metrics-rail');
  const totalAssetsLabel = screen.getByText('Total Assets');

  expect(rail.className).toContain('font-mono');
  expect(rail.className).toContain('tabular-nums');
  expect(rail.className).toContain('app-terminal-panel');
  expect(rail.className).toContain(
    'xl:grid-cols-[1.6fr_repeat(5,minmax(0,1fr))]',
  );
  expect(totalAssetsLabel.className).toContain('font-bold');
  expect(totalAssetsLabel.className).toContain('text-[10px]');
  expect(totalAssetsLabel.className).toContain('text-[var(--app-subtext-0)]');
  expect(screen.getByText('Total Assets')).toBeTruthy();
  expect(screen.getByText('Cumulative Return')).toBeTruthy();
  expect(screen.getByText('¥1,550.00 / +1.55%')).toBeTruthy();
  expect(screen.getByText('Cash Ratio')).toBeTruthy();
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
      }}
      variant="workbench"
    />,
  );

  const rail = screen.getByTestId('account-metrics-rail');
  const coreMetrics = screen.getByTestId('account-core-metrics-stack');
  const totalAssetsValue = screen.getByTestId('overview-total-assets-value');
  const sideMetrics = screen.getByTestId('today-pnl-side-metrics');
  const drawdownPeak = screen.getByTestId('drawdown-peak-detail');

  expect(rail.className).toContain('self-start');
  expect(rail.className).toContain(
    'lg:grid-cols-[minmax(0,1.05fr)_minmax(290px,0.95fr)]',
  );
  expect(sideMetrics.className).toContain('mt-auto');
  expect(sideMetrics.textContent).toContain('Available Cash');
  expect(sideMetrics.textContent).toContain('Active Positions');
  expect(rail.className).not.toContain(
    'xl:grid-cols-[1.7fr_repeat(4,minmax(0,1fr))]',
  );
  expect(coreMetrics.className).toContain('gap-2');
  expect(coreMetrics.textContent).toBe(
    'Net Deposits¥100,000.00Unrealized PnL¥1,550.00Current Drawdown-4.80%Peak ¥106,650.00Cumulative Return¥1,550.00 / +1.55%',
  );
  expect(drawdownPeak.className).toContain('text-right');
  expect(totalAssetsValue.className).not.toContain('xl:text-5xl');
  expect(screen.getByText('¥1,550.00 / +1.55%')).toBeTruthy();
  expect(screen.getByTestId('available-cash-ratio').textContent).toBe(
    'Cash Ratio 74.8%',
  );
});

test('renders a responsive shimmering metrics rail skeleton', () => {
  render(<OverviewCardsSkeleton />);

  const skeleton = screen.getByTestId('account-metrics-skeleton');

  expect(skeleton.className).toContain('animate-pulse');
  expect(skeleton.className).toContain('app-terminal-panel');
  expect(skeleton.className).toContain(
    'xl:grid-cols-[1.6fr_repeat(5,minmax(0,1fr))]',
  );
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
