import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { getCopy } from '../../app/copy';
import { PreferencesProvider } from '../../app/preferences';
import { LiveHoldingsBoard } from './components/live-holdings-board';

function renderBoard(locale: 'en' | 'zh' = 'en') {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', locale);
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en-US';
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: query.includes('light'),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true,
    }),
  });

  render(
    <PreferencesProvider>
      <LiveHoldingsBoard
        groups={[
          {
            asset_class: 'fund',
            label: locale === 'zh' ? '基金' : 'Fund',
            total_market_value: 1200,
            total_today_change: 50,
            total_since_buy_pnl: 200,
            items: [
              {
                symbol: '000001',
                name: locale === 'zh' ? '示例基金' : 'Example Fund',
                asset_class: 'fund',
                quantity: 100,
                avg_cost: 10,
                market_value: 1200,
                latest_price: 12,
                quote_timestamp: '2026-04-21T14:30:00',
                since_buy_pnl: 200,
                since_buy_pnl_pct: 0.2,
                today_change: 50,
                today_change_pct: 0.04,
                baseline_price: 11.5,
                baseline_timestamp: '2026-04-20T15:00:00',
                baseline_source: 'previous_quote',
                quote_status: 'live',
              },
            ],
          },
        ]}
      />
    </PreferencesProvider>,
  );
}

test('renders holdings quote board in english', () => {
  renderBoard('en');
  const copy = getCopy('en');

  expect(screen.getByText(copy.portfolio.liveBoard.title)).toBeTruthy();
  expect(screen.getByText('Example Fund')).toBeTruthy();
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.latestPrice).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.todayMove).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.sinceBuyReturn).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText(copy.portfolio.liveBoard.quoteLive)).toBeTruthy();
});

test('renders localized holdings quote board in chinese', () => {
  renderBoard('zh');
  const copy = getCopy('zh');

  expect(screen.getByText(copy.portfolio.liveBoard.title)).toBeTruthy();
  expect(screen.getByText('示例基金')).toBeTruthy();
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.latestPrice).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.todayMove).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.sinceBuyReturn).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText(copy.portfolio.liveBoard.quoteLive)).toBeTruthy();
});
