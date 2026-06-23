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
    strategy_health_status: 'healthy',
    strategy_health_reasons: ['linked_fill_evidence_available'],
    linked_fill_count: 2,
    gross_realized_pnl: 8,
    gross_unrealized_pnl: 128.5,
    total_commission: 5,
    total_slippage: 1.5,
    total_tax: 0.5,
    net_contribution: 129.5,
    unattributed_account_pnl: 4,
    manual_unattributed_pnl: 12,
    cash_flow_pnl: 3,
    missing_valuation_symbols: [],
    evidence_refs: ['fill:FILL-1', 'fill:FILL-2'],
    limitations: [
      'Contribution is estimated only from linked strategy fills and latest local quotes.',
    ],
  });

  expect(screen.getByText('Strategy contribution')).toBeTruthy();
  expect(screen.getByText('Evidence-linked')).toBeTruthy();
  expect(screen.getByText('Strategy health')).toBeTruthy();
  expect(screen.getByText('Healthy')).toBeTruthy();
  expect(screen.getByText('Dual Moving Average · dual_ma')).toBeTruthy();
  expect(screen.getByText('Gross realized P/L')).toBeTruthy();
  expect(screen.getByText('CN¥8.00')).toBeTruthy();
  expect(screen.getByText('Gross unrealized P/L')).toBeTruthy();
  expect(screen.getByText('CN¥128.50')).toBeTruthy();
  expect(screen.getByText('Commission / slippage')).toBeTruthy();
  expect(screen.getByText('CN¥5.00 / CN¥1.50')).toBeTruthy();
  expect(screen.getByText('Tax')).toBeTruthy();
  expect(screen.getAllByText(/0\.50/).length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText('Manual / cash-flow movement')).toBeTruthy();
  expect(screen.getByText('CN¥12.00 / CN¥3.00')).toBeTruthy();
  expect(screen.getByText('Tax / excluded movement')).toBeTruthy();
  expect(screen.getByText('CN¥0.50 / CN¥4.00')).toBeTruthy();
  expect(screen.getByText('Net contribution')).toBeTruthy();
  expect(screen.getByText('CN¥129.50')).toBeTruthy();
  expect(screen.getByText('Evidence refs')).toBeTruthy();
});

test('does not expose contribution amount when evidence chain is unsupported', () => {
  renderCard({
    strategy_id: 'dual_ma',
    contribution_status: 'no_linked_fills',
    strategy_health_status: 'needs_review',
    strategy_health_reasons: ['linked_fill_evidence_missing'],
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
  expect(screen.getByText('Strategy health')).toBeTruthy();
  expect(screen.getByText('Needs review')).toBeTruthy();
  expect(
    screen.getByText(
      'Contribution is hidden until signals, reviews, orders, and fills are linked.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('CN¥999.00')).toBeNull();
});
