import { fireEvent, render, screen, within } from '@testing-library/react';
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

function renderCalendarWithTimeline(
  customTimeline: typeof timeline,
  { compact = false }: { compact?: boolean } = {},
) {
  return render(
    <PreferencesProvider>
      <ReturnCalendarCard timeline={customTimeline} compact={compact} />
    </PreferencesProvider>,
  );
}

test('renders a month calendar with selectable daily return cells by default', async () => {
  renderCalendar();

  expect(await screen.findByText('Return calendar')).toBeTruthy();
  expect(screen.getByText(/next to the net-value curve/i)).toBeTruthy();
  expect(screen.getByText('Data status')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Calendar' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Curve' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Day' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Week' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Month' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Year' })).toBeTruthy();
  expect(screen.queryByText(/you earned/i)).toBeNull();
  expect(screen.queryByText(/risk page/i)).toBeNull();
  const toolbar = screen.getByTestId('return-calendar-toolbar');
  expect(toolbar).toBeTruthy();
  expect(toolbar.className).toContain('sm:grid-cols-[auto_minmax');
  expect(
    within(toolbar).getByLabelText('View mode').getAttribute('data-compact'),
  ).toBe('icon');
  expect(
    within(toolbar).getByLabelText('Period mode').getAttribute('data-compact'),
  ).toBe('period');
  expect(
    within(toolbar).getByLabelText('Metric mode').getAttribute('data-compact'),
  ).toBe('metric');
  expect(
    within(toolbar).queryByTestId('return-calendar-status-chip'),
  ).toBeNull();
  expect(screen.getByTestId('return-calendar-period-select')).toBeTruthy();
  const statusChip = screen.getByTestId('return-calendar-status-chip');
  expect(statusChip).toBeTruthy();
  expect(statusChip.className).toContain('text-[var(--app-warning)]');
  expect(statusChip.className).not.toMatch(/text-(amber|emerald|sky)-100/);
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

test('keeps the compact calendar toolbar and day cells readable on narrow viewports', async () => {
  renderCalendar({ compact: true });

  const toolbar = await screen.findByTestId('return-calendar-toolbar');
  expect(toolbar.className).toContain('rounded-2xl');
  expect(toolbar.className.split(/\s+/)).not.toContain('rounded-full');
  expect(toolbar.className).toContain('sm:rounded-full');

  const periodControl = within(toolbar).getByLabelText('Period mode');
  expect(periodControl.className).toContain('w-full');
  expect(periodControl.className).toContain('sm:justify-between');

  const populatedValue = screen.getByRole('button', {
    name: '2026-02-10 · CN¥600.00',
  });
  expect(populatedValue.className).toContain('overflow-hidden');
  const cellValue = within(populatedValue).getByTestId(
    'return-calendar-cell-value',
  );
  expect(cellValue.className).toContain('whitespace-nowrap');
  expect(cellValue.className).toContain('text-[10px]');
  expect(cellValue.className).toContain('sm:text-[11px]');
  expect(cellValue.textContent).toBe('+600.00');
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

test('explains market holidays and weekends without showing missing prices', async () => {
  renderCalendarWithTimeline([
    {
      date: '2026-01-06',
      equity: 100200,
      delta: 200,
      external_flow: 0,
      market_pnl: 200,
      valuation_status: 'confirmed',
      missing_price_symbols: [],
    },
  ]);

  expect(await screen.findByText('Holiday')).toBeTruthy();
  expect(screen.getAllByText('Weekend').length).toBeGreaterThan(0);
  expect(screen.queryByRole('button', { name: /2026-01-01/ })).not.toBeTruthy();
  expect(screen.queryByRole('button', { name: /2026-01-04/ })).not.toBeTruthy();
  expect(screen.queryByRole('button', { name: /Price gap/ })).toBeNull();
});

test('shows live returns normally and only true missing rows as price gaps', async () => {
  renderCalendarWithTimeline([
    {
      date: '2026-06-16',
      equity: 100300,
      delta: 300,
      external_flow: 0,
      market_pnl: 300,
      valuation_status: 'live',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-17',
      equity: 101000,
      delta: 700,
      external_flow: 0,
      market_pnl: 700,
      valuation_status: 'estimated',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-18',
      equity: 100900,
      delta: -100,
      external_flow: 0,
      market_pnl: -100,
      valuation_status: 'confirmed_nav_missing',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-19',
      equity: 101200,
      delta: 300,
      external_flow: 0,
      market_pnl: 300,
      valuation_status: 'complete',
      missing_price_symbols: ['600519'],
    },
  ]);

  expect(await screen.findByText('Data status')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-16 · CN¥300.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-17 · CN¥700.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-18 · -CN¥100.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-19 · Price gap' }),
  ).toBeTruthy();
  expect(screen.getAllByText('Unconfirmed').length).toBeGreaterThanOrEqual(2);

  await userEvent.click(
    screen.getByRole('button', { name: '2026-06-17 · CN¥700.00' }),
  );

  const selectedPeriod = screen
    .getByText('Selected period')
    .closest('div')?.parentElement;
  expect(selectedPeriod).toBeTruthy();
  expect(within(selectedPeriod!).getByText('Valuation coverage')).toBeTruthy();
  expect(
    within(selectedPeriod!).getByText(
      'Some return periods are partially covered; review the breakdown before using the result.',
    ),
  ).toBeTruthy();
  expect(
    within(selectedPeriod!).getAllByText('CN¥700.00').length,
  ).toBeGreaterThan(0);
});

test('keeps live confirmed and cached valuation states distinct from true price gaps', async () => {
  renderCalendarWithTimeline([
    {
      date: '2026-06-16',
      equity: 100100,
      delta: 100,
      external_flow: 0,
      market_pnl: 100,
      valuation_status: 'live',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-17',
      equity: 100300,
      delta: 200,
      external_flow: 0,
      market_pnl: 200,
      valuation_status: 'confirmed',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-18',
      equity: 100600,
      delta: 300,
      external_flow: 0,
      market_pnl: 300,
      valuation_status: 'complete',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-19',
      equity: 101000,
      delta: 400,
      external_flow: 0,
      market_pnl: 400,
      valuation_status: 'cache',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-22',
      equity: 101500,
      delta: 500,
      external_flow: 0,
      market_pnl: 500,
      valuation_status: 'stale',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-23',
      equity: 102100,
      delta: 600,
      external_flow: 0,
      market_pnl: 600,
      valuation_status: 'estimated',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-24',
      equity: 102800,
      delta: 700,
      external_flow: 0,
      market_pnl: 700,
      valuation_status: 'missing',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-25',
      equity: 103600,
      delta: 800,
      external_flow: 0,
      market_pnl: 800,
      valuation_status: 'unavailable',
      missing_price_symbols: [],
    },
    {
      date: '2026-06-26',
      equity: 104500,
      delta: 900,
      external_flow: 0,
      market_pnl: 900,
      valuation_status: 'missing_price_symbols',
      missing_price_symbols: [],
    },
  ]);

  expect(
    await screen.findByRole('button', { name: '2026-06-16 · CN¥100.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-17 · CN¥200.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-18 · CN¥300.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-19 · CN¥400.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-22 · CN¥500.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-23 · CN¥600.00' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-24 · Price gap' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-25 · Price gap' }),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-06-26 · Price gap' }),
  ).toBeTruthy();
  expect(screen.getAllByText('Unconfirmed')).toHaveLength(3);
});

test('switches the return calendar between monthly days, yearly months, and years', async () => {
  renderCalendar();
  const user = userEvent.setup();

  await user.click(screen.getByRole('button', { name: 'Week' }));

  const calendarLayout = screen.getByTestId('return-calendar-layout');
  expect(calendarLayout.className).toContain('return-calendar-layout-week');
  expect(calendarLayout.className).toContain('xl:grid-cols-1');
  const weekGrid = await screen.findByTestId('return-calendar-week-grid');
  expect(weekGrid.className).toContain('md:grid-cols-3');
  expect(weekGrid.className).toContain('overflow-y-auto');
  expect(weekGrid.className).toContain('max-h-');
  expect(within(weekGrid).getByText('Week 1')).toBeTruthy();
  expect(within(weekGrid).getByText('01/01-01/03')).toBeTruthy();
  expect(within(weekGrid).getByText('02/08-02/14')).toBeTruthy();
  expect(
    within(weekGrid).getByRole('button', { name: '2026-W07 · Price gap' }),
  ).toBeTruthy();
  expect(await screen.findByText('Weekly change')).toBeTruthy();
  expect(screen.getByText('Week 7 · 02/08-02/14')).toBeTruthy();
  expect(screen.queryByText('2026-W07')).toBeNull();

  await user.click(screen.getByRole('button', { name: 'Month' }));

  const yearGrid = await screen.findByTestId('return-calendar-year-grid');
  const januaryCell = within(yearGrid).getByRole('button', {
    name: '2026-01 · CN¥200.00',
  });
  expect(within(januaryCell).getByText('01 Month')).toBeTruthy();
  expect(within(januaryCell).queryByText('01')).toBeNull();
  expect(within(januaryCell).queryByText('Month')).toBeNull();
  const januaryCellValue = within(januaryCell).getByTestId(
    'return-calendar-cell-value',
  );
  expect(januaryCellValue.textContent).toBe('CN¥200.00');
  expect(januaryCellValue.className).toContain('self-end');
  expect(januaryCellValue.className).toContain('text-right');
  expect(januaryCellValue.className).toContain('text-base');
  expect(
    within(yearGrid).getByRole('button', { name: '2026-01 · CN¥200.00' }),
  ).toBeTruthy();
  expect(
    within(yearGrid).getByRole('button', { name: '2026-02 · Price gap' }),
  ).toBeTruthy();
  expect(await screen.findByText('Monthly change')).toBeTruthy();
  expect(screen.queryByText('Daily change')).toBeNull();

  await user.click(screen.getByRole('button', { name: 'Year' }));

  const yearsGrid = await screen.findByTestId('return-calendar-years-grid');
  expect(
    within(yearsGrid).getByRole('button', { name: '2026 · Price gap' }),
  ).toBeTruthy();
  expect(
    within(yearsGrid).getByRole('button', { name: '2025 · CN¥500.00' }),
  ).toBeTruthy();
  expect(await screen.findByText('Annual change')).toBeTruthy();
  expect(screen.queryByText('Daily change')).toBeNull();
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

  await userEvent.click(screen.getByRole('button', { name: 'Table' }));
  expect(screen.getAllByText('Price gap').length).toBeGreaterThan(0);
});

test('renders axes when the return calendar switches to curve view', async () => {
  renderCalendar();

  await userEvent.click(screen.getByRole('button', { name: 'Curve' }));

  const chart = await screen.findByTestId('return-curve-chart');
  expect(chart.getAttribute('viewBox')).toBe('0 0 820 420');
  expect(chart.getAttribute('class')).toContain('h-[360px]');
  expect(chart.getAttribute('class')).toContain('sm:h-[420px]');
  expect(await screen.findByTestId('return-curve-x-axis')).toBeTruthy();
  expect(screen.getByTestId('return-curve-y-axis')).toBeTruthy();
  expect(screen.getByTestId('return-curve-zero-axis')).toBeTruthy();
  expect(screen.getByText('2026-02-11')).toBeTruthy();
  expect(screen.getByText('CN¥600.00')).toBeTruthy();

  const point = screen.getByTestId('return-curve-point-0');
  fireEvent.mouseEnter(point);

  const tooltip = await screen.findByTestId('return-curve-tooltip');
  expect(within(tooltip).getByText('2026-02-10')).toBeTruthy();
  expect(within(tooltip).getByText('CN¥600.00')).toBeTruthy();

  fireEvent.mouseLeave(point);
  fireEvent.pointerMove(point);
  const pointerTooltip = await screen.findByTestId('return-curve-tooltip');
  expect(within(pointerTooltip).getByText('2026-02-10')).toBeTruthy();
});

test('supports a compact cockpit layout for the overview page', async () => {
  renderCalendar({ compact: true });
  const user = userEvent.setup();

  const panel = await screen.findByTestId('return-calendar-card');
  expect(panel.className).toContain('p-4');
  expect(panel.className).not.toContain('rounded-2xl');
  expect(screen.getByTestId('return-calendar-month-grid')).toBeTruthy();
  expect(screen.getByText('Selected period')).toBeTruthy();

  await user.click(screen.getByRole('button', { name: 'Month' }));

  const yearGrid = await screen.findByTestId('return-calendar-year-grid');
  const januaryCell = within(yearGrid).getByRole('button', {
    name: '2026-01 · CN¥200.00',
  });
  const januaryCellValue = within(januaryCell).getByTestId(
    'return-calendar-cell-value',
  );
  expect(januaryCellValue.className).toContain('text-[10px]');
  expect(januaryCellValue.className).toContain('sm:text-[11px]');
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
