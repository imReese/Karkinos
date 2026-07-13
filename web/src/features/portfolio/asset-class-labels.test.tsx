import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../app/preferences';
import { AllocationGroupsCard } from './components/allocation-groups-card';
import { WorkspaceToolbar } from './components/workspace-toolbar';

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

function renderWithLocale(ui: ReactElement, locale: 'en' | 'zh') {
  window.localStorage.setItem('karkinos.locale', locale);
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en-US';
  render(<PreferencesProvider>{ui}</PreferencesProvider>);
}

function renderToolbar(locale: 'en' | 'zh') {
  renderWithLocale(
    <WorkspaceToolbar
      mode="account"
      onModeChange={() => undefined}
      search=""
      onSearchChange={() => undefined}
      assetClassFilter="all"
      onAssetClassFilterChange={() => undefined}
      pnlFilter="all"
      onPnlFilterChange={() => undefined}
      assetClasses={['cash', 'fund', 'stock']}
    />,
    locale,
  );
}

test('localizes portfolio asset filter options in english', () => {
  renderToolbar('en');

  expect(screen.getByRole('option', { name: 'Fund' })).toBeTruthy();
  expect(screen.getByRole('option', { name: 'Stock' })).toBeTruthy();
  expect(screen.getByRole('option', { name: 'Cash' })).toBeTruthy();
  expect(screen.queryByRole('option', { name: 'fund' })).toBeNull();
  expect(screen.queryByRole('option', { name: 'stock' })).toBeNull();
  expect(screen.queryByRole('option', { name: 'cash' })).toBeNull();
});

test('localizes portfolio asset filter options and allocation groups in chinese', () => {
  renderToolbar('zh');

  expect(screen.getByRole('option', { name: '基金' })).toBeTruthy();
  expect(screen.getByRole('option', { name: '股票' })).toBeTruthy();
  expect(screen.getByRole('option', { name: '现金' })).toBeTruthy();
  expect(screen.queryByRole('option', { name: 'fund' })).toBeNull();
  expect(screen.queryByRole('option', { name: 'stock' })).toBeNull();
  expect(screen.queryByRole('option', { name: 'cash' })).toBeNull();

  renderWithLocale(
    <AllocationGroupsCard
      groups={[
        {
          asset_class: 'stock',
          name: 'stock',
          weight: 0.7,
          value: 700,
          items: [],
        },
        {
          asset_class: 'fund',
          name: 'fund',
          weight: 0.3,
          value: 300,
          items: [],
        },
      ]}
    />,
    'zh',
  );

  expect(screen.getAllByText('股票').length).toBeGreaterThan(0);
  expect(screen.getAllByText('基金').length).toBeGreaterThan(0);
  expect(screen.queryByText('stock')).toBeNull();
  expect(screen.queryByText('fund')).toBeNull();
});

test('exposes local quote, evidence, and sort controls without mutations', () => {
  const onQuoteFilterChange = vi.fn();
  const onEvidenceFilterChange = vi.fn();
  const onSortByChange = vi.fn();
  renderWithLocale(
    <WorkspaceToolbar
      mode="account"
      onModeChange={() => undefined}
      search=""
      onSearchChange={() => undefined}
      assetClassFilter="all"
      onAssetClassFilterChange={() => undefined}
      pnlFilter="all"
      onPnlFilterChange={() => undefined}
      assetClasses={['fund', 'stock']}
      onQuoteFilterChange={onQuoteFilterChange}
      onEvidenceFilterChange={onEvidenceFilterChange}
      onSortByChange={onSortByChange}
    />,
    'en',
  );

  fireEvent.change(screen.getByRole('combobox', { name: 'Quote state' }), {
    target: { value: 'review' },
  });
  fireEvent.change(screen.getByRole('combobox', { name: 'Reconciliation' }), {
    target: { value: 'review' },
  });
  fireEvent.change(screen.getByRole('combobox', { name: 'Sort by' }), {
    target: { value: 'realized_pnl' },
  });

  expect(onQuoteFilterChange).toHaveBeenCalledWith('review');
  expect(onEvidenceFilterChange).toHaveBeenCalledWith('review');
  expect(onSortByChange).toHaveBeenCalledWith('realized_pnl');
});
