import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { BacktestFill } from '../api';
import { FillsTable } from './fills-table';

const fills: BacktestFill[] = [
  {
    timestamp: '2026-06-18T09:31:00+08:00',
    symbol: 'SYN001',
    side: 'buy',
    fill_price: 8.8,
    fill_quantity: 100,
    commission: 5,
    slippage: 0.1,
  },
  {
    timestamp: '2026-06-18T14:56:00+08:00',
    symbol: 'SYN001',
    side: 'sell',
    fill_price: 9.1,
    fill_quantity: 100,
    commission: 5,
    slippage: 0.1,
  },
];

function renderFillsTable(locale: 'en' | 'zh', rows: BacktestFill[] = fills) {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', locale);
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));

  render(
    <PreferencesProvider>
      <FillsTable fills={rows} />
    </PreferencesProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('localizes backtest fill directions through the shared ledger labels', () => {
  renderFillsTable('zh');

  expect(screen.getByText('买入')).toBeTruthy();
  expect(screen.getByText('卖出')).toBeTruthy();
  expect(screen.queryByText('BUY')).toBeNull();
  expect(screen.queryByText('SELL')).toBeNull();
});

test('uses public review fallback for unknown fill directions', () => {
  renderFillsTable('en', [
    {
      ...fills[0],
      side: 'broker_special_side',
    },
  ]);

  expect(screen.getByText('Status needs review')).toBeTruthy();
  expect(screen.queryByText('broker_special_side')).toBeNull();
  expect(screen.queryByText('Buy')).toBeNull();
});
