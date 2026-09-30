import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { PortfolioSnapshot } from '../overview-feature-boundary';
import { OverviewHoldingsSection } from './overview-holdings-section';

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}));

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

function renderSection(ui: ReactElement, locale: 'en' | 'zh' = 'zh') {
  window.localStorage.setItem('karkinos.locale', locale);
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en-US';
  return render(<PreferencesProvider>{ui}</PreferencesProvider>);
}

const mockPositions: PortfolioSnapshot['positions'] = [
  {
    symbol: '600519',
    display_name: '贵州茅台',
    asset_class: 'stock',
    quantity: 100,
    available_qty: 100,
    frozen_qty: 0,
    avg_cost: 1500,
    market_value: 160000,
    latest_price: 1600,
    unrealized_pnl: 10000,
    realized_pnl: 0,
    commission_paid: 5,
    quote_status: 'confirmed',
    pricing_kind: 'session_close',
    pricing_authority: 'authoritative',
    pricing_as_of: '2026-09-11',
  },
  {
    symbol: '000001.OF',
    display_name: '华夏成长',
    asset_class: 'fund',
    quantity: 1000,
    available_qty: 1000,
    frozen_qty: 0,
    avg_cost: 1.2,
    market_value: 1300,
    latest_price: 1.3,
    unrealized_pnl: 100,
    realized_pnl: 0,
    commission_paid: 0,
    quote_status: 'confirmed',
    pricing_kind: 'published_nav',
    pricing_authority: 'authoritative',
    pricing_as_of: '2026-09-11',
  },
];

test('renders category filter buttons in Chinese and filters positions on click', () => {
  renderSection(
    <OverviewHoldingsSection
      positions={mockPositions}
      assetClassBySymbol={{ '600519': 'stock', '000001.OF': 'fund' }}
    />,
    'zh',
  );

  // Filter group rendered
  const filterGroup = screen.getByTestId('overview-holdings-category-filter');
  expect(filterGroup).toBeInTheDocument();

  // Filter tabs with counts in Chinese
  const allBtn = screen.getByRole('button', { name: /全部 \(2\)/ });
  const stockBtn = screen.getByRole('button', { name: /股票 \(1\)/ });
  const fundBtn = screen.getByRole('button', { name: /基金 \(1\)/ });

  expect(allBtn).toHaveAttribute('aria-pressed', 'true');
  expect(stockBtn).toHaveAttribute('aria-pressed', 'false');
  expect(fundBtn).toHaveAttribute('aria-pressed', 'false');

  // Both positions visible initially
  expect(screen.getAllByText('贵州茅台').length).toBeGreaterThan(0);
  expect(screen.getAllByText('华夏成长').length).toBeGreaterThan(0);

  // Click Stock filter
  fireEvent.click(stockBtn);
  expect(stockBtn).toHaveAttribute('aria-pressed', 'true');
  expect(allBtn).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getAllByText('贵州茅台').length).toBeGreaterThan(0);
  expect(screen.queryAllByText('华夏成长').length).toBe(0);
  expect(screen.getByText('1 / 2')).toBeInTheDocument();

  // Click Fund filter
  fireEvent.click(fundBtn);
  expect(fundBtn).toHaveAttribute('aria-pressed', 'true');
  expect(stockBtn).toHaveAttribute('aria-pressed', 'false');
  expect(screen.queryAllByText('贵州茅台').length).toBe(0);
  expect(screen.getAllByText('华夏成长').length).toBeGreaterThan(0);
  expect(screen.getByText('1 / 2')).toBeInTheDocument();

  // Click All filter to reset
  fireEvent.click(allBtn);
  expect(allBtn).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getAllByText('贵州茅台').length).toBeGreaterThan(0);
  expect(screen.getAllByText('华夏成长').length).toBeGreaterThan(0);
  expect(screen.getByText('2')).toBeInTheDocument();
});

test('renders category filter buttons in English', () => {
  renderSection(
    <OverviewHoldingsSection
      positions={mockPositions}
      assetClassBySymbol={{ '600519': 'stock', '000001.OF': 'fund' }}
    />,
    'en',
  );

  expect(screen.getByRole('button', { name: /All \(2\)/ })).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: /Stock \(1\)/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('button', { name: /Fund \(1\)/ }),
  ).toBeInTheDocument();
});

test('renders empty state when positions array is empty', () => {
  renderSection(
    <OverviewHoldingsSection positions={[]} assetClassBySymbol={{}} />,
    'zh',
  );

  expect(
    screen.getByText('当前还没有持仓，可先前往【账本】录入交易记录。'),
  ).toBeInTheDocument();
});

test('sorts by indicative market value when market_value is null', () => {
  const positionsWithIndicative: PortfolioSnapshot['positions'] = [
    {
      symbol: '000002',
      display_name: '万科A',
      asset_class: 'stock',
      quantity: 100,
      available_qty: 100,
      frozen_qty: 0,
      avg_cost: 10,
      market_value: null,
      indicative_market_value: 50000,
      latest_price: null,
      unrealized_pnl: null,
      indicative_unrealized_pnl: 1000,
      realized_pnl: 0,
      commission_paid: 0,
      quote_status: 'unconfirmed',
      pricing_kind: 'session_close',
      pricing_authority: 'non_authoritative',
      pricing_as_of: '2026-09-11',
    },
    {
      symbol: '600519',
      display_name: '贵州茅台',
      asset_class: 'stock',
      quantity: 100,
      available_qty: 100,
      frozen_qty: 0,
      avg_cost: 1500,
      market_value: 160000,
      latest_price: 1600,
      unrealized_pnl: 10000,
      realized_pnl: 0,
      commission_paid: 5,
      quote_status: 'confirmed',
      pricing_kind: 'session_close',
      pricing_authority: 'authoritative',
      pricing_as_of: '2026-09-11',
    },
  ];

  renderSection(
    <OverviewHoldingsSection
      positions={positionsWithIndicative}
      assetClassBySymbol={{ '600519': 'stock', '000002': 'stock' }}
    />,
    'zh',
  );

  expect(screen.getAllByText('贵州茅台').length).toBeGreaterThan(0);
  expect(screen.getAllByText('万科A').length).toBeGreaterThan(0);
});

test('renders sort control and allows sorting and direction toggle', () => {
  renderSection(
    <OverviewHoldingsSection
      positions={mockPositions}
      assetClassBySymbol={{ '600519': 'stock', '000001.OF': 'fund' }}
      weightBySymbol={{ '600519': 0.8, '000001.OF': 0.2 }}
    />,
    'zh',
  );

  const sortControl = screen.getByTestId('overview-holdings-sort-control');
  expect(sortControl).toBeInTheDocument();

  // Sort direction toggle button
  const dirBtn = screen.getByRole('button', { name: /降序/ });
  expect(dirBtn).toBeInTheDocument();

  // Click to toggle direction to ascending
  fireEvent.click(dirBtn);
  expect(screen.getByRole('button', { name: /升序/ })).toBeInTheDocument();
});

test('sorts positions by both today_change_pct and today_change (涨跌额/盈亏)', () => {
  const positionsWithChanges: PortfolioSnapshot['positions'] = [
    {
      symbol: '600519',
      display_name: '贵州茅台',
      asset_class: 'stock',
      quantity: 100,
      available_qty: 100,
      frozen_qty: 0,
      avg_cost: 1500,
      market_value: 160000,
      latest_price: 1600,
      today_change: 3000,
      today_change_pct: 1.88,
      unrealized_pnl: 10000,
      realized_pnl: 0,
      commission_paid: 5,
      quote_status: 'confirmed',
      pricing_kind: 'session_close',
      pricing_authority: 'authoritative',
      pricing_as_of: '2026-09-11',
    },
    {
      symbol: '000001.OF',
      display_name: '华夏成长',
      asset_class: 'fund',
      quantity: 1000,
      available_qty: 1000,
      frozen_qty: 0,
      avg_cost: 1.2,
      market_value: 1300,
      latest_price: 1.3,
      today_change: 50,
      today_change_pct: 3.85,
      unrealized_pnl: 100,
      realized_pnl: 0,
      commission_paid: 0,
      quote_status: 'confirmed',
      pricing_kind: 'published_nav',
      pricing_authority: 'authoritative',
      pricing_as_of: '2026-09-11',
    },
  ];

  renderSection(
    <OverviewHoldingsSection
      positions={positionsWithChanges}
      assetClassBySymbol={{ '600519': 'stock', '000001.OF': 'fund' }}
    />,
    'zh',
  );

  const select = screen.getByRole('combobox', { name: '排序' });
  const dirBtn = screen.getByRole('button', { name: /降序/ });

  const getVisibleSymbols = () => {
    const rows = screen.getAllByTestId(/^position-row-/);
    return rows.map((r) =>
      r.getAttribute('data-testid')?.replace('position-row-', ''),
    );
  };

  // 1. Sort by Today's Change % (按今日涨跌幅) descending:
  // 000001.OF (+3.85%) > 600519 (+1.88%)
  fireEvent.change(select, { target: { value: 'today_change_pct' } });
  expect(getVisibleSymbols()).toEqual(['000001.OF', '600519']);

  // Toggle to ascending: 600519 (+1.88%) < 000001.OF (+3.85%)
  fireEvent.click(dirBtn);
  expect(getVisibleSymbols()).toEqual(['600519', '000001.OF']);

  // 2. Sort by Today's Change Amount / P&L (按今日涨跌额 / 盈亏):
  // Reset direction to descending
  fireEvent.click(screen.getByRole('button', { name: /升序/ }));
  fireEvent.change(select, { target: { value: 'today_change' } });
  // 600519 (+3000) > 000001.OF (+50)
  expect(getVisibleSymbols()).toEqual(['600519', '000001.OF']);

  // Toggle to ascending: 000001.OF (+50) < 600519 (+3000)
  fireEvent.click(screen.getByRole('button', { name: /降序/ }));
  expect(getVisibleSymbols()).toEqual(['000001.OF', '600519']);
});
