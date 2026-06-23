import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../app/preferences';
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

test('renders active positions', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600519',
          name: '贵州茅台',
          asset_class: 'stock',
          quantity: 60,
          available_qty: 60,
          frozen_qty: 0,
          avg_cost: 1500,
          market_value: 96000,
          unrealized_pnl: 6000,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('600519').length).toBeGreaterThan(0);
  expect(screen.getAllByText('贵州茅台').length).toBeGreaterThan(0);
  expect(
    screen
      .getAllByRole('link', { name: 'Holding Details: 贵州茅台 600519' })[0]
      .getAttribute('href'),
  ).toBe('/portfolio/600519');
  expect(
    screen.queryByRole('link', { name: 'Holding Details: 600519' }),
  ).toBeNull();
  expect(screen.getByTestId('position-card-600519').className).toContain(
    'cursor-pointer',
  );
  expect(screen.getByTestId('position-row-600519').className).toContain(
    'cursor-pointer',
  );
  expect(
    screen.getAllByRole('link', { name: /Trade/i }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole('button', { name: 'Refresh' }).length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText('60').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Market Value').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Stock').length).toBeGreaterThan(0);
  expect(screen.getAllByText('6.67%').length).toBeGreaterThan(0);
  expect(screen.queryByText('6.7%')).toBeNull();
  expect(screen.queryByText('stock')).toBeNull();
});

test('renders cost and quote prices with four decimal places', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600066',
          display_name: '宇通客车',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 26.375,
          latest_price: 26.3608,
          market_value: 5272,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: -3,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('26.3750').length).toBeGreaterThan(0);
  expect(screen.getAllByText('26.3608').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Today PnL').length).toBeGreaterThan(0);
  expect(screen.getAllByText('-CN¥3.00').length).toBeGreaterThan(0);
  expect(screen.getByTestId('position-avg-cost-600066').textContent).toBe(
    '26.3750',
  );
  expect(screen.getByTestId('position-latest-price-600066').textContent).toBe(
    '26.3608',
  );
  expect(screen.getByTestId('position-avg-cost-600066').className).toContain(
    'min-w-28',
  );
  expect(
    screen.getByTestId('position-latest-price-600066').className,
  ).toContain('min-w-28');
  expect(screen.getAllByText('CN¥5,272.00').length).toBeGreaterThan(0);
  expect(screen.queryByText('26.38')).toBeNull();
  expect(screen.queryByText('26.36')).toBeNull();
  expect(screen.queryByText('CN¥26.3750')).toBeNull();
  expect(screen.queryByText('CN¥26.3608')).toBeNull();
});

test('shows broker displayed cost basis beside local moving average cost when evidence exists', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600066',
          display_name: '宇通客车',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 26.3758,
          latest_price: 26.41,
          market_value: 5282,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: 6.84,
          realized_pnl: 0,
          commission_paid: 5,
          broker_displayed_cost_basis: 5275.16,
          broker_cost_basis_difference: -0.0,
          broker_cost_basis_method: 'broker_remaining_cost',
          broker_cost_basis_status: 'available',
        },
      ]}
    />,
  );

  expect(
    screen.getAllByText('Local moving average cost').length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText('Broker displayed cost').length).toBeGreaterThan(
    0,
  );
  expect(screen.getAllByText('26.3758').length).toBeGreaterThan(0);
  expect(screen.getAllByText('26.3758').length).toBeGreaterThan(1);
  expect(
    screen.getAllByText(/Broker remaining-position cost/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(/Broker-confirmed evidence/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByTestId('position-broker-cost-600066').textContent,
  ).toContain('26.3758');
  expect(
    screen.getByTestId('position-mobile-broker-cost-600066').textContent,
  ).toBe('26.3758');
});

test('uses shared numeric cell classes for desktop portfolio columns', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600066',
          display_name: '宇通客车',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 26.375,
          latest_price: 26.3608,
          market_value: 5272,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: -3,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('Realized PnL').length).toBeGreaterThan(0);

  for (const testId of [
    'position-quantity-600066',
    'position-avg-cost-600066',
    'position-broker-cost-600066',
    'position-latest-price-600066',
    'position-market-value-600066',
    'position-today-change-600066',
    'position-unrealized-600066',
    'position-return-pct-600066',
    'position-available-frozen-600066',
    'position-realized-600066',
  ]) {
    expect(screen.getByTestId(testId).className).toContain(
      'karkinos-numeric-cell',
    );
  }

  expect(screen.getByTestId('position-avg-cost-600066').className).toContain(
    'min-w-28',
  );
  expect(
    screen.getByTestId('position-latest-price-600066').className,
  ).toContain('min-w-28');
  expect(
    screen.getByTestId('position-market-value-600066').className,
  ).toContain('min-w-32');
  expect(screen.getByTestId('position-return-pct-600066').className).toContain(
    'min-w-24',
  );
});

test('uses shared numeric display classes for mobile portfolio metrics', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600066',
          display_name: '宇通客车',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 26.375,
          latest_price: 26.3608,
          market_value: 5272,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: -3,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('Realized PnL').length).toBeGreaterThan(0);

  for (const testId of [
    'position-mobile-quantity-600066',
    'position-mobile-avg-cost-600066',
    'position-mobile-latest-price-600066',
    'position-mobile-market-value-600066',
    'position-mobile-today-change-600066',
    'position-mobile-unrealized-600066',
    'position-mobile-return-pct-600066',
    'position-mobile-available-frozen-600066',
    'position-mobile-realized-600066',
  ]) {
    expect(screen.getByTestId(testId).className).toContain(
      'karkinos-numeric-display',
    );
  }

  expect(
    screen.getByTestId('position-mobile-avg-cost-600066').textContent,
  ).toBe('26.3750');
  expect(
    screen.getByTestId('position-mobile-latest-price-600066').textContent,
  ).toBe('26.3608');
  expect(
    screen.getByTestId('position-mobile-market-value-600066').textContent,
  ).toBe('CN¥5,272.00');
  expect(
    screen.getByTestId('position-mobile-today-change-600066').textContent,
  ).toBe('-CN¥3.00');
  expect(
    screen.getByTestId('position-mobile-today-change-600066').className,
  ).toContain('text-[var(--app-danger)]');
  expect(
    screen.getByTestId('position-mobile-return-pct-600066').className,
  ).toContain('text-[var(--app-danger)]');
  expect(screen.queryByText('CN¥26.3750')).toBeNull();
  expect(screen.queryByText('CN¥26.3608')).toBeNull();
});

test('shows cached quote copy for stale positions', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600519',
          display_name: '贵州茅台',
          quantity: 60,
          available_qty: 60,
          frozen_qty: 0,
          avg_cost: 1500,
          market_value: 96000,
          unrealized_pnl: 6000,
          realized_pnl: 0,
          commission_paid: 5,
          quote_status: 'stale',
          quote_timestamp: '2026-04-21T14:30:00+08:00',
          quote_age_seconds: 86_400,
          stale_reason: 'quote_older_than_expected_session',
        },
      ]}
    />,
  );

  expect(
    screen.getByText('Cached quotes · positions valued from cached quotes'),
  ).toBeTruthy();
  expect(screen.getAllByText(/^Cached /).length).toBeGreaterThan(0);
  expect(
    screen.getAllByText('Quote older than expected trading session').length,
  ).toBeGreaterThan(0);
});

test('contains the desktop positions table in a local horizontal scroller', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600519',
          name: '贵州茅台',
          asset_class: 'stock',
          quantity: 60,
          available_qty: 60,
          frozen_qty: 0,
          avg_cost: 1500,
          market_value: 96000,
          unrealized_pnl: 6000,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  const scrollRegion = screen.getByTestId('positions-table-scroll');
  const table = screen.getByTestId('positions-table-desktop');

  expect(scrollRegion.className).toContain('min-w-0');
  expect(scrollRegion.className).toContain('max-w-full');
  expect(scrollRegion.className).toContain('overflow-x-scroll');
  expect(scrollRegion.className).toContain('overscroll-x-contain');
  expect(scrollRegion.className).toContain('pb-2');
  expect(table.className).toContain('w-[1520px]');
  expect(table.className).toContain('min-w-max');
});

test('keeps desktop asset class badges on one line', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600519',
          name: '贵州茅台',
          asset_class: 'stock',
          quantity: 60,
          available_qty: 60,
          frozen_qty: 0,
          avg_cost: 1500,
          market_value: 96000,
          unrealized_pnl: 6000,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  const badge = screen.getByTestId('position-asset-class-600519');

  expect(badge.className).toContain('whitespace-nowrap');
  expect(badge.className).toContain('inline-flex');
});
