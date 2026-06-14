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
  },
  {
    date: '2025-12-31',
    equity: 100000,
    delta: 1000,
    external_flow: 500,
    market_pnl: 500,
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
  expect(screen.getByTestId('return-calendar-month-grid')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '2026-02-10 · CN¥800.00' }),
  ).toBeTruthy();

  await userEvent.click(
    screen.getByRole('button', { name: '2026-02-10 · CN¥800.00' }),
  );

  expect(await screen.findByText('2026-02-10')).toBeTruthy();
  const selectedPeriod = screen
    .getByText('Selected period')
    .closest('div')?.parentElement;
  expect(selectedPeriod).toBeTruthy();
  expect(within(selectedPeriod!).getByText('Market move')).toBeTruthy();
  expect(within(selectedPeriod!).getByText('CN¥600.00')).toBeTruthy();
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
    within(yearGrid).getByRole('button', { name: '2026-02 · CN¥800.00' }),
  ).toBeTruthy();

  await user.selectOptions(screen.getByLabelText('Calendar period'), 'years');

  const yearsGrid = await screen.findByTestId('return-calendar-years-grid');
  expect(
    within(yearsGrid).getByRole('button', { name: '2026 · CN¥1,000.00' }),
  ).toBeTruthy();
  expect(
    within(yearsGrid).getByRole('button', { name: '2025 · CN¥1,000.00' }),
  ).toBeTruthy();
});

test('supports a compact cockpit layout for the overview page', async () => {
  renderCalendar({ compact: true });

  const panel = await screen.findByTestId('return-calendar-card');
  expect(panel.className).toContain('p-4');
  expect(panel.className).not.toContain('rounded-2xl');
  expect(screen.getByTestId('return-calendar-month-grid')).toBeTruthy();
  expect(screen.getByText('Selected period')).toBeTruthy();
});
