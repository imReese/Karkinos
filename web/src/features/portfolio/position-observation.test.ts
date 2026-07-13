import { expect, test } from 'vitest';

import type { AllocationItem, Position } from './api';
import { filterAndSortPortfolioPositions } from './position-observation';

const positions: Position[] = [
  {
    symbol: '600001',
    display_name: 'Healthy Winner',
    asset_class: 'stock',
    quantity: 100,
    available_qty: 100,
    frozen_qty: 0,
    avg_cost: 10,
    market_value: 1_200,
    unrealized_pnl: 200,
    realized_pnl: 50,
    commission_paid: 5,
    today_change: 20,
    quote_status: 'live',
  },
  {
    symbol: '018125',
    display_name: 'Stale Fund',
    asset_class: 'fund',
    quantity: 1_000,
    available_qty: 1_000,
    frozen_qty: 0,
    avg_cost: 2,
    market_value: 1_800,
    unrealized_pnl: -200,
    realized_pnl: 80,
    commission_paid: 0,
    today_change: -30,
    quote_status: 'stale',
  },
  {
    symbol: '600002',
    display_name: 'Estimated Review Item',
    asset_class: 'stock',
    quantity: -20,
    available_qty: -20,
    frozen_qty: 0,
    avg_cost: 12,
    market_value: -260,
    unrealized_pnl: -20,
    realized_pnl: 120,
    commission_paid: 5,
    today_change: 5,
    quote_status: 'estimated',
  },
];

const allocation: AllocationItem[] = [
  {
    symbol: '600001',
    name: 'Healthy Winner',
    asset_class: 'stock',
    value: 1_200,
    weight: 0.3,
  },
  {
    symbol: '018125',
    name: 'Stale Fund',
    asset_class: 'fund',
    value: 1_800,
    weight: 0.45,
  },
  {
    symbol: '600002',
    name: 'Estimated Review Item',
    asset_class: 'stock',
    value: -260,
    weight: -0.065,
  },
];

function select(
  overrides: Partial<
    Parameters<typeof filterAndSortPortfolioPositions>[0]
  > = {},
) {
  return filterAndSortPortfolioPositions({
    positions,
    allocation,
    search: '',
    assetClassFilter: 'all',
    pnlFilter: 'all',
    quoteFilter: 'all',
    evidenceFilter: 'all',
    evidenceReviewSymbols: new Set(),
    sortBy: 'market_value',
    ...overrides,
  });
}

test('filters stale and estimated facts without mutating canonical positions', () => {
  const originalOrder = positions.map((position) => position.symbol);
  const filtered = select({ quoteFilter: 'review' });

  expect(filtered.map((position) => position.symbol)).toEqual([
    '018125',
    '600002',
  ]);
  expect(positions.map((position) => position.symbol)).toEqual(originalOrder);
});

test('sorts by canonical weight, today, unrealized, and realized values', () => {
  expect(
    select({ sortBy: 'weight' }).map((position) => position.symbol),
  ).toEqual(['018125', '600001', '600002']);
  expect(
    select({ sortBy: 'today_change' }).map((position) => position.symbol),
  ).toEqual(['600001', '600002', '018125']);
  expect(
    select({ sortBy: 'unrealized_pnl' }).map((position) => position.symbol),
  ).toEqual(['600001', '600002', '018125']);
  expect(
    select({ sortBy: 'realized_pnl' }).map((position) => position.symbol),
  ).toEqual(['600002', '018125', '600001']);
});

test('uses explicit evidence-review symbols and preserves nonzero short positions', () => {
  const review = select({
    evidenceFilter: 'review',
    evidenceReviewSymbols: new Set(['600002']),
  });

  expect(review).toHaveLength(1);
  expect(review[0]?.quantity).toBe(-20);
});
