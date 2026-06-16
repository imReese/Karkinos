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
  expect(table.className).toContain('w-[1280px]');
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
