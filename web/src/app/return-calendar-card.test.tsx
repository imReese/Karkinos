import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from './preferences';
import { ReturnCalendarCard } from './router';

const timeline = [
  {
    date: '2026-01-03',
    equity: 100500,
    delta: 500,
    external_flow: 0,
    market_pnl: 500,
  },
  {
    date: '2026-01-06',
    equity: 100200,
    delta: -300,
    external_flow: 0,
    market_pnl: -300,
  },
  {
    date: '2026-02-10',
    equity: 101000,
    delta: 800,
    external_flow: 200,
    market_pnl: 600,
    market_breakdown: [
      { key: 'stock', label: 'Stocks', value: 650 },
      { key: 'fund', label: 'Funds', value: -50 },
    ],
    external_flow_breakdown: [
      { key: 'cash_deposit', label: 'Deposits', value: 200 },
    ],
  },
  {
    date: '2026-02-11',
    equity: 100721,
    delta: -279,
    external_flow: 0,
    market_pnl: 0,
    valuation_status: 'missing',
    missing_price_symbols: ['600519'],
  },
  {
    date: '2025-12-31',
    equity: 100000,
    delta: 1000,
    external_flow: 500,
    market_pnl: 500,
  },
];

const positionSnapshot = [
  {
    symbol: '026539',
    display_name: 'Rongtong Tech Growth Fund C',
    asset_class: 'fund',
    market_value: 775.78,
    unrealized_pnl: 175.78,
    realized_pnl: 0,
  },
  {
    symbol: '603659',
    name: 'Putailai',
    asset_class: 'stock',
    market_value: 5668,
    unrealized_pnl: -95,
    realized_pnl: 0,
  },
];

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

function renderCalendar({ compact = false }: { compact?: boolean } = {}) {
  return render(
    <PreferencesProvider>
      <ReturnCalendarCard timeline={timeline} compact={compact} />
    </PreferencesProvider>,
  );
}

test('renders a month calendar with selectable daily return cells by default', async () => {
  renderCalendar();

  expect(await screen.findByText('Return calendar')).toBeTruthy();
  expect(screen.getByText(/next to the net-value curve/i)).toBeTruthy();
  expect(screen.queryByText(/risk page/i)).toBeNull();
  expect(screen.getByTestId('return-calendar-month-grid')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-02-10 · CN¥600.00' }),
  ).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: '2026-02-10 · CN¥800.00' }),
  ).toBeNull();

  await userEvent.click(
    screen.getByRole('button', { name: '2026-02-10 · CN¥600.00' }),
  );

  expect(await screen.findByText('2026-02-10')).toBeTruthy();
  const selectedPeriod = screen
    .getByText('Selected period')
    .closest('div')?.parentElement;
  expect(selectedPeriod).toBeTruthy();
  expect(within(selectedPeriod!).getByText('Market move')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('CN¥600.00')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('Stocks')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('CN¥650.00')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('Funds')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('-CN¥50.00')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('Deposits')).toBeTruthy();
  expect(
    within(selectedPeriod!).getAllByText('CN¥200.00').length,
  ).toBeGreaterThan(0);
});

test('uses Sunday as the first weekday column in the return calendar', async () => {
  renderCalendar();

  const weekdays = await screen.findAllByTestId('return-calendar-weekday');
  expect(weekdays.map((day) => day.textContent)).toEqual([
    'Sun',
    'Mon',
    'Tue',
    'Wed',
    'Thu',
    'Fri',
    'Sat',
  ]);
});

test('switches the return calendar between monthly days, yearly months, and years', async () => {
  renderCalendar();
  const user = userEvent.setup();

  await user.selectOptions(
    screen.getByLabelText('Calendar period'),
    'year-months',
  );

  const yearGrid = await screen.findByTestId('return-calendar-year-grid');
  expect(
    within(yearGrid).getByRole('button', { name: '2026-01 · CN¥200.00' }),
  ).toBeTruthy();
  expect(
    within(yearGrid).getByRole('button', { name: '2026-02 · Price gap' }),
  ).toBeTruthy();

  await user.selectOptions(screen.getByLabelText('Calendar period'), 'years');

  const yearsGrid = await screen.findByTestId('return-calendar-years-grid');
  expect(
    within(yearsGrid).getByRole('button', { name: '2026 · Price gap' }),
  ).toBeTruthy();
  expect(
    within(yearsGrid).getByRole('button', { name: '2025 · CN¥500.00' }),
  ).toBeTruthy();
});

test('marks return calendar days with incomplete historical prices', async () => {
  renderCalendar();

  const missingPriceCell = await screen.findByRole('button', {
    name: '2026-02-11 · Price gap',
  });
  expect(missingPriceCell).toBeTruthy();

  await userEvent.click(missingPriceCell);

  expect(await screen.findByText('Valuation coverage')).toBeTruthy();
  expect(screen.getByText('Missing historical prices: 600519')).toBeTruthy();
  expect(screen.getAllByText('Price gap').length).toBeGreaterThan(0);
  const selectedPeriod = screen
    .getByText('Selected period')
    .closest('div')?.parentElement;
  expect(selectedPeriod).toBeTruthy();
  expect(within(selectedPeriod!).queryByText(/279/)).toBeNull();

  await userEvent.selectOptions(screen.getByDisplayValue('Calendar'), 'table');
  expect(screen.getAllByText('Price gap').length).toBeGreaterThan(0);
});

test('renders axes when the return calendar switches to curve view', async () => {
  renderCalendar();

  await userEvent.selectOptions(screen.getByDisplayValue('Calendar'), 'curve');

  expect(await screen.findByTestId('return-curve-x-axis')).toBeTruthy();
  expect(screen.getByTestId('return-curve-y-axis')).toBeTruthy();
  expect(screen.getByText('2026-02-11')).toBeTruthy();
  expect(screen.getByText('CN¥600.00')).toBeTruthy();
});

test('supports a compact cockpit layout for the overview page', async () => {
  renderCalendar({ compact: true });

  const panel = await screen.findByTestId('return-calendar-card');
  expect(panel.className).toContain('p-4');
  expect(panel.className).not.toContain('rounded-2xl');
  expect(screen.getByTestId('return-calendar-month-grid')).toBeTruthy();
  expect(screen.getByText('Selected period')).toBeTruthy();
});

test('shows a current-position fallback when daily attribution is not available', async () => {
  render(
    <PreferencesProvider>
      <ReturnCalendarCard timeline={[]} positions={positionSnapshot} compact />
    </PreferencesProvider>,
  );

  expect(await screen.findByText('Current position PnL')).toBeTruthy();
  expect(screen.getByText('Return calendar is warming up')).toBeTruthy();
  expect(screen.getAllByText('CN¥80.78').length).toBeGreaterThan(0);
  expect(screen.getByText('Rongtong Tech Growth Fund C')).toBeTruthy();
  expect(screen.getByText('026539')).toBeTruthy();
  expect(screen.getByText('Putailai')).toBeTruthy();
  expect(screen.getByText('603659')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Add activity' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Check data source' })).toBeTruthy();
});
