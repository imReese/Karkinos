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
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.275,
          latest_price: 16.2608,
          market_value: 3252,
          today_change: -3,
          today_change_pct: -0.00092,
          unrealized_pnl: -3,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('16.2750').length).toBeGreaterThan(0);
  expect(screen.getAllByText('16.2608').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Today PnL').length).toBeGreaterThan(0);
  expect(screen.getAllByText('-CN¥3.00').length).toBeGreaterThan(0);
  expect(screen.getByTestId('position-avg-cost-600003').textContent).toBe(
    '16.2750',
  );
  expect(screen.getByTestId('position-latest-price-600003').textContent).toBe(
    '16.2608',
  );
  expect(screen.getByTestId('position-avg-cost-600003').className).toContain(
    'min-w-28',
  );
  expect(
    screen.getByTestId('position-latest-price-600003').className,
  ).toContain('min-w-28');
  expect(screen.getAllByText('CN¥3,252.00').length).toBeGreaterThan(0);
  expect(screen.queryByText('16.28')).toBeNull();
  expect(screen.queryByText('16.26')).toBeNull();
  expect(screen.queryByText('CN¥16.2750')).toBeNull();
  expect(screen.queryByText('CN¥16.2608')).toBeNull();
});

test('shows broker displayed cost basis beside local moving average cost when evidence exists', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.2345,
          latest_price: 26.41,
          market_value: 5282,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: 6.84,
          realized_pnl: 0,
          commission_paid: 5,
          broker_displayed_cost_basis: 3255.16,
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
  expect(screen.getAllByText('16.2345').length).toBeGreaterThan(0);
  expect(screen.getAllByText('16.2345').length).toBeGreaterThan(1);
  expect(
    screen.getAllByText(/Broker displayed remaining cost/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(/Broker-confirmed evidence/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByTestId('position-broker-cost-600003').textContent,
  ).toContain('16.2758');
  expect(
    screen.getByTestId('position-mobile-broker-cost-600003').textContent,
  ).toBe('16.2758');
});

test('prefers broker displayed unit cost over deriving from total basis', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.2345,
          latest_price: 26.41,
          market_value: 5282,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: 6.84,
          realized_pnl: 0,
          commission_paid: 5,
          broker_displayed_unit_cost: 16.2379,
          broker_displayed_cost_basis: 99999,
          broker_cost_basis_difference: 10,
          broker_cost_basis_method: 'broker_remaining_cost',
          broker_cost_basis_status: 'available',
        },
      ]}
    />,
  );

  expect(
    screen.getByTestId('position-broker-cost-600003').textContent,
  ).toContain('16.2379');
  expect(
    screen.getByTestId('position-mobile-broker-cost-600003').textContent,
  ).toBe('16.2379');
  expect(screen.queryByText('499.9950')).toBeNull();
});

test('labels ledger-projected position costs without presenting them as broker displayed cost', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 10.01,
          latest_price: 26.41,
          market_value: 5282,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: 6.84,
          realized_pnl: 0,
          commission_paid: 5,
          broker_displayed_cost_basis: 1805.22,
          broker_cost_basis_difference: -196.78,
          broker_cost_basis_method: 'broker_remaining_cost',
          broker_cost_basis_status: 'projected_from_ledger',
        },
      ]}
    />,
  );

  const mobileBrokerCost = screen.getByTestId(
    'position-mobile-broker-cost-600003',
  ).parentElement;

  expect(mobileBrokerCost?.textContent).toContain('Ledger-projected unit cost');
  expect(mobileBrokerCost?.textContent).toContain(
    'Projected from local ledger',
  );
  expect(mobileBrokerCost?.textContent).not.toContain('Broker displayed cost');
});

test('warns when broker displayed cost basis differs from local cost basis', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.2345,
          latest_price: 26.41,
          market_value: 5282,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: 6.84,
          realized_pnl: 0,
          commission_paid: 5,
          broker_displayed_cost_basis: 5285.16,
          broker_cost_basis_difference: 10,
          broker_cost_basis_method: 'broker_remaining_cost',
          broker_cost_basis_status: 'available',
        },
      ]}
    />,
  );

  expect(
    screen.getByTestId('position-broker-cost-600003').textContent,
  ).toContain('Cost basis difference CN¥10.00');
  expect(
    screen.getByTestId('position-mobile-broker-cost-600003').parentElement
      ?.textContent,
  ).toContain('Cost basis difference CN¥10.00');
});

test('uses shared public fallback for unknown broker cost-basis methods', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.2345,
          latest_price: 26.41,
          market_value: 5282,
          today_change: -3,
          today_change_pct: -0.00057,
          unrealized_pnl: 6.84,
          realized_pnl: 0,
          commission_paid: 5,
          broker_displayed_cost_basis: 3255.16,
          broker_cost_basis_difference: 0,
          broker_cost_basis_method: 'future_private_cost_basis_method',
          broker_cost_basis_status: 'available',
        },
      ]}
    />,
  );

  expect(screen.queryByText(/future_private_cost_basis_method/)).toBeNull();
  expect(
    screen.getAllByText(/Cost basis method needs review/).length,
  ).toBeGreaterThan(0);
});

test('uses shared numeric cell classes for desktop portfolio columns', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.275,
          latest_price: 16.2608,
          market_value: 3252,
          today_change: -3,
          today_change_pct: -0.00092,
          unrealized_pnl: -3,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('Realized PnL').length).toBeGreaterThan(0);

  for (const testId of [
    'position-quantity-600003',
    'position-avg-cost-600003',
    'position-broker-cost-600003',
    'position-latest-price-600003',
    'position-market-value-600003',
    'position-today-change-600003',
    'position-unrealized-600003',
    'position-return-pct-600003',
    'position-available-frozen-600003',
    'position-realized-600003',
  ]) {
    expect(screen.getByTestId(testId).className).toContain(
      'karkinos-numeric-cell',
    );
  }

  expect(screen.getByTestId('position-avg-cost-600003').className).toContain(
    'min-w-28',
  );
  expect(
    screen.getByTestId('position-latest-price-600003').className,
  ).toContain('min-w-28');
  expect(
    screen.getByTestId('position-market-value-600003').className,
  ).toContain('min-w-32');
  expect(screen.getByTestId('position-return-pct-600003').className).toContain(
    'min-w-24',
  );
});

test('uses shared numeric display classes for mobile portfolio metrics', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          symbol: '600003',
          display_name: '示例制造',
          asset_class: 'stock',
          quantity: 200,
          available_qty: 200,
          frozen_qty: 0,
          avg_cost: 16.275,
          latest_price: 16.2608,
          market_value: 3252,
          today_change: -3,
          today_change_pct: -0.00092,
          unrealized_pnl: -3,
          realized_pnl: 0,
          commission_paid: 5,
        },
      ]}
    />,
  );

  expect(screen.getAllByText('Realized PnL').length).toBeGreaterThan(0);

  for (const testId of [
    'position-mobile-quantity-600003',
    'position-mobile-avg-cost-600003',
    'position-mobile-latest-price-600003',
    'position-mobile-market-value-600003',
    'position-mobile-today-change-600003',
    'position-mobile-unrealized-600003',
    'position-mobile-return-pct-600003',
    'position-mobile-available-frozen-600003',
    'position-mobile-realized-600003',
  ]) {
    expect(screen.getByTestId(testId).className).toContain(
      'karkinos-numeric-display',
    );
  }

  expect(
    screen.getByTestId('position-mobile-avg-cost-600003').textContent,
  ).toBe('16.2750');
  expect(
    screen.getByTestId('position-mobile-latest-price-600003').textContent,
  ).toBe('16.2608');
  expect(
    screen.getByTestId('position-mobile-market-value-600003').textContent,
  ).toBe('CN¥3,252.00');
  expect(
    screen.getByTestId('position-mobile-today-change-600003').textContent,
  ).toBe('-CN¥3.00');
  expect(
    screen.getByTestId('position-mobile-today-change-600003').className,
  ).toContain('text-[var(--app-danger)]');
  expect(
    screen.getByTestId('position-mobile-return-pct-600003').className,
  ).toContain('text-[var(--app-danger)]');
  expect(screen.queryByText('CN¥16.2750')).toBeNull();
  expect(screen.queryByText('CN¥16.2608')).toBeNull();
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
