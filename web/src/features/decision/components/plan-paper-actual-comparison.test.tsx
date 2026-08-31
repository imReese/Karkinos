import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import type { ExecutionReconciliationItem } from '../decision-feature-boundary';
import { PlanPaperActualComparison } from './plan-paper-actual-comparison';

function itemWithComparison(
  overrides: Record<string, unknown> = {},
): ExecutionReconciliationItem {
  return {
    item_id: 1,
    order_id: 'OMS-AI-1',
    item_status: 'broker_evidence_available',
    suggested_action: 'review_broker_evidence_match',
    payload_status: 'valid',
    payload: {
      plan_paper_actual_comparison: {
        schema_version: 'karkinos.plan_paper_actual_comparison.v1',
        status: 'pass',
        planned: {
          quantity: '100',
          limit_price: '1688.00',
          strategy_id: 'ai_formula_shadow:candidate-1',
        },
        paper: {
          filled_quantity: '100',
          average_fill_price: '1688.00',
          total_execution_cost: '5.00',
        },
        actual: {
          quantity: '100',
          average_fill_price: '1688.00',
          total_execution_cost: '5.00',
          import_run_ids: ['private-import-run'],
          event_ids: ['private-event-id'],
        },
        blockers: [],
        differences: [],
        evidence_fingerprint: 'a'.repeat(64),
        persisted_evidence_only: true,
        human_review_required: false,
        authorizes_execution: false,
        does_not_mutate_oms: true,
        does_not_mutate_production_ledger: true,
        does_not_change_capital_authority: true,
        ...overrides,
      },
    },
  };
}

test('shows aligned persisted plan paper and actual values without private identities or controls', () => {
  render(<PlanPaperActualComparison item={itemWithComparison()} locale="en" />);

  const panel = screen.getByTestId('plan-paper-actual-comparison');
  expect(panel.textContent).toContain('Plan / paper / actual comparison');
  expect(panel.textContent).toContain('Comparison passed');
  expect(panel.textContent).toContain('Planned');
  expect(panel.textContent).toContain('Paper/shadow');
  expect(panel.textContent).toContain('Actual broker');
  expect(panel.textContent).toContain('1,688.0000');
  expect(panel.textContent).toContain('¥5.00');
  expect(panel.textContent).toContain('a'.repeat(64));
  expect(panel.textContent).toContain('Persisted evidence only');
  expect(panel.textContent).toContain('No execution authority');
  expect(panel.textContent).toContain('No OMS mutation');
  expect(panel.textContent).toContain('No ledger mutation');
  expect(panel.textContent).toContain('No capital authority change');
  expect(panel.textContent).not.toContain('private-import-run');
  expect(panel.textContent).not.toContain('private-event-id');
  expect(panel.querySelector('button')).toBeNull();
});

test('keeps observed paper actual differences in explicit human review state', () => {
  render(
    <PlanPaperActualComparison
      item={itemWithComparison({
        status: 'review_required',
        differences: [
          'paper_actual_fill_price_difference',
          'paper_actual_execution_cost_difference',
        ],
        human_review_required: true,
      })}
      locale="en"
    />,
  );

  const panel = screen.getByTestId('plan-paper-actual-comparison');
  expect(panel.textContent).toContain('Review required');
  expect(panel.textContent).toContain(
    'Actual average price differs from the paper result.',
  );
  expect(panel.textContent).toContain(
    'Actual fees and taxes differ from the paper result.',
  );
  expect(panel.textContent).toContain('Keep the next batch blocked');
  expect(panel.textContent).toContain('Human review required');
  expect(panel.textContent).not.toContain('paper_actual_fill_price_difference');
});

test('explains missing exact broker evidence as a fail-closed blocker in Chinese', () => {
  render(
    <PlanPaperActualComparison
      item={itemWithComparison({
        status: 'blocked',
        actual: {},
        blockers: ['actual_broker_evidence_missing'],
        evidence_fingerprint: 'b'.repeat(64),
        human_review_required: true,
      })}
      locale="zh"
    />,
  );

  const panel = screen.getByTestId('plan-paper-actual-comparison');
  expect(panel.textContent).toContain('对比阻断');
  expect(panel.textContent).toContain('缺少精确的券商实际成交导入证据。');
  expect(panel.textContent).toContain('补充与订单身份精确绑定的券商证据');
  expect(panel.textContent).toContain('无执行权限');
  expect(panel.textContent).not.toContain('actual_broker_evidence_missing');
});

test('fails closed when the persisted reconciliation payload is invalid', () => {
  const item = itemWithComparison();
  item.payload_status = 'invalid';
  item.payload = {};

  render(<PlanPaperActualComparison item={item} locale="en" />);

  const panel = screen.getByTestId('plan-paper-actual-comparison');
  expect(panel.textContent).toContain('Comparison blocked');
  expect(panel.textContent).toContain(
    'The persisted reconciliation payload is invalid and cannot be interpreted.',
  );
  expect(panel.textContent).toContain('Do not infer or accept missing values.');
  expect(panel.textContent).not.toContain('Metric');
  expect(panel.querySelector('button')).toBeNull();
});

test('fails closed when the persisted reconciliation payload is missing', () => {
  const item = itemWithComparison();
  item.payload_status = 'missing';
  item.payload = undefined;

  render(<PlanPaperActualComparison item={item} locale="en" />);

  const panel = screen.getByTestId('plan-paper-actual-comparison');
  expect(panel.textContent).toContain('Comparison blocked');
  expect(panel.textContent).toContain(
    'The persisted reconciliation payload is missing.',
  );
  expect(panel.textContent).toContain('No execution authority');
});

test('fails closed when a valid payload omits or corrupts the comparison status', () => {
  const missingComparison = itemWithComparison();
  missingComparison.payload = {};
  const { rerender } = render(
    <PlanPaperActualComparison item={missingComparison} locale="en" />,
  );

  expect(
    screen.getByTestId('plan-paper-actual-comparison').textContent,
  ).toContain('The persisted plan, paper, and actual comparison is missing.');

  rerender(
    <PlanPaperActualComparison
      item={itemWithComparison({ status: 'unexpected_pass' })}
      locale="en"
    />,
  );
  const panel = screen.getByTestId('plan-paper-actual-comparison');
  expect(panel.textContent).toContain('Comparison blocked');
  expect(panel.textContent).toContain(
    'The persisted comparison status is missing or invalid.',
  );
  expect(panel.textContent).not.toContain('unexpected_pass');
});
