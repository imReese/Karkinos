import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../app/preferences';
import type { Position } from './api';
import { PositionsTable } from './components/positions-table';

beforeEach(() => {
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
});

const basePosition: Position = {
  symbol: '600519',
  display_name: '贵州茅台',
  asset_class: 'stock',
  quantity: 60,
  available_qty: 60,
  frozen_qty: 0,
  avg_cost: 1500,
  latest_price: 1600,
  market_value: 96000,
  today_change: 30,
  unrealized_pnl: 6000,
  realized_pnl: 120,
  commission_paid: 5,
  quote_status: 'confirmed',
};

function renderTable(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </PreferencesProvider>,
  );
}

test('renders the canonical current-holdings table with direct detail drill-down', () => {
  renderTable(
    <PositionsTable
      positions={[basePosition]}
      weightBySymbol={{ '600519': 0.42 }}
    />,
  );

  const row = screen.getByRole('row', {
    name: 'Holding Details: 贵州茅台 600519',
  });
  expect(row.className).toContain('cursor-pointer');
  expect(
    screen
      .getAllByRole('link', { name: 'Holding Details: 贵州茅台 600519' })[0]
      .getAttribute('href'),
  ).toBe('/portfolio/600519');
  expect(screen.getByTestId('position-weight-600519').textContent).toBe(
    '42.0%',
  );
  expect(screen.getByTestId('position-realized-600519').textContent).toBe(
    '¥120.00',
  );
  expect(screen.getByRole('button', { name: 'Refresh' })).toBeTruthy();
});

test('formats persisted cost and quote prices without recomputing them', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          ...basePosition,
          symbol: '600003',
          avg_cost: 16.275,
          latest_price: 16.2608,
          market_value: 3252,
          today_change: -3,
          unrealized_pnl: -3,
        },
      ]}
    />,
  );

  expect(screen.getByTestId('position-avg-cost-600003').textContent).toBe(
    '16.2750',
  );
  expect(screen.getByTestId('position-latest-price-600003').textContent).toBe(
    '16.2608',
  );
  expect(screen.getByTestId('position-today-change-600003').textContent).toBe(
    '-¥3.00',
  );
  expect(
    screen.getByTestId('position-today-change-600003').querySelector('span')
      ?.className,
  ).toContain('text-[var(--app-pnl-negative)]');
});

test('fails closed when quote price is absent instead of deriving market value per share', () => {
  renderTable(
    <PositionsTable positions={[{ ...basePosition, latest_price: null }]} />,
  );

  expect(screen.getByTestId('position-latest-price-600519').textContent).toBe(
    '--',
  );
  expect(screen.queryByText('1,600.0000')).toBeNull();
});

test('fails closed when broker unit cost is absent instead of dividing total basis by quantity', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          ...basePosition,
          avg_cost: 1400,
          broker_displayed_unit_cost: null,
          broker_displayed_cost_basis: 90000,
          broker_cost_basis_status: 'available',
        },
      ]}
    />,
  );

  expect(screen.getByTestId('position-broker-cost-600519').textContent).toBe(
    '--',
  );
  expect(screen.queryByText('1,500.0000')).toBeNull();
});

test('shows persisted broker cost evidence and its canonical difference', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          ...basePosition,
          broker_displayed_unit_cost: 1499.25,
          broker_displayed_cost_basis: 89955,
          broker_cost_basis_difference: -45,
          broker_cost_basis_method: 'broker_remaining_cost',
          broker_cost_basis_status: 'available',
        },
      ]}
    />,
  );

  const brokerCell = screen.getByTestId('position-broker-cost-600519');
  expect(brokerCell.textContent).toContain('1,499.2500');
  expect(brokerCell.textContent).toContain('Cost basis difference -¥45.00');
  expect(brokerCell.textContent).toContain('Broker-confirmed evidence');
});

test('labels ledger-projected cost evidence without claiming broker confirmation', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          ...basePosition,
          broker_displayed_unit_cost: 1498,
          broker_displayed_cost_basis: 89880,
          broker_cost_basis_method: 'broker_remaining_cost',
          broker_cost_basis_status: 'projected_from_ledger',
        },
      ]}
    />,
  );

  const brokerCell = screen.getByTestId('position-broker-cost-600519');
  expect(brokerCell.textContent).toContain('Projected from local ledger');
  expect(brokerCell.textContent).not.toContain('Broker-confirmed evidence');
});

test('shows stale quote reason as visible evidence', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          ...basePosition,
          quote_status: 'stale',
          quote_timestamp: '2026-04-21T14:30:00+08:00',
          quote_age_seconds: 86400,
          stale_reason: 'quote_older_than_expected_session',
        },
      ]}
    />,
  );

  expect(
    screen.getByText('Cached quotes · positions valued from cached quotes'),
  ).toBeTruthy();
  expect(
    screen.getByText('Quote older than expected trading session'),
  ).toBeTruthy();
});

test('contains wide data in a local horizontal scroller', () => {
  renderTable(<PositionsTable positions={[basePosition]} />);

  const scrollRegion = screen.getByTestId('positions-table-scroll');
  const table = screen.getByTestId('positions-table-desktop');
  expect(scrollRegion.className).toContain('min-w-0');
  expect(scrollRegion.className).toContain('max-w-full');
  expect(scrollRegion.className).toContain('overflow-x-auto');
  expect(scrollRegion.className).toContain('overscroll-x-contain');
  expect(table.className).toContain('min-w-max');
});

test('keeps historical positions and realized PnL accessible without refresh or trade authority', () => {
  renderTable(<PositionsTable positions={[basePosition]} variant="history" />);

  const row = screen.getByTestId('position-row-600519');
  expect(within(row).getByText('¥120.00')).toBeTruthy();
  expect(within(row).getByRole('link', { name: 'Ledger' })).toBeTruthy();
  expect(within(row).queryByRole('button', { name: 'Refresh' })).toBeNull();
  expect(within(row).queryByRole('link', { name: 'Trade' })).toBeNull();
});
