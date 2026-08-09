import { fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../app/preferences';
import type { Position } from './api';
import { PositionsTable } from './components/positions-table';

beforeEach(() => {
  window.localStorage.clear();
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
  return render(<PreferencesProvider>{ui}</PreferencesProvider>);
}

test('renders the compact canonical holdings table with direct detail drill-down', () => {
  const onOpenPosition = vi.fn();
  renderTable(
    <PositionsTable
      positions={[basePosition]}
      weightBySymbol={{ '600519': 0.42 }}
      onOpenPosition={onOpenPosition}
    />,
  );

  const table = screen.getByTestId('positions-table-desktop');
  const headers = within(table)
    .getAllByRole('columnheader')
    .map((header) => header.textContent);
  expect(headers).toEqual([
    'Symbol',
    'Market Value',
    'Weight',
    'Today PnL',
    'Unrealized',
    'Realized PnL',
    'Quote State',
  ]);
  expect(screen.getByTestId('position-weight-600519').textContent).toBe(
    '42.0%',
  );
  expect(screen.getByTestId('position-realized-600519').textContent).toBe(
    '¥120.00',
  );
  const detailLink = within(table).getByRole('link', {
    name: 'Holding Details: 贵州茅台 600519',
  });
  expect(detailLink.getAttribute('href')).toBe('/portfolio/600519');
  detailLink.addEventListener('click', (event) => event.preventDefault(), {
    once: true,
  });
  fireEvent.click(detailLink, { ctrlKey: true });
  expect(onOpenPosition).not.toHaveBeenCalled();
  fireEvent.click(detailLink);
  expect(onOpenPosition).toHaveBeenCalledWith('600519');
  expect(within(table).queryByRole('button')).toBeNull();
});

test('keeps the overview dashboard table compact', () => {
  renderTable(
    <PositionsTable positions={[basePosition]} variant="dashboard" />,
  );

  const table = screen.getByTestId('positions-table-desktop');
  expect(table.closest('.app-data-table-shell')?.className).toContain(
    'app-positions-table-dashboard',
  );
  const headers = within(table)
    .getAllByRole('columnheader')
    .map((header) => header.textContent);
  expect(headers).toEqual([
    'Symbol',
    'Market Value',
    'Today PnL',
    'Unrealized',
    'Quote State',
  ]);
  expect(within(table).queryByRole('button')).toBeNull();
});

test('uses a watchlist-density mobile row for the overview dashboard', () => {
  renderTable(
    <PositionsTable positions={[basePosition]} variant="dashboard" />,
  );

  const row = screen.getByTestId('position-mobile-row-600519');
  expect(row.className).toContain('py-2.5');
  expect(row.textContent).toContain('贵州茅台');
  expect(row.textContent).toContain('¥96,000.00');
  expect(row.textContent).toContain('Today PnL: ¥30.00');
  expect(row.textContent).toContain('Unrealized ¥6,000.00');
  expect(within(row).queryByText('Weight')).toBeNull();
});

test('keeps secondary cost, quantity, and quote facts in holding detail', () => {
  renderTable(<PositionsTable positions={[basePosition]} />);

  const table = screen.getByTestId('positions-table-desktop');
  expect(within(table).queryByText('Quantity')).toBeNull();
  expect(within(table).queryByText('Quote Price')).toBeNull();
  expect(within(table).queryByText('Local moving average cost')).toBeNull();
  expect(within(table).queryByText('Broker displayed cost')).toBeNull();
  expect(
    within(table).getByRole('link', {
      name: 'Holding Details: 贵州茅台 600519',
    }),
  ).toBeTruthy();
});

test('shows stale quote reason as compact visible evidence', () => {
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

  const table = screen.getByTestId('positions-table-desktop');
  expect(
    within(table).getByText('Quote older than expected trading session'),
  ).toBeTruthy();
  expect(
    within(table).getByText('Quote older than expected trading session')
      .className,
  ).toContain('truncate');
});

test('provides a task-focused mobile holdings list without table-width dependence', () => {
  renderTable(
    <PositionsTable
      positions={[basePosition]}
      weightBySymbol={{ '600519': 0.42 }}
    />,
  );

  const list = screen.getByTestId('positions-mobile-list');
  const row = within(list).getByTestId('position-mobile-row-600519');
  expect(list.className).toContain('md:hidden');
  expect(list.className).toContain('max-w-full');
  expect(row.className).toContain('app-position-mobile-row');
  expect(row.className).toContain('w-full');
  expect(row.className).toContain('max-w-full');
  expect(row.getAttribute('href')).toBe('/portfolio/600519');
  expect(row.textContent).toContain('贵州茅台');
  expect(row.textContent).toContain('¥96,000.00');
  expect(row.textContent).toContain('42.0%');
  expect(row.textContent).toContain('¥6,000.00');
});

test('keeps closed-position realized results and fees as read-only history', () => {
  renderTable(
    <PositionsTable
      positions={[
        {
          ...basePosition,
          closed_at: '2026-07-18T14:30:00+08:00',
        },
      ]}
      variant="history"
    />,
  );

  const table = screen.getByTestId('positions-table-desktop');
  const headers = within(table)
    .getAllByRole('columnheader')
    .map((header) => header.textContent);
  expect(headers).toEqual([
    'Symbol',
    'Closed on',
    'Realized PnL',
    'Commission Paid',
  ]);
  expect(screen.getByTestId('position-closed-at-600519').textContent).toBe(
    '07/18/2026',
  );
  expect(screen.getByTestId('position-realized-600519').textContent).toBe(
    '¥120.00',
  );
  expect(screen.getByTestId('position-commission-600519').textContent).toBe(
    '¥5.00',
  );
  expect(within(table).queryByRole('button')).toBeNull();
  expect(within(table).queryByText('Trade')).toBeNull();
  expect(
    within(table)
      .getByRole('link', { name: 'Holding Details: 贵州茅台 600519' })
      .getAttribute('href'),
  ).toBe('/portfolio/600519');
});

test('fails closed when a historical close timestamp is unavailable', () => {
  renderTable(<PositionsTable positions={[basePosition]} variant="history" />);

  expect(screen.getByTestId('position-closed-at-600519').textContent).toBe(
    '--',
  );
  expect(
    screen.getByTestId('position-mobile-row-600519').textContent,
  ).toContain('Closed on--');
});
