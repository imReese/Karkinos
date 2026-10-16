import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import type { BacktestFill } from '../api';

const points = [
  { timestamp: '2026-06-01T15:00:00+08:00', equity: 100000 },
  { timestamp: '2026-06-02T15:00:00+08:00', equity: 101200 },
];

const fills: BacktestFill[] = [
  {
    fill_id: 'fill-buy-1',
    timestamp: '2026-06-01T10:30:00+08:00',
    symbol: 'SYN001',
    side: 'buy',
    fill_price: 10.23,
    fill_quantity: 100,
    commission: 5,
    slippage: 0,
  },
  {
    fill_id: 'fill-sell-1',
    timestamp: '2026-06-02T10:30:00+08:00',
    symbol: 'SYN001',
    side: 'sell',
    fill_price: 10.88,
    fill_quantity: 100,
    commission: 5,
    slippage: 0,
  },
];
const originalResizeObserver = window.ResizeObserver;

function mockChartGeometry() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      const textMeasurement = this.id === 'recharts_measurement_span';
      const width = textMeasurement ? (this.textContent?.length ?? 1) * 7 : 640;
      const height = textMeasurement ? 12 : 320;
      return {
        bottom: height,
        height,
        left: 0,
        right: width,
        top: 0,
        width,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    },
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, 'ResizeObserver', {
    configurable: true,
    value: originalResizeObserver,
  });
});

test('summarizes buy and sell markers beside the backtest equity curve', () => {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'zh');
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));

  render(
    <PreferencesProvider>
      <EquityDrawdownChart fills={fills} points={points} />
    </PreferencesProvider>,
  );

  expect(screen.getByText('买卖点')).toBeTruthy();
  expect(screen.getByText('买入 · SYN001')).toBeTruthy();
  expect(screen.getByText('卖出 · SYN001')).toBeTruthy();
  expect(screen.getByText('10.2300')).toBeTruthy();
  expect(screen.getByText('10.8800')).toBeTruthy();
  expect(
    screen
      .getByTestId('backtest-equity-chart-frame')
      .getAttribute('aria-label'),
  ).toContain('净值与回撤. 2 个点. 2 个点位.');
  expect(
    screen
      .getByTestId('backtest-drawdown-chart-frame')
      .getAttribute('aria-label'),
  ).toContain('回撤. 2 个点.');
  expect(document.querySelector('.recharts-responsive-container')).toBeNull();
});

test('keeps drawdown gradient identities unique across coexisting reports', () => {
  Object.defineProperty(window, 'ResizeObserver', {
    configurable: true,
    value: undefined,
  });
  mockChartGeometry();

  render(
    <PreferencesProvider>
      <EquityDrawdownChart points={points} />
      <EquityDrawdownChart points={points} />
    </PreferencesProvider>,
  );

  const gradientIds = Array.from(
    document.querySelectorAll(
      'linearGradient[id^="backtest-equity-"], linearGradient[id^="backtest-drawdown-"]',
    ),
    (gradient) => gradient.id,
  );
  expect(gradientIds).toHaveLength(4);
  expect(new Set(gradientIds).size).toBe(4);
  expect(document.querySelectorAll('.recharts-wrapper')).toHaveLength(4);
});

test('uses legible amount ticks around a small equity change instead of forcing a zero baseline', async () => {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  Object.defineProperty(window, 'ResizeObserver', {
    configurable: true,
    value: undefined,
  });
  mockChartGeometry();
  const unchangedPoints = [
    { timestamp: '2026-09-15T15:00:00+08:00', equity: 100000 },
    { timestamp: '2026-09-16T15:00:00+08:00', equity: 98000 },
    { timestamp: '2026-09-17T15:00:00+08:00', equity: 99000 },
  ];
  render(
    <PreferencesProvider>
      <EquityDrawdownChart points={unchangedPoints} />
    </PreferencesProvider>,
  );
  const frame = screen.getByTestId('backtest-equity-chart-frame');
  await waitFor(() =>
    expect(
      frame.querySelectorAll('.recharts-yAxis-tick-labels text').length,
    ).toBeGreaterThanOrEqual(3),
  );
  const labels = Array.from(
    frame.querySelectorAll('.recharts-yAxis-tick-labels text'),
    (element) => element.textContent ?? '',
  );
  const ticks = labels.map((label) => Number(label.replace(/,/g, '')));
  expect(ticks.length).toBeGreaterThanOrEqual(3);
  expect(Math.min(...ticks)).toBeGreaterThan(90000);
  expect(Math.max(...ticks)).toBeGreaterThanOrEqual(100000);
  expect(labels.some((label) => label.includes(','))).toBe(true);
  expect(unchangedPoints.map((point) => point.equity)).toEqual([
    100000, 98000, 99000,
  ]);
});

test('allows filtering markers by side or hiding them', () => {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'zh');
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));

  render(
    <PreferencesProvider>
      <EquityDrawdownChart fills={fills} points={points} />
    </PreferencesProvider>,
  );

  const filterControls = screen.getByTestId('backtest-marker-filter-controls');
  expect(filterControls).toBeTruthy();

  // Click "买入 (1)"
  const buyBtn = screen.getByRole('button', { name: /买入/ });
  fireEvent.click(buyBtn);
  expect(screen.getByText('买入 · SYN001')).toBeTruthy();
  expect(screen.queryByText('卖出 · SYN001')).toBeNull();

  // Click "隐藏"
  const hideBtn = screen.getByRole('button', { name: /隐藏/ });
  fireEvent.click(hideBtn);
  expect(screen.queryByText('买入 · SYN001')).toBeNull();
  expect(screen.queryByText('卖出 · SYN001')).toBeNull();
});
