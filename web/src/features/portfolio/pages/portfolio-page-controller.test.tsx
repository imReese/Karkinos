import '@testing-library/jest-dom/vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { PortfolioSnapshot } from '../api';
import { PortfolioPageController } from './portfolio-page-controller';

const { navigate, searchState } = vi.hoisted(() => ({
  navigate: vi.fn(),
  searchState: { q: '', assetClass: 'all', pnl: 'all' },
}));

vi.mock('@tanstack/react-router', () => ({
  getRouteApi: () => ({
    useSearch: () => searchState,
  }),
  useNavigate: () => navigate,
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

// Keep the actual controller, model, holdings section and table; omit unrelated analysis.
vi.mock('./portfolio-page-view', async () => {
  const { PortfolioCurrentHoldingsSection } =
    await import('./portfolio-page-sections');
  return { PortfolioPageView: PortfolioCurrentHoldingsSection };
});

const snapshot: PortfolioSnapshot = {
  cash: 100,
  total_equity: 500,
  total_deposits: 400,
  positions: [1, 2].map((index) => ({
    symbol: `60000${index}`,
    display_name: `Fixture ${index}`,
    asset_class: 'stock',
    quantity: 10,
    available_qty: 10,
    frozen_qty: 0,
    avg_cost: 10,
    market_value: 100 + index * 100,
    today_change: index * 10,
    today_change_pct: index,
    unrealized_pnl: index * 100,
    realized_pnl: index * 5,
    commission_paid: 0,
    quote_status: 'confirmed',
  })),
  allocation: [1, 2].map((index) => ({
    symbol: `60000${index}`,
    name: `Fixture ${index}`,
    asset_class: 'stock',
    value: 100 + index * 100,
    weight: index * 0.2,
  })),
  allocation_grouped: [],
};

beforeEach(() => {
  navigate.mockClear();
  Object.assign(searchState, { q: '', assetClass: 'all', pnl: 'all' });
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

function rowSymbols() {
  return within(screen.getByTestId('positions-table-desktop'))
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.getAttribute('data-testid'));
}

test.each([
  'market_value',
  'weight',
  'today-pct',
  'today-change',
  'unrealized-pct',
  'unrealized-amount',
  'realized_pnl',
  'symbol',
])('cycles %s through both directions and cancellation', (key) => {
  render(
    <PreferencesProvider>
      <PortfolioPageController />
    </PreferencesProvider>,
  );
  const defaultOrder = rowSymbols();
  const button = () => screen.getByTestId(`positions-sort-${key}`);
  fireEvent.click(button());
  const firstOrder = rowSymbols();
  expect(button().closest('th')).toHaveAttribute(
    'aria-sort',
    key === 'symbol' ? 'ascending' : 'descending',
  );
  expect(firstOrder).toHaveLength(2);
  expect(new Set(firstOrder).size).toBe(2);
  fireEvent.click(button());
  expect(rowSymbols()).toEqual([...firstOrder].reverse());
  expect(button().closest('th')).toHaveAttribute(
    'aria-sort',
    key === 'symbol' ? 'descending' : 'ascending',
  );
  fireEvent.click(button());
  expect(rowSymbols()).toEqual(defaultOrder);
  expect(button().closest('th')).not.toHaveAttribute('aria-sort');
  expect(screen.getByRole('combobox', { name: 'Sort by' })).toHaveValue(
    'default',
  );
  fireEvent.click(button());
  expect(rowSymbols()).toEqual(firstOrder);
});

test('clears route and local filters together from the empty state', () => {
  Object.assign(searchState, {
    q: 'no-match',
    assetClass: 'fund',
    pnl: 'losers',
  });
  render(
    <PreferencesProvider>
      <PortfolioPageController />
    </PreferencesProvider>,
  );
  const quoteFilter = screen.getByRole('combobox', { name: 'Quote state' });
  const evidenceFilter = screen.getByRole('combobox', {
    name: 'Reconciliation',
  });
  fireEvent.change(quoteFilter, { target: { value: 'review' } });
  fireEvent.change(evidenceFilter, { target: { value: 'review' } });
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  expect(quoteFilter).toHaveValue('all');
  expect(evidenceFilter).toHaveValue('all');
  expect(navigate).toHaveBeenCalledWith({
    to: '/portfolio',
    search: { q: '', assetClass: 'all', pnl: 'all' },
    replace: true,
  });
});

test('title clicks cancel the active amount sort and clear the unit highlight', () => {
  render(
    <PreferencesProvider>
      <PortfolioPageController />
    </PreferencesProvider>,
  );
  const defaultOrder = rowSymbols();
  const amount = () => screen.getByTestId('positions-sort-today-change');
  const title = () =>
    within(amount().closest('th')!).getByRole('button', {
      name: 'Day’s P&L',
    });
  fireEvent.click(amount());
  expect(amount()).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(title());
  expect(rowSymbols()).toEqual([...defaultOrder].reverse());
  fireEvent.click(title());
  expect(rowSymbols()).toEqual(defaultOrder);
  expect(amount()).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('combobox', { name: 'Sort by' })).toHaveValue(
    'default',
  );
});

test('keeps keyboard focus through the full sorting cycle', async () => {
  const user = userEvent.setup();
  render(
    <PreferencesProvider>
      <PortfolioPageController />
    </PreferencesProvider>,
  );
  const button = () => screen.getByTestId('positions-sort-today-pct');
  button().focus();
  for (let click = 0; click < 3; click++) {
    await user.keyboard('{Enter}');
    await waitFor(() => expect(button()).toHaveFocus());
  }
  expect(screen.getByRole('combobox', { name: 'Sort by' })).toHaveValue(
    'default',
  );
});
