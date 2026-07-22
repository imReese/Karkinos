import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
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
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    bottom: 320,
    height: 320,
    left: 0,
    right: 640,
    top: 0,
    width: 640,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);

  render(
    <PreferencesProvider>
      <EquityDrawdownChart points={points} />
      <EquityDrawdownChart points={points} />
    </PreferencesProvider>,
  );

  const gradientIds = Array.from(
    document.querySelectorAll('linearGradient[id^="backtest-drawdown-"]'),
    (gradient) => gradient.id,
  );
  expect(gradientIds).toHaveLength(2);
  expect(new Set(gradientIds).size).toBe(2);
  expect(document.querySelectorAll('.recharts-wrapper')).toHaveLength(4);
});
