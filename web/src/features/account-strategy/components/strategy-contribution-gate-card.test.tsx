import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { StrategyContributionGateCard } from './strategy-contribution-gate-card';

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

function renderCard(
  report: Parameters<typeof StrategyContributionGateCard>[0]['report'],
) {
  return render(
    <PreferencesProvider>
      <StrategyContributionGateCard report={report} />
    </PreferencesProvider>,
  );
}

test('shows strategy contribution only when linked-fill evidence supports it', () => {
  renderCard({
    strategy_id: 'dual_ma',
    contribution_status: 'estimated_from_linked_fills',
    linked_fill_count: 2,
    gross_realized_pnl: 0,
    gross_unrealized_pnl: 128.5,
    total_commission: 5,
    total_slippage: 1.5,
    total_tax: 0,
    net_contribution: 122,
    unattributed_account_pnl: null,
    manual_unattributed_pnl: null,
    cash_flow_pnl: null,
    missing_valuation_symbols: [],
    evidence_refs: ['fill:FILL-1', 'fill:FILL-2'],
    limitations: [
      'Contribution is estimated only from linked strategy fills and latest local quotes.',
    ],
  });

  expect(screen.getByText('Strategy contribution')).toBeTruthy();
  expect(screen.getByText('Evidence-linked')).toBeTruthy();
  expect(screen.getByText('Dual Moving Average · dual_ma')).toBeTruthy();
  expect(screen.getByText('Net contribution')).toBeTruthy();
  expect(screen.getByText('CN¥122.00')).toBeTruthy();
  expect(screen.getByText('Evidence refs')).toBeTruthy();
});

test('does not expose contribution amount when evidence chain is unsupported', () => {
  renderCard({
    strategy_id: 'dual_ma',
    contribution_status: 'no_linked_fills',
    linked_fill_count: 0,
    gross_realized_pnl: 0,
    gross_unrealized_pnl: 0,
    total_commission: 0,
    total_slippage: 0,
    total_tax: 0,
    net_contribution: 999,
    unattributed_account_pnl: null,
    manual_unattributed_pnl: null,
    cash_flow_pnl: null,
    missing_valuation_symbols: [],
    evidence_refs: [],
    limitations: ['No linked fills are available for strategy attribution.'],
  });

  expect(screen.getByText('Strategy contribution')).toBeTruthy();
  expect(screen.getByText('Evidence required')).toBeTruthy();
  expect(
    screen.getByText(
      'Contribution is hidden until signals, reviews, orders, and fills are linked.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('CN¥999.00')).toBeNull();
});
