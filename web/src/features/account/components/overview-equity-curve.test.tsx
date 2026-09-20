import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { EquityCurveRange, EquitySeriesPoint } from '../api';
import { OverviewEquityCurve } from './overview-equity-curve';

const points: EquitySeriesPoint[] = [
  {
    timestamp: '2026-09-10T15:00:00+08:00',
    total: 10100,
    stocks: 100,
    funds: 0,
    others: 0,
    cash: 10000,
  },
  {
    timestamp: '2026-09-11T15:00:00+08:00',
    total: 10200,
    stocks: 200,
    funds: 0,
    others: 0,
    cash: 10000,
  },
];

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
    })),
  });
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      const isTextMeasurement = this.tagName === 'SPAN';
      const width = isTextMeasurement ? 42 : 640;
      const height = isTextMeasurement ? 12 : 280;
      return {
        width,
        height,
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: width,
        bottom: height,
        toJSON: () => ({}),
      };
    },
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function chart(data: EquitySeriesPoint[], range: EquityCurveRange = 'all') {
  return (
    <PreferencesProvider>
      <OverviewEquityCurve
        points={data}
        range={range}
        onRangeChange={() => undefined}
      />
    </PreferencesProvider>
  );
}

test('draws canonical history after an initially empty range becomes populated', async () => {
  const { rerender, container } = render(chart([]));
  expect(screen.queryByTestId('equity-chart-frame')).not.toBeInTheDocument();
  rerender(chart(points));
  expect(await screen.findByTestId('equity-chart-frame')).toBeVisible();
  expect(container.querySelector('path.recharts-line-curve')).not.toBeNull();
});

test('missing canonical totals remain an empty chart rather than becoming zero equity', () => {
  const { container } = render(
    chart(points.map((point) => ({ ...point, total: null }))),
  );
  expect(screen.queryByTestId('equity-chart-frame')).not.toBeInTheDocument();
  expect(container.querySelector('path.recharts-line-curve')).toBeNull();
});

test.each([
  { valuation_status: 'degraded' },
  { quote_status: 'estimated' },
  { quote_status: 'conflicting' },
])(
  'keeps non-authoritative history visible only on the indicative line: %j',
  (evidence) => {
    const data = [0, 1, 2, 3, 4].map((index) => ({
      ...points[index % 2],
      timestamp: `2026-09-${10 + index}T15:00:00+08:00`,
      ...(index === 2 ? evidence : { valuation_status: 'complete' }),
    }));
    const { container } = render(chart(data));
    const paths = container.querySelectorAll('path.recharts-line-curve');
    expect(paths).toHaveLength(2);
    expect(paths[0]?.getAttribute('d')?.match(/M/g)).toHaveLength(1);
    expect(paths[1]?.getAttribute('d')?.match(/M/g)).toHaveLength(2);
  },
);

test('renders reconstructed history as the selected colored solid line', () => {
  const { container } = render(
    chart(
      points.map((point) => ({
        ...point,
        valuation_status: 'reconstructed',
        valuation_policy: 'karkinos.historical_replay.v1',
        quote_status: 'live',
      })),
    ),
  );
  const paths = container.querySelectorAll('path.recharts-line-curve');
  expect(paths).toHaveLength(1);
  expect(paths[0]).toHaveAttribute('stroke', 'var(--app-accent)');
  expect(paths[0]).not.toHaveAttribute('stroke-dasharray');
});

test('bridges a genuine missing valuation with a same-color dashed line', () => {
  const data: EquitySeriesPoint[] = [
    {
      ...points[0],
      valuation_status: 'reconstructed',
      quote_status: 'live',
    },
    {
      ...points[0],
      timestamp: '2026-09-11T15:00:00+08:00',
      total: null,
      valuation_status: 'missing',
      quote_status: 'missing',
    },
    {
      ...points[1],
      timestamp: '2026-09-12T15:00:00+08:00',
      total: 10300,
      valuation_status: 'reconstructed',
      quote_status: 'live',
    },
  ];
  const { container } = render(chart(data));
  const bridge = container.querySelector(
    'path.recharts-line-curve[stroke-dasharray="4 4"]',
  );
  expect(bridge).not.toBeNull();
  expect(bridge).toHaveAttribute('stroke', 'var(--app-accent)');
  expect(bridge?.getAttribute('d')?.match(/M/g)).toHaveLength(1);
});

test('lets overview switch the performance series without changing the time range', async () => {
  render(chart(points));
  const user = userEvent.setup();
  const controls = screen.getByTestId('equity-series-controls');
  const total = within(controls).getByRole('button', { name: 'Total Assets' });
  const cash = within(controls).getByRole('button', { name: 'Cash' });
  expect(total).toHaveAttribute('aria-pressed', 'true');
  expect(cash).toHaveAttribute('aria-pressed', 'false');

  await user.click(cash);

  expect(total).toHaveAttribute('aria-pressed', 'false');
  expect(cash).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByTestId('equity-chart-frame')).toHaveAttribute(
    'aria-label',
    'Cash',
  );
});

test('year-to-date renders a flat zero baseline before the first account point', () => {
  const ytdPoints: EquitySeriesPoint[] = [
    {
      timestamp: '2026-04-01T15:00:00+08:00',
      total: 3000,
      stocks: 0,
      funds: 0,
      others: 0,
      cash: 3000,
      valuation_status: 'reconstructed',
      quote_status: 'live',
    },
    {
      timestamp: '2026-04-02T15:00:00+08:00',
      total: 3000,
      stocks: 0,
      funds: 0,
      others: 0,
      cash: 3000,
      valuation_status: 'reconstructed',
      quote_status: 'live',
    },
  ];
  const { container } = render(chart(ytdPoints, 'ytd'));
  const line = container.querySelector('path.recharts-line-curve');
  expect(line).not.toBeNull();
  expect(line?.getAttribute('d')).toContain('L');
  expect(screen.queryByTestId('equity-history-start')).not.toBeInTheDocument();
});

test('financial axis labels preserve the difference between nearby equity values', async () => {
  const { container } = render(chart(points));
  await waitFor(() =>
    expect(
      container.querySelectorAll('.recharts-yAxis-tick-labels text').length,
    ).toBeGreaterThan(1),
  );
  const labels = Array.from(
    container.querySelectorAll('.recharts-yAxis-tick-labels text'),
  ).map((tick) => tick.textContent);
  expect(labels.length).toBeGreaterThan(1);
  expect(new Set(labels).size).toBe(labels.length);
});
