import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { PortfolioSnapshot } from '../api';
import { PortfolioPageController } from './portfolio-page-controller';

vi.mock('@tanstack/react-router', () => ({
  getRouteApi: () => ({
    useSearch: () => ({ q: '', assetClass: 'all', pnl: 'all' }),
  }),
  useNavigate: () => vi.fn(),
}));

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  usePortfolioSnapshotQuery: () => ({ data: snapshot }),
  usePortfolioCockpitQuery: () => ({ data: undefined }),
  useLiveHoldingsQuery: () => ({ data: undefined }),
}));

vi.mock('../portfolio-feature-boundary', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../portfolio-feature-boundary')>()),
  useAccountStrategyContributionQuery: () => ({ data: undefined }),
  useDailyTradingPlanQuery: () => ({ data: undefined }),
}));

vi.mock('./portfolio-page-sections', () => ({
  PortfolioCurrentHoldingsSection: () => null,
  PortfolioAnalysisSection: () => null,
  PortfolioHistorySection: () => null,
}));

let snapshot: PortfolioSnapshot;

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  snapshot = {
    cash: 100,
    total_equity: 2100,
    total_market_value: 2000,
    total_today_change: 25,
    total_unrealized_pnl: 500,
    total_unrealized_pnl_pct: 0.3333,
    performance_session_date: '2026-10-08',
    total_deposits: 1600,
    // Position details are deliberately separate from the canonical totals.
    positions: [
      {
        symbol: '600001',
        quantity: 10,
        available_qty: 10,
        frozen_qty: 0,
        avg_cost: 100,
        market_value: 1000,
        today_change: 10,
        unrealized_pnl: 100,
        realized_pnl: 0,
        commission_paid: 0,
      },
    ],
    allocation: [],
    allocation_grouped: [],
  };
});

afterEach(cleanup);

function renderSummary() {
  render(
    <PreferencesProvider>
      <QueryClientProvider client={new QueryClient()}>
        <PortfolioPageController />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return screen.getByTestId('portfolio-summary-strip');
}

function valueFor(summary: HTMLElement, label: string) {
  return within(summary).getByText(label).closest('div')!.querySelector('dd')!;
}

test('shows canonical snapshot totals and the bound session date', () => {
  const summary = renderSummary();
  expect(valueFor(summary, 'Market value').textContent).toContain('2,000.00');
  expect(valueFor(summary, 'Session P&L').textContent).toContain('25.00');
  expect(valueFor(summary, 'Unrealized PnL').textContent).toContain('500.00');
  expect(summary.textContent).toContain('2026-10-08');
});

test('does not reconstruct missing canonical totals from partial position facts', () => {
  snapshot.total_equity = null;
  snapshot.total_market_value = null;
  snapshot.total_today_change = null;
  snapshot.total_unrealized_pnl = null;
  snapshot.total_unrealized_pnl_pct = null;
  snapshot.performance_session_date = null;
  const summary = renderSummary();
  expect(valueFor(summary, 'Market value').textContent).toBe('--');
  expect(valueFor(summary, 'Session P&L').textContent).toBe('--');
  expect(valueFor(summary, 'Unrealized PnL').textContent).toBe('--');
  expect(valueFor(summary, 'Cash').textContent).toContain('100.00');
});
