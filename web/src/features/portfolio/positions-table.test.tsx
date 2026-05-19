import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import { expect, test } from 'vitest';

import { PositionsTable } from './components/positions-table';

function renderTable(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
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
      .getAllByRole('link', { name: 'Holding Details: 600519' })[0]
      .getAttribute('href'),
  ).toBe('/portfolio/600519');
  expect(
    screen.getAllByRole('link', { name: /Trade/i }).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByRole('button', { name: 'Refresh' }).length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText('60').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Market Value').length).toBeGreaterThan(0);
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
    screen.getAllByText('quote_older_than_expected_session').length,
  ).toBeGreaterThan(0);
});
