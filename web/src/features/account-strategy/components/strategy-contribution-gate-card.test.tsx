import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  locale?: 'en' | 'zh',
) {
  window.localStorage.clear();
  if (locale) {
    window.localStorage.setItem('karkinos.locale', locale);
  }
  return render(
    <PreferencesProvider>
      <StrategyContributionGateCard report={report} />
    </PreferencesProvider>,
  );
}

test('shows strategy contribution only when linked-fill evidence supports it', async () => {
  const user = userEvent.setup();
  renderCard({
    schema_version: 'karkinos.account_strategy_contribution.v2',
    strategy_id: 'dual_ma',
    contribution_status: 'evidence_bound_from_posted_fills',
    evidence_binding_status: 'bound',
    next_manual_action: 'review_evidence_bound_strategy_contribution',
    blockers: [],
    strategy_health_status: 'healthy',
    strategy_health_reasons: ['posted_fill_and_valuation_evidence_bound'],
    linked_fill_count: 2,
    ledger_posted_fill_count: 2,
    unposted_linked_fill_count: 0,
    unattributed_fill_count: 0,
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
    valuation_snapshot_id: 'valuation-fixture-1',
    valuation_status: 'complete',
    valuation_scope_status: 'complete',
    ledger_cutoff_id: 42,
    contribution_fingerprint: 'contribution-fixture-1',
    evidence_refs: [
      'fill:FILL-1',
      'fill:FILL-2',
      'ledger_entry:41',
      'ledger_entry:42',
      'valuation_snapshot:valuation-fixture-1',
    ],
    persisted_facts_only: true,
    provider_contacted: false,
    database_writes_performed: false,
    authorizes_execution: false,
    limitations: [
      'Only strategy-linked fills posted to the production ledger are eligible for contribution.',
    ],
  });

  expect(screen.getByText('Strategy contribution')).toBeTruthy();
  expect(
    screen.getByText(
      'Contribution is shown only for strategy fills posted to the production ledger and bound to one persisted valuation snapshot. Manual trades and cash flows stay separate.',
    ),
  ).toBeTruthy();
  expect(screen.getByText('Evidence-linked')).toBeTruthy();
  expect(screen.getByText('Strategy health')).toBeTruthy();
  expect(screen.getByText('Healthy')).toBeTruthy();
  expect(screen.getByText('Dual Moving Average')).toBeTruthy();
  expect(screen.queryByText('dual_ma')).toBeNull();
  expect(screen.queryByText('Dual Moving Average · dual_ma')).toBeNull();
  expect(screen.getByText('Gross realized P/L')).toBeTruthy();
  expect(screen.getByText('¥8.00')).toBeTruthy();
  expect(screen.getByText('Gross unrealized P/L')).toBeTruthy();
  expect(screen.getByText('¥128.50')).toBeTruthy();
  expect(screen.getByText('Commission / slippage')).toBeTruthy();
  expect(screen.getByText('¥5.00 / ¥1.50')).toBeTruthy();
  expect(screen.getByText('Tax')).toBeTruthy();
  expect(screen.getByText('¥0.50')).toBeTruthy();
  expect(screen.queryByText('valuation-fixture-1')).toBeNull();
  await user.click(
    screen.getByRole('button', { name: 'View evidence identity' }),
  );
  expect(screen.getByText('valuation-fixture-1')).toBeTruthy();
  expect(screen.getByText('dual_ma')).toBeTruthy();
  expect(screen.getByText('Net contribution')).toBeTruthy();
  expect(screen.getByText('¥129.50')).toBeTruthy();
  expect(screen.getByText('Evidence refs')).toBeTruthy();
  expect(
    screen.getByText(
      'Only strategy-linked fills posted to the production ledger are eligible for contribution.',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText(
      'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.',
    ),
  ).toBeNull();
});

test('localizes the contribution explanation before showing estimates', () => {
  renderCard(
    {
      schema_version: 'karkinos.account_strategy_contribution.v2',
      strategy_id: 'dual_ma',
      contribution_status: 'evidence_bound_from_posted_fills',
      evidence_binding_status: 'bound',
      next_manual_action: 'review_evidence_bound_strategy_contribution',
      blockers: [],
      strategy_health_status: 'healthy',
      strategy_health_reasons: ['posted_fill_and_valuation_evidence_bound'],
      linked_fill_count: 1,
      ledger_posted_fill_count: 1,
      unposted_linked_fill_count: 0,
      unattributed_fill_count: 0,
      gross_realized_pnl: 0,
      gross_unrealized_pnl: 16,
      total_commission: 5,
      total_slippage: 0,
      total_tax: 0,
      net_contribution: 11,
      unattributed_account_pnl: 0,
      manual_unattributed_pnl: 0,
      cash_flow_pnl: 0,
      missing_valuation_symbols: [],
      valuation_snapshot_id: 'valuation-fixture-zh',
      valuation_status: 'complete',
      valuation_scope_status: 'complete',
      ledger_cutoff_id: 7,
      contribution_fingerprint: 'contribution-fixture-zh',
      evidence_refs: [
        'fill:FILL-1',
        'ledger_entry:7',
        'valuation_snapshot:valuation-fixture-zh',
      ],
      persisted_facts_only: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
      limitations: [],
    },
    'zh',
  );

  expect(screen.getByText('策略贡献')).toBeTruthy();
  expect(
    screen.getByText(
      '只有已记入生产账本并绑定同一持久化估值快照的策略成交才会展示贡献；手工交易和现金流会单独列出。',
    ),
  ).toBeTruthy();
  expect(screen.getByText('证据链已连接')).toBeTruthy();
  expect(screen.queryByText(/linked signal/)).toBeNull();
});

test('does not expose contribution amount when evidence chain is unsupported', () => {
  renderCard({
    strategy_id: 'dual_ma',
    contribution_status: 'no_linked_fills',
    evidence_binding_status: 'not_applicable',
    next_manual_action: 'no_action_until_strategy_linked_fill_exists',
    blockers: [],
    strategy_health_status: 'not_applicable',
    strategy_health_reasons: ['no_strategy_linked_fills_yet'],
    linked_fill_count: 0,
    ledger_posted_fill_count: 0,
    unposted_linked_fill_count: 0,
    unattributed_fill_count: 0,
    gross_realized_pnl: null,
    gross_unrealized_pnl: null,
    total_commission: null,
    total_slippage: null,
    total_tax: null,
    net_contribution: null,
    unattributed_account_pnl: null,
    manual_unattributed_pnl: null,
    cash_flow_pnl: null,
    missing_valuation_symbols: [],
    evidence_refs: [],
    limitations: ['No linked fills are available for strategy attribution.'],
  });

  expect(screen.getByText('Strategy contribution')).toBeTruthy();
  expect(screen.getByText('No contribution due yet')).toBeTruthy();
  expect(screen.getByText('Strategy health')).toBeTruthy();
  expect(screen.getAllByText('Not applicable yet')).toHaveLength(2);
  expect(
    screen.getByText(
      'Contribution stays hidden until the listed ledger and valuation evidence is complete.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/¥999/)).toBeNull();
});

test('shows readable instrument labels for missing valuation warnings', () => {
  render(
    <PreferencesProvider>
      <StrategyContributionGateCard
        report={{
          strategy_id: 'dual_ma',
          contribution_status: 'valuation_missing',
          evidence_binding_status: 'blocked',
          next_manual_action: 'sync_confirmed_market_or_nav_evidence',
          blockers: ['strategy_contribution_valuation_not_confirmed:600519'],
          strategy_health_status: 'stale',
          strategy_health_reasons: ['local_valuation_missing'],
          linked_fill_count: 1,
          gross_realized_pnl: 0,
          gross_unrealized_pnl: 0,
          total_commission: 0,
          total_slippage: 0,
          total_tax: 0,
          net_contribution: 0,
          unattributed_account_pnl: null,
          manual_unattributed_pnl: null,
          cash_flow_pnl: null,
          missing_valuation_symbols: ['600519', '000001'],
          evidence_refs: ['fill:FILL-1'],
          limitations: ['Local valuation is missing for linked evidence.'],
        }}
        instruments={[
          {
            symbol: '600519',
            display_name: '贵州茅台',
          },
        ]}
      />
    </PreferencesProvider>,
  );

  expect(
    screen.getByText('Missing local valuation for: 贵州茅台 600519, 000001.'),
  ).toBeTruthy();
  expect(
    screen.queryByText('Missing local valuation for: 600519, 000001.'),
  ).toBeNull();
});
