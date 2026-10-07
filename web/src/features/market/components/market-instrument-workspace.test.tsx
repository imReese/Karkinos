import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { MarketHealthQuote, ResearchBoardItem } from '../api';
import { MarketInstrumentWorkspace } from './market-instrument-workspace';

beforeEach(() => {
  window.localStorage.clear();
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

function renderWorkspace(ui: ReactElement, locale: 'en' | 'zh' = 'zh') {
  window.localStorage.setItem('karkinos.locale', locale);
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en-US';
  return render(<PreferencesProvider>{ui}</PreferencesProvider>);
}

const mockItems: ResearchBoardItem[] = [
  {
    symbol: '600519',
    asset_class: 'stock',
    name: '贵州茅台',
    is_holding: true,
    quantity: 100,
    avg_cost: 1500,
    market_value: 160000,
    unrealized_pnl: 10000,
    realized_pnl: 0,
    last_snapshot_at: null,
    price: 1600,
    volume: 1000,
    research_count: 2,
    last_research_at: null,
  },
  {
    symbol: '000001',
    asset_class: 'stock',
    name: '平安银行',
    is_holding: false,
    quantity: 0,
    avg_cost: 0,
    market_value: 0,
    unrealized_pnl: 0,
    realized_pnl: 0,
    last_snapshot_at: null,
    price: 12,
    volume: 5000,
    research_count: 1,
    last_research_at: null,
  },
  {
    symbol: '000001.OF',
    asset_class: 'fund',
    name: '华夏成长',
    is_holding: false,
    quantity: 0,
    avg_cost: 0,
    market_value: 0,
    unrealized_pnl: 0,
    realized_pnl: 0,
    last_snapshot_at: null,
    price: 1.5,
    volume: 0,
    research_count: 0,
    last_research_at: null,
  },
];

const mockHealthQuotes = new Map<string, MarketHealthQuote>([
  [
    '600519',
    {
      symbol: '600519',
      asset_class: 'stock',
      timestamp: '2026-09-11T15:00:00+08:00',
      price: 1600,
      daily_change: 30,
      quote_status: 'confirmed',
      quote_source: 'tushare_daily',
      quote_age_seconds: 120,
      stale_reason: null,
      last_refresh_attempt: null,
      last_refresh_error: null,
    },
  ],
  [
    '000001',
    {
      symbol: '000001',
      asset_class: 'stock',
      timestamp: '2026-09-11T15:00:00+08:00',
      price: 12,
      daily_change: -0.5,
      quote_status: 'confirmed',
      quote_source: 'tushare_daily',
      quote_age_seconds: 120,
      stale_reason: null,
      last_refresh_attempt: null,
      last_refresh_error: null,
    },
  ],
  [
    '000001.OF',
    {
      symbol: '000001.OF',
      asset_class: 'fund',
      timestamp: '2026-09-11T15:00:00+08:00',
      price: 1.5,
      daily_change: 0.05,
      quote_status: 'confirmed',
      quote_source: 'tushare_fund_nav',
      quote_age_seconds: 300,
      stale_reason: null,
      last_refresh_attempt: null,
      last_refresh_error: null,
    },
  ],
]);

test.each([
  {
    name: 'a stored stock quote with a healthy status and cross-day timestamp',
    item: mockItems[0],
    patch: {
      quote_status: 'live',
      quote_age_seconds: 29 * 60 * 60,
      using_persistent_cache: true,
    } satisfies Partial<MarketHealthQuote>,
    label: '行情记录',
    cacheLabel: '缓存记录',
  },
  {
    name: 'published NAV whose freshness status is live',
    item: mockItems[2],
    patch: {
      quote_status: 'live',
      quote_source: 'tushare_fund_nav',
      nav_date: '2026-09-10',
    } satisfies Partial<MarketHealthQuote>,
    label: '已公布净值',
    cacheLabel: null,
  },
  {
    name: 'an unconfirmed fund estimate',
    item: mockItems[2],
    patch: {
      quote_status: 'estimated',
      quote_source: 'eastmoney_fund_estimate',
    } satisfies Partial<MarketHealthQuote>,
    label: '估算净值 · 非确认数据',
    cacheLabel: null,
  },
  {
    name: 'a stale daily quote',
    item: mockItems[0],
    patch: { quote_status: 'stale' } satisfies Partial<MarketHealthQuote>,
    label: '行情记录 · 待更新',
    cacheLabel: null,
  },
])(
  'presents pricing and storage separately for $name',
  ({ item, patch, label, cacheLabel }) => {
    const quote = { ...mockHealthQuotes.get(item.symbol)!, ...patch };
    renderWorkspace(
      <MarketInstrumentWorkspace
        items={[item]}
        healthBySymbol={new Map([[item.symbol, quote]])}
        activeSymbol={item.symbol}
        selectedItem={item}
        selectedHealthQuote={quote}
        selectedQuoteNextAction={null}
        bars={[]}
        barsLoading={false}
        barsError={false}
        onRetryBars={vi.fn()}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
      />,
    );

    const detail = within(screen.getByTestId('market-selected-instrument'));
    expect(detail.getByText(label)).toBeInTheDocument();
    expect(
      screen.getByTestId(`market-instrument-status-${item.symbol}`),
    ).toHaveTextContent(label);
    expect(screen.queryByText('实时行情')).not.toBeInTheDocument();
    if (cacheLabel) {
      expect(detail.getByText(cacheLabel)).toBeInTheDocument();
      expect(detail.queryByText(/待更新|已过期/)).not.toBeInTheDocument();
    }
    if (quote.nav_date) {
      expect(
        detail.getByText(`净值日期 ${quote.nav_date}`),
      ).toBeInTheDocument();
    }
  },
);

test('renders sort header and sorts by daily change descending, ascending, and resets to default', () => {
  renderWorkspace(
    <MarketInstrumentWorkspace
      items={mockItems}
      healthBySymbol={mockHealthQuotes}
      activeSymbol="600519"
      selectedItem={mockItems[0]}
      selectedHealthQuote={mockHealthQuotes.get('600519')!}
      selectedQuoteNextAction={null}
      bars={[]}
      barsLoading={false}
      barsError={false}
      onRetryBars={vi.fn()}
      onSelect={vi.fn()}
      onRemove={vi.fn()}
    />,
    'zh',
  );

  const sortHeader = screen.getByTestId('market-watchlist-sort-header');
  expect(sortHeader).toBeInTheDocument();

  // Find sort buttons
  const changePctSortBtn = screen.getByRole('button', { name: /涨跌幅/ });
  const changeAmountSortBtn = screen.getByRole('button', { name: /涨跌额/ });
  const priceSortBtn = screen.getByRole('button', { name: /最新价/ });
  const symbolSortBtn = screen.getByRole('button', { name: /名称代码/ });

  expect(changePctSortBtn).toBeInTheDocument();
  expect(changeAmountSortBtn).toBeInTheDocument();
  expect(priceSortBtn).toBeInTheDocument();
  expect(symbolSortBtn).toBeInTheDocument();

  // Initially in default order: 600519, 000001, 000001.OF
  const getRenderedSymbols = () => {
    const list = screen.getByTestId('market-instrument-list');
    return Array.from(
      list.querySelectorAll('[data-market-instrument-row]'),
    ).map((el) => el.getAttribute('data-market-instrument-row'));
  };

  expect(getRenderedSymbols()).toEqual(['600519', '000001', '000001.OF']);

  // Test 1: Daily Change Percentage (涨跌幅 %)
  // Click 1: Percentage descending (涨幅榜: 000001.OF(+3.45%), 600519(+1.91%), 000001(-4.00%))
  fireEvent.click(changePctSortBtn);
  expect(getRenderedSymbols()).toEqual(['000001.OF', '600519', '000001']);

  // Click 2: Percentage ascending (跌幅榜: 000001(-4.00%), 600519(+1.91%), 000001.OF(+3.45%))
  fireEvent.click(changePctSortBtn);
  expect(getRenderedSymbols()).toEqual(['000001', '600519', '000001.OF']);

  // Click 3: Resets to default
  fireEvent.click(changePctSortBtn);
  expect(getRenderedSymbols()).toEqual(['600519', '000001', '000001.OF']);

  // Test 2: Daily Change Amount (涨跌额 ¥)
  // Click 1: Amount descending (+30: 600519, +0.05: 000001.OF, -0.5: 000001)
  fireEvent.click(changeAmountSortBtn);
  expect(getRenderedSymbols()).toEqual(['600519', '000001.OF', '000001']);

  // Click 2: Amount ascending (-0.5: 000001, +0.05: 000001.OF, +30: 600519)
  fireEvent.click(changeAmountSortBtn);
  expect(getRenderedSymbols()).toEqual(['000001', '000001.OF', '600519']);

  // Click 3: Resets to default
  fireEvent.click(changeAmountSortBtn);
  expect(getRenderedSymbols()).toEqual(['600519', '000001', '000001.OF']);
});

test('sorts by price descending and resets with Reset button', () => {
  renderWorkspace(
    <MarketInstrumentWorkspace
      items={mockItems}
      healthBySymbol={mockHealthQuotes}
      activeSymbol="600519"
      selectedItem={mockItems[0]}
      selectedHealthQuote={mockHealthQuotes.get('600519')!}
      selectedQuoteNextAction={null}
      bars={[]}
      barsLoading={false}
      barsError={false}
      onRetryBars={vi.fn()}
      onSelect={vi.fn()}
      onRemove={vi.fn()}
    />,
    'zh',
  );

  const priceSortBtn = screen.getByRole('button', { name: /最新价/ });
  const getRenderedSymbols = () => {
    const list = screen.getByTestId('market-instrument-list');
    return Array.from(
      list.querySelectorAll('[data-market-instrument-row]'),
    ).map((el) => el.getAttribute('data-market-instrument-row'));
  };

  // Sort by price desc: 600519 (1600), 000001 (12), 000001.OF (1.5)
  fireEvent.click(priceSortBtn);
  expect(getRenderedSymbols()).toEqual(['600519', '000001', '000001.OF']);

  // Sort by price asc: 000001.OF (1.5), 000001 (12), 600519 (1600)
  fireEvent.click(priceSortBtn);
  expect(getRenderedSymbols()).toEqual(['000001.OF', '000001', '600519']);

  // Reset button should now be visible
  const resetBtn = screen.getByRole('button', { name: '重置' });
  expect(resetBtn).toBeInTheDocument();
  fireEvent.click(resetBtn);

  // Restores default order
  expect(getRenderedSymbols()).toEqual(['600519', '000001', '000001.OF']);
});

test('filters watchlist items by category pills', () => {
  renderWorkspace(
    <MarketInstrumentWorkspace
      items={mockItems}
      healthBySymbol={mockHealthQuotes}
      activeSymbol="600519"
      selectedItem={mockItems[0]}
      selectedHealthQuote={mockHealthQuotes.get('600519')!}
      selectedQuoteNextAction={null}
      bars={[]}
      barsLoading={false}
      barsError={false}
      onRetryBars={vi.fn()}
      onSelect={vi.fn()}
      onRemove={vi.fn()}
    />,
    'zh',
  );

  // Category filter rendered because there are both stocks and fund
  const catFilter = screen.getByTestId('market-watchlist-category-filter');
  expect(catFilter).toBeInTheDocument();

  const allBtn = screen.getByRole('button', { name: /全部 \(3\)/ });
  const stockBtn = screen.getByRole('button', { name: /股票 \(2\)/ });
  const fundBtn = screen.getByRole('button', { name: /基金 \(1\)/ });

  expect(allBtn).toBeInTheDocument();
  expect(stockBtn).toBeInTheDocument();
  expect(fundBtn).toBeInTheDocument();

  const getRenderedSymbols = () => {
    const list = screen.getByTestId('market-instrument-list');
    return Array.from(
      list.querySelectorAll('[data-market-instrument-row]'),
    ).map((el) => el.getAttribute('data-market-instrument-row'));
  };

  // Click Fund filter
  fireEvent.click(fundBtn);
  expect(getRenderedSymbols()).toEqual(['000001.OF']);

  // Click Stock filter
  fireEvent.click(stockBtn);
  expect(getRenderedSymbols()).toEqual(['600519', '000001']);

  // Click All filter
  fireEvent.click(allBtn);
  expect(getRenderedSymbols()).toEqual(['600519', '000001', '000001.OF']);
});

test('renders holding badge for held instruments and copy symbol button in detail header', async () => {
  renderWorkspace(
    <MarketInstrumentWorkspace
      items={mockItems}
      healthBySymbol={mockHealthQuotes}
      activeSymbol="600519"
      selectedItem={mockItems[0]}
      selectedHealthQuote={mockHealthQuotes.get('600519')!}
      selectedQuoteNextAction={null}
      bars={[]}
      barsLoading={false}
      barsError={false}
      onRetryBars={vi.fn()}
      onSelect={vi.fn()}
      onRemove={vi.fn()}
    />,
    'zh',
  );

  // 600519 has is_holding: true, 000001 has is_holding: false
  const holdingBadge = screen.getByTestId(
    'market-instrument-holding-badge-600519',
  );
  expect(holdingBadge).toBeInTheDocument();
  expect(holdingBadge).toHaveTextContent('持仓');

  expect(
    screen.queryByTestId('market-instrument-holding-badge-000001'),
  ).not.toBeInTheDocument();

  // Copy symbol button in detail header
  const copyBtn = screen.getByTestId('market-copy-symbol-btn');
  expect(copyBtn).toBeInTheDocument();
  expect(copyBtn).toHaveTextContent('600519');

  // Holding badge in detail header
  expect(
    screen.getByTestId('market-selected-holding-badge'),
  ).toBeInTheDocument();
});

test('renders holding cost cushion lens when item is held', () => {
  renderWorkspace(
    <MarketInstrumentWorkspace
      items={mockItems}
      healthBySymbol={mockHealthQuotes}
      activeSymbol="600519"
      selectedItem={mockItems[0]}
      selectedHealthQuote={mockHealthQuotes.get('600519')!}
      selectedQuoteNextAction={null}
      bars={[]}
      barsLoading={false}
      barsError={false}
      onRetryBars={vi.fn()}
      onSelect={vi.fn()}
      onRemove={vi.fn()}
    />,
    'zh',
  );

  const cushion = screen.getByTestId('market-holding-cost-cushion');
  expect(cushion).toBeInTheDocument();
  expect(cushion).toHaveTextContent('持仓成本透视');
  expect(cushion).toHaveTextContent('浮盈安全垫');
});
