import type { Page } from '@playwright/test';

export function overviewFixture() {
  const identity = {
    valuation_snapshot_id: 'overview-sanitized-friday',
    valuation_as_of: '2026-09-11T18:00:00+08:00',
    valuation_trade_date: '2026-09-11',
    valuation_policy: 'confirmed-session-close',
    valuation_status: 'complete',
    ledger_cutoff_id: 2,
    ledger_fingerprint: 'sanitized-ledger',
    quote_set_fingerprint: 'sanitized-quotes',
    valuation_blockers: [],
  };
  const positions = [
    {
      symbol: 'fixture-stock',
      name: '示例制造',
      display_name: '示例制造',
      asset_class: 'stock',
      instrument_type: 'stock',
      quantity: 100,
      available_qty: 100,
      frozen_qty: 0,
      avg_cost: 550,
      latest_price: 600,
      market_value: 60000,
      unrealized_pnl: 5000,
      realized_pnl: 0,
      commission_paid: 0,
      today_change: -400,
      quote_status: 'confirmed',
      quote_timestamp: '2026-09-11T15:00:00+08:00',
      pricing_kind: 'session_close',
      pricing_as_of: '2026-09-11',
      pricing_authority: 'authoritative',
      valuation_available: true,
      using_persistent_cache: true,
      valuation_blockers: [],
    },
    {
      symbol: 'fixture-fund',
      name: '示例成长混合',
      display_name: '示例成长混合',
      asset_class: 'fund',
      instrument_type: 'open_end_fund',
      quantity: 1000,
      available_qty: 1000,
      frozen_qty: 0,
      avg_cost: 17.5,
      latest_price: 18,
      market_value: 18000,
      unrealized_pnl: 500,
      realized_pnl: 0,
      commission_paid: 0,
      today_change: -50,
      quote_status: 'confirmed',
      quote_timestamp: '2026-09-11T18:00:00+08:00',
      nav_date: '2026-09-11',
      pricing_kind: 'published_nav',
      pricing_as_of: '2026-09-11',
      pricing_authority: 'authoritative',
      valuation_available: true,
      using_persistent_cache: true,
      valuation_blockers: [],
    },
  ];
  return {
    summary: {
      ...identity,
      total_equity: 100500,
      available_cash: 22500,
      total_deposits: 95000,
      positions_count: 2,
      unrealized_pnl: 5500,
      realized_pnl: 0,
      cumulative_pnl: 5500,
      cumulative_return: null,
      today_pnl: -450,
      cash_ratio: 22500 / 100500,
      latest_session_date: '2026-09-11',
      quote_status: 'confirmed',
    },
    snapshot: {
      ...identity,
      cash: 22500,
      total_equity: 100500,
      total_deposits: 95000,
      positions,
      closed_positions: [],
      allocation_grouped: [],
      allocation: positions.map((position) => ({
        symbol: position.symbol,
        name: position.name,
        asset_class: position.asset_class,
        value: position.market_value,
        weight: position.market_value / 100500,
      })),
    },
    risks: [],
    next_step: 'Continue observation',
    overview: {
      market_session: {
        status: 'non_trading_day',
        calendar_verified: true,
        latest_completed_trade_date: '2026-09-11',
        expected_quote_date: '2026-09-11',
        next_trading_date: '2026-09-14',
        blockers: [],
      },
      valuation_usability: 'usable',
      pricing_as_of: '2026-09-11',
      refresh_health: {
        status: 'degraded',
        latest_attempt: {
          status: 'failed',
          updated_at: '2026-09-12T08:00:00+08:00',
        },
        blockers: ['sanitized-refresh-failure'],
      },
      decision_readiness: 'unknown',
      user_attention: [],
      attention_status: 'available',
    },
  };
}

export const overviewCurveFixture = [
  100200, 100700, 100400, 101050, 100950, 100500,
].map((total, index) => ({
  timestamp: `2026-09-${String(index + 6).padStart(2, '0')}T15:00:00+08:00`,
  total,
  cash: 22500,
  stocks: total - 40500,
  funds: 18000,
  others: 0,
}));

export async function installOverviewFixture(page: Page) {
  await page.route('**/api/portfolio/state', (route) =>
    route.fulfill({ json: overviewFixture() }),
  );
  await page.route('**/api/portfolio/overview', (route) =>
    route.fulfill({ json: overviewFixture().summary }),
  );
  await page.route('**/api/portfolio/equity-curve/series**', (route) =>
    route.fulfill({ json: overviewCurveFixture }),
  );
}
