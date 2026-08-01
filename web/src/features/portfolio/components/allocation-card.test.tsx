import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { AllocationCard } from './allocation-card';

beforeEach(() => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  document.documentElement.lang = 'zh-CN';
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

test('presents canonical cash and securities as account composition', () => {
  render(
    <PreferencesProvider>
      <AllocationCard
        items={[
          {
            symbol: 'CASH',
            name: '现金',
            weight: 0.296,
            value: 5621.6,
            asset_class: 'cash',
          },
          {
            symbol: '018125',
            name: '永赢先进制造智选混合发起C',
            weight: 0.043,
            value: 823.45,
            asset_class: 'fund',
          },
        ]}
      />
    </PreferencesProvider>,
  );

  const table = screen.getByRole('table', { name: '账户资产构成' });
  expect(screen.getByRole('heading', { name: '账户资产构成' })).toBeTruthy();
  expect(
    within(table).getByRole('columnheader', { name: '资产' }),
  ).toBeTruthy();
  expect(
    within(table).getByRole('columnheader', { name: '估值金额' }),
  ).toBeTruthy();
  expect(
    within(table).getByRole('columnheader', { name: '净值占比' }),
  ).toBeTruthy();

  const cashLabel = within(table).getByText('现金余额');
  expect(cashLabel.getAttribute('data-allocation-kind')).toBe('cash');
  expect(within(table).queryByRole('link', { name: /现金/ })).toBeNull();
  expect(within(table).queryByText('CASH')).toBeNull();
  expect(within(table).getByText('¥5,621.60')).toBeTruthy();
  expect(within(table).getByText('29.6%')).toBeTruthy();

  expect(
    within(table)
      .getByRole('link', {
        name: '永赢先进制造智选混合发起C · 018125',
      })
      .getAttribute('href'),
  ).toBe('/portfolio/018125');
  expect(within(table).getByText('¥823.45')).toBeTruthy();
  expect(within(table).getByText('4.3%')).toBeTruthy();
  expect(screen.queryByText('配置明细')).toBeNull();
  expect(
    within(table).queryByRole('columnheader', { name: '市值' }),
  ).toBeNull();
});
