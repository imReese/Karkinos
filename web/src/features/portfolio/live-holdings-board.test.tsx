import { render, screen, within } from '@testing-library/react';
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
            asset_class: 'stock',
            label: locale === 'zh' ? '股票' : 'Stock',
            total_market_value: 1800,
            total_today_change: -20,
            total_since_buy_pnl: 300,
            items: [
              {
                symbol: '600519',
                name: locale === 'zh' ? '贵州茅台' : 'Kweichow Moutai',
                display_name: locale === 'zh' ? '贵州茅台' : 'Kweichow Moutai',
                asset_class: 'stock',
                quantity: 1,
                avg_cost: 1500,
                market_value: 1800,
                latest_price: 1800,
                quote_timestamp: '2026-04-21T14:30:00',
                since_buy_pnl: 300,
                since_buy_pnl_pct: 0.2,
                today_change: -20,
                today_change_pct: -0.011,
                baseline_price: 1820,
                baseline_timestamp: '2026-04-20T15:00:00',
                baseline_source: 'previous_close',
                quote_status: 'live',
              },
            ],
          },
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
  expect(screen.getByText('Kweichow Moutai')).toBeTruthy();
  expect(screen.getByText('600519')).toBeTruthy();
  expect(screen.getAllByText('Stock').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Fund').length).toBeGreaterThan(0);
  expect(screen.getAllByText('1 active holding').length).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.latestPrice).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.todayMove).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.sinceBuyReturn).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.quoteLive).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText('-1.10%')).toBeTruthy();
  expect(
    screen.getByRole('link', {
      name: copy.portfolio.liveBoard.holdingDetailLink('600519'),
    }),
  ).toHaveProperty('href', expect.stringContaining('/portfolio/600519'));
  expect(screen.queryByText('Avg Cost CN¥1,500.00')).toBeNull();
  expect(screen.queryByText('-1.1%')).toBeNull();
});

test('groups summary values with their labels in the asset cards', () => {
  renderBoard('en');
  const copy = getCopy('en');

  const stockSummary = screen.getByTestId('live-holdings-group-summary-stock');
  const stockMarketValue = within(stockSummary).getByTestId(
    'live-holdings-group-summary-stock-market-value',
  );
  const stockTodayMove = within(stockSummary).getByTestId(
    'live-holdings-group-summary-stock-today-move',
  );
  const stockSinceBuy = within(stockSummary).getByTestId(
    'live-holdings-group-summary-stock-since-buy',
  );

  expect(within(stockMarketValue).getByText(copy.portfolio.table.marketValue));
  expect(within(stockMarketValue).getByText('CN¥1,800.00'));
  expect(within(stockTodayMove).getByText(copy.portfolio.liveBoard.todayMove));
  expect(within(stockTodayMove).getByText('-CN¥20.00'));
  expect(
    within(stockSinceBuy).getByText(copy.portfolio.liveBoard.sinceBuyReturn),
  );
  expect(within(stockSinceBuy).getByText('CN¥300.00'));
});

test('renders localized holdings quote board in chinese', () => {
  renderBoard('zh');
  const copy = getCopy('zh');

  expect(screen.getByText(copy.portfolio.liveBoard.title)).toBeTruthy();
  expect(screen.getByText('示例基金')).toBeTruthy();
  expect(screen.getByText('贵州茅台')).toBeTruthy();
  expect(screen.getByText('600519')).toBeTruthy();
  expect(screen.getAllByText('股票').length).toBeGreaterThan(0);
  expect(screen.getAllByText('基金').length).toBeGreaterThan(0);
  expect(screen.getAllByText('1 个活跃持仓').length).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.latestPrice).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.todayMove).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.sinceBuyReturn).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(copy.portfolio.liveBoard.quoteLive).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByRole('link', {
      name: copy.portfolio.liveBoard.holdingDetailLink('600519'),
    }),
  ).toHaveProperty('href', expect.stringContaining('/portfolio/600519'));
});
