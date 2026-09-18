import '@testing-library/jest-dom/vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { EquitySeriesPoint } from '../api';
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

function chart(data: EquitySeriesPoint[]) {
  return (
    <PreferencesProvider>
      <OverviewEquityCurve
        points={data}
        range="all"
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
    expect(screen.getByTestId('equity-indicative-note')).toBeVisible();
  },
);

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
