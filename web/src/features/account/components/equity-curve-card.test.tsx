import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { EquityCurveCard, EquityCurveSkeleton } from './equity-curve-card';
import type { EquitySeriesPoint } from '../api';

const points: EquitySeriesPoint[] = [
  {
    timestamp: '2026-04-18T09:00:00+00:00',
    total: 100000,
    stocks: 0,
    funds: 0,
    others: 0,
    cash: 100000,
  },
  {
    timestamp: '2026-04-18T10:00:00+00:00',
    total: 101550,
    stocks: 11000,
    funds: 5300,
    others: 9250,
    cash: 76000,
  },
];

const historicalPoints: EquitySeriesPoint[] = [
  {
    timestamp: '2025-01-01T09:00:00+00:00',
    total: 82000,
    stocks: 21000,
    funds: 12000,
    others: 4000,
    cash: 45000,
  },
  {
    timestamp: '2025-02-10T09:00:00+00:00',
    total: 83500,
    stocks: 22000,
    funds: 12500,
    others: 5000,
    cash: 44000,
  },
];

const timelinePoints: EquitySeriesPoint[] = [
  {
    timestamp: '2025-01-01T09:00:00+00:00',
    total: 82000,
    stocks: 21000,
    funds: 12000,
    others: 4000,
    cash: 45000,
  },
  {
    timestamp: '2025-03-01T09:00:00+00:00',
    total: 84000,
    stocks: 22500,
    funds: 12200,
    others: 4200,
    cash: 45100,
  },
  {
    timestamp: '2025-05-01T09:00:00+00:00',
    total: 86000,
    stocks: 23600,
    funds: 12800,
    others: 4700,
    cash: 44900,
  },
  {
    timestamp: '2025-07-01T09:00:00+00:00',
    total: 87500,
    stocks: 24100,
    funds: 13300,
    others: 5200,
    cash: 44900,
  },
  {
    timestamp: '2025-09-01T09:00:00+00:00',
    total: 89200,
    stocks: 25500,
    funds: 13600,
    others: 5800,
    cash: 44300,
  },
  {
    timestamp: '2025-11-01T09:00:00+00:00',
    total: 91000,
    stocks: 26800,
    funds: 14100,
    others: 6100,
    cash: 44000,
  },
];

const intradayPoints: EquitySeriesPoint[] = [
  {
    timestamp: '2026-04-18T09:30:00+08:00',
    total: 89000,
    stocks: 10000,
    funds: 3000,
    others: 0,
    cash: 76000,
    unrealized_pnl: 0,
  },
  {
    timestamp: '2026-04-18T09:35:00+08:00',
    total: 89150,
    stocks: 10050,
    funds: 3100,
    others: 0,
    cash: 76000,
    unrealized_pnl: 150,
  },
  {
    timestamp: '2026-04-18T09:40:00+08:00',
    total: 89300,
    stocks: 10100,
    funds: 3200,
    others: 0,
    cash: 76000,
    unrealized_pnl: 300,
  },
];

const updatedPoints: EquitySeriesPoint[] = [
  {
    timestamp: '2026-05-10T09:30:00+08:00',
    total: 103000,
    stocks: 12000,
    funds: 6000,
    others: 9000,
    cash: 76000,
  },
  {
    timestamp: '2026-05-11T10:00:00+08:00',
    total: 104200,
    stocks: 12600,
    funds: 6100,
    others: 9500,
    cash: 76000,
  },
];

const backendCurrentPoints: EquitySeriesPoint[] = [
  {
    timestamp: '2026-05-16T09:30:00+08:00',
    total: 102800,
    stocks: 12200,
    funds: 6100,
    others: 9500,
    cash: 75000,
    unrealized_pnl: 1800,
  },
  {
    timestamp: '2026-05-17T14:30:00+08:00',
    total: 104600,
    stocks: 13000,
    funds: 6200,
    others: 9800,
    cash: 75600,
    unrealized_pnl: 2600,
    quote_status: 'stale',
  },
];

const sparseLedgerPoints: EquitySeriesPoint[] = [
  {
    timestamp: '2026-04-13T14:27:00+08:00',
    total: 103900,
    stocks: 0,
    funds: 1780,
    others: 0,
    cash: 102120,
  },
  {
    timestamp: '2026-04-23T14:46:00+08:00',
    total: 104100,
    stocks: 0,
    funds: 2050,
    others: 0,
    cash: 102050,
  },
  {
    timestamp: '2026-05-26T00:39:00+08:00',
    total: 104350,
    stocks: 0,
    funds: 2110,
    others: 0,
    cash: 102240,
    quote_status: 'stale',
  },
];

function renderCard({
  cardPoints = points,
  onRangeChange,
}: {
  cardPoints?: EquitySeriesPoint[];
  onRangeChange?: (range: string) => void;
} = {}) {
  const originalWarn = console.warn;
  vi.spyOn(console, 'warn').mockImplementation((message?: unknown) => {
    if (
      typeof message === 'string' &&
      message.includes(
        'The width(-1) and height(-1) of chart should be greater than 0',
      )
    ) {
      return;
    }
    originalWarn(message);
  });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    value: 800,
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    value: 380,
  });
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({
      bottom: 380,
      height: 380,
      left: 0,
      right: 800,
      top: 0,
      width: 800,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }),
  });
  window.ResizeObserver = class ResizeObserver {
    private readonly callback: ResizeObserverCallback;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }

    observe(target: Element) {
      this.callback(
        [
          {
            target,
            contentRect: {
              bottom: 380,
              height: 380,
              left: 0,
              right: 800,
              top: 0,
              width: 800,
              x: 0,
              y: 0,
              toJSON: () => ({}),
            },
          } as ResizeObserverEntry,
        ],
        this,
      );
    }

    unobserve() {}

    disconnect() {}
  };
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

  return render(
    <PreferencesProvider>
      <EquityCurveCard points={cardPoints} onRangeChange={onRangeChange} />
    </PreferencesProvider>,
  );
}

test('renders premium performance dashboard controls', async () => {
  renderCard();

  expect(await screen.findByText('Performance Analysis')).toBeTruthy();
  for (const label of ['Total', 'Stocks', 'Funds', 'Others', 'Cash']) {
    const chip = await screen.findByRole('button', { name: label });
    expect(chip.className).toContain('rounded-full');
    expect(chip.getAttribute('aria-pressed')).toBe('true');
  }

  for (const label of ['1D', '5D', '1M', '6M', '1Y', 'ALL']) {
    expect(
      await screen.findByRole('button', { name: `Range: ${label}` }),
    ).toBeTruthy();
  }

  expect(
    (await screen.findByRole('button', { name: 'Range: 1M' })).getAttribute(
      'aria-pressed',
    ),
  ).toBe('true');
});

test('toggles category chips without removing the control', async () => {
  renderCard();
  const user = userEvent.setup();

  const stocks = await screen.findByRole('button', { name: 'Stocks' });
  await user.click(stocks);

  expect(stocks.getAttribute('aria-pressed')).toBe('false');
});

test('updates the active range and notifies the parent query layer', async () => {
  const user = userEvent.setup();
  const onRangeChange = vi.fn();

  renderCard({ onRangeChange });

  const oneYear = await screen.findByRole('button', { name: 'Range: 1Y' });
  await user.click(oneYear);

  expect(oneYear.getAttribute('aria-pressed')).toBe('true');
  expect(onRangeChange).toHaveBeenCalledWith('1y');
});

test('notifies the parent query layer for every long-range switch', async () => {
  const user = userEvent.setup();
  const onRangeChange = vi.fn();

  renderCard({ cardPoints: timelinePoints, onRangeChange });

  for (const [label, value] of [
    ['6M', '6m'],
    ['1Y', '1y'],
    ['ALL', 'all'],
  ] as const) {
    await user.click(
      await screen.findByRole('button', { name: `Range: ${label}` }),
    );
    expect(onRangeChange).toHaveBeenLastCalledWith(value);
  }
});

test('renders the backend current stale point without adding a synthetic point', async () => {
  renderCard({ cardPoints: backendCurrentPoints });

  expect(await screen.findByText('Valuation uses cached quotes')).toBeTruthy();
  expect(screen.getAllByText(/05-17\s+14:30/).length).toBeGreaterThan(0);
});

test('refreshes stale status when backend points prop changes', async () => {
  const view = renderCard();

  expect(screen.queryByText('Valuation uses cached quotes')).toBeNull();

  view.rerender(
    <PreferencesProvider>
      <EquityCurveCard points={backendCurrentPoints} />
    </PreferencesProvider>,
  );

  expect(await screen.findByText('Valuation uses cached quotes')).toBeTruthy();
  expect(screen.getAllByText(/05-17\s+14:30/).length).toBeGreaterThan(0);
});

test('shows the insufficient data state when a selected range has only one point', async () => {
  const user = userEvent.setup();

  renderCard({ cardPoints: historicalPoints });

  await user.click(await screen.findByRole('button', { name: 'Range: 1D' }));

  expect(
    await screen.findByText('Insufficient data for this range.'),
  ).toBeTruthy();
});

test('renders flat two-point ranges from backend data', async () => {
  renderCard({
    cardPoints: [
      {
        timestamp: '2026-05-17T14:30:00+08:00',
        total: 104600,
        stocks: 13000,
        funds: 6200,
        others: 9800,
        cash: 75600,
      },
      {
        timestamp: '2026-05-18T10:00:00+08:00',
        total: 104600,
        stocks: 13000,
        funds: 6200,
        others: 9800,
        cash: 75600,
        quote_status: 'stale',
      },
    ],
  });

  expect(await screen.findByText('Valuation uses cached quotes')).toBeTruthy();
  expect(screen.queryByText('Insufficient data for this range.')).toBeNull();
  expect(screen.queryByText('Current valuation point')).toBeNull();
});

test('keeps 1m and 5d ranges usable when ledger history is sparse', async () => {
  const user = userEvent.setup();

  renderCard({ cardPoints: sparseLedgerPoints });

  expect(await screen.findByText('Valuation uses cached quotes')).toBeTruthy();
  expect(screen.queryByText('Insufficient data for this range.')).toBeNull();
  expect(screen.queryByText('Current valuation point')).toBeNull();

  await user.click(await screen.findByRole('button', { name: 'Range: 5D' }));

  expect(screen.queryByText('Insufficient data for this range.')).toBeNull();
  expect(screen.queryByText('Current valuation point')).toBeNull();
});

test('renders multiple intermediate time ticks across the selected range', async () => {
  const user = userEvent.setup();

  renderCard({ cardPoints: timelinePoints });

  await user.click(await screen.findByRole('button', { name: 'Range: 1Y' }));

  const tickLabels = screen.getAllByText(/\d{2}-\d{2}\s+\d{2}:\d{2}/);
  expect(tickLabels.length).toBeGreaterThanOrEqual(4);
});

test('updates rendered chart ticks when points change', async () => {
  const view = renderCard();

  expect(await screen.findByText(/04-18\s+18:00/)).toBeTruthy();

  view.rerender(
    <PreferencesProvider>
      <EquityCurveCard points={updatedPoints} />
    </PreferencesProvider>,
  );

  expect(await screen.findByText(/05-11\s+10:00/)).toBeTruthy();
});

test('renders the full intraday session axis for the 1d range', async () => {
  const user = userEvent.setup();

  renderCard({ cardPoints: intradayPoints });

  await user.click(await screen.findByRole('button', { name: 'Range: 1D' }));

  expect(screen.getAllByText(/04-18\s+09:30/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/04-18\s+15:00/).length).toBeGreaterThan(0);
});

test('renders a terminal empty state for periods without chart data', async () => {
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

  render(
    <PreferencesProvider>
      <EquityCurveCard points={[]} />
    </PreferencesProvider>,
  );

  const emptyState = await screen.findByText(
    'No data available for this period.',
  );
  expect(emptyState.className).toContain('text-[var(--app-subtext-0)]');
});

test('renders chart skeleton with shimmer and terminal surface colors', () => {
  render(<EquityCurveSkeleton />);

  const skeleton = screen.getByTestId('equity-curve-skeleton');
  expect(skeleton.className).toContain('animate-pulse');
  expect(skeleton.className).toContain('var(--app-surface-0)');
});
