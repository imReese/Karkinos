import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { TradingPage } from './trading-page';

const pendingOrder = {
  id: 1,
  order_id: 'ORD-PENDING',
  timestamp: '2026-05-16T10:00:00+08:00',
  symbol: '600519',
  side: 'buy',
  order_type: 'limit',
  quantity: 100,
  price: 1720.25,
  intent_id: 'INT-1',
  risk_decision_id: 'RISK-1',
  execution_mode: 'manual',
  status: 'pending_confirm',
  payload_json: '{"intent_id":"INT-1","risk_decision_id":"RISK-1"}',
  note: null,
  created_at: '2026-05-16T10:00:00+08:00',
  updated_at: '2026-05-16T10:00:00+08:00',
};

const confirmedOrder = {
  ...pendingOrder,
  id: 2,
  order_id: 'ORD-CONFIRMED',
  symbol: '019999',
  side: 'sell',
  status: 'confirmed',
  note: 'confirmed by operator',
  updated_at: '2026-05-16T10:30:00+08:00',
};

const orderFact = {
  order_id: 'ORD-FACT-1',
  timestamp: '2026-05-16T10:45:00+08:00',
  symbol: '600519',
  side: 'buy',
  order_type: 'limit',
  quantity: 100,
  price: 1720.25,
  asset_class: 'stock',
  execution_mode: 'manual',
  status: 'confirmed',
};

const fillFact = {
  fill_id: 'FILL-1',
  order_id: 'ORD-FACT-1',
  timestamp: '2026-05-16T10:46:00+08:00',
  symbol: '600519',
  side: 'buy',
  fill_price: 1720.25,
  fill_quantity: 100,
  commission: 5,
  slippage: 0,
};

const positionRows = [
  {
    symbol: '600519',
    name: '贵州茅台',
    display_name: '贵州茅台',
    asset_class: 'stock',
    quantity: 100,
    available_qty: 100,
    frozen_qty: 0,
    avg_cost: 1720.25,
    latest_price: 1721,
    market_value: 172100,
    unrealized_pnl: 75,
    realized_pnl: 0,
    commission_paid: 5,
  },
  {
    symbol: '019999',
    name: '示例成长混合C',
    display_name: '示例成长混合C',
    asset_class: 'fund',
    quantity: 100,
    available_qty: 100,
    frozen_qty: 0,
    avg_cost: 1.1,
    latest_price: 1.12,
    market_value: 112,
    unrealized_pnl: 2,
    realized_pnl: 0,
    commission_paid: 0,
  },
];

const defaultOperationsToday = {
  schema_version: 'karkinos.operations_today.v1',
  operations_date: '2026-05-16',
  generated_at: '2026-05-16T10:00:00+08:00',
  conclusion_status: 'healthy',
  primary_target: 'decision',
  health: {
    total: 8,
    pass: 6,
    degraded: 0,
    blocked: 0,
    manual_action_required: 0,
    skipped: 2,
  },
  subsystems: [],
  daily_plan: {
    candidate_pool_count: 0,
    manual_ready_count: 0,
    blocked_count: 0,
    order_intent_count: 0,
    conclusion_status: 'no_action',
  },
  paper_shadow: {
    status: 'not_required',
    run_id: null,
    input_fingerprint: null,
    order_intent_count: 0,
    simulated_order_count: 0,
    simulated_fill_count: 0,
    divergence_reviewed_count: 0,
    divergence_status: 'not_required',
    next_manual_review_step: 'none',
    last_run_at: null,
    limitations: [],
    orders: [],
  },
  limitations: [],
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installTradingFetchMock({
  orders = [pendingOrder, confirmedOrder],
  orderFacts = [orderFact],
  fillFacts = [fillFact],
  positions = positionRows,
  operationsToday = defaultOperationsToday,
  rejectFails = false,
  ordersFail = false,
}: {
  orders?: unknown[];
  orderFacts?: unknown[];
  fillFacts?: unknown[];
  positions?: unknown[];
  operationsToday?: unknown;
  rejectFails?: boolean;
  ordersFail?: boolean;
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/trading/kill-switch')) {
        if (init?.method === 'PUT') {
          return jsonResponse({
            kill_switch_enabled: false,
            reason: '',
            updated_at: '2026-05-16T10:00:00+08:00',
          });
        }
        return jsonResponse({
          kill_switch_enabled: false,
          reason: '',
          updated_at: '2026-05-16T10:00:00+08:00',
        });
      }
      if (url.includes('/api/portfolio/positions')) {
        return jsonResponse(positions);
      }
      if (url.includes('/api/operations/today')) {
        return jsonResponse(operationsToday);
      }
      if (
        url.includes(
          '/api/operations/paper-shadow/runs/shadow%3A2026-05-16%3Adiverged/review',
        )
      ) {
        return jsonResponse({
          run_id: 'shadow:2026-05-16:diverged',
          status: 'diverged',
          divergence_status: 'diverged',
          review_status: 'accepted_for_manual_confirmation',
          reviewed_at: '2026-05-16T10:20:00+08:00',
          reviewer: 'web',
          next_manual_review_step: 'review_manual_confirmation',
          does_not_submit_broker_order: true,
          does_not_mutate_production_ledger: true,
        });
      }
      if (url.includes('/api/trading/order-facts')) {
        return jsonResponse(orderFacts);
      }
      if (url.includes('/api/trading/fills')) {
        return jsonResponse(fillFacts);
      }
      if (url.includes('/api/trading/shadow-runs/daily')) {
        return jsonResponse({
          run_id: 'shadow-2026-05-16',
          run_date: '2026-05-16',
          processed_count: 1,
          reused_count: 0,
          skipped_count: 0,
          orders: [orderFact],
          reused_orders: [],
          skipped: [],
        });
      }
      if (url.includes('/api/trading/orders/ORD-PENDING/confirm')) {
        return jsonResponse({ ...pendingOrder, status: 'confirmed' });
      }
      if (url.includes('/api/trading/orders/ORD-PENDING/reject')) {
        return rejectFails
          ? jsonResponse({ detail: 'manual order not found' }, { status: 404 })
          : jsonResponse({ ...pendingOrder, status: 'rejected' });
      }
      if (
        url.includes(
          '/api/broker-gateway/orders/ORD-CONFIRMED/manual-ticket/export',
        )
      ) {
        return jsonResponse({
          schema_version: 'karkinos.broker_gateway.v1',
          gateway_id: 'manual_ticket',
          status: 'export_ready',
          dry_run: true,
          submitted_to_broker: false,
          order_id: 'ORD-CONFIRMED',
          ticket: {
            symbol: '019999',
            side: 'sell',
            asset_class: 'stock',
            quantity: 100,
            order_type: 'limit',
            limit_price: 1720.25,
            copy_text: 'SELL 019999 100 LIMIT 1720.25',
            operator_form: {
              schema_version: 'karkinos.manual_ticket_operator_form.v1',
              account_alias: 'local-review',
              field_labels: {
                account_alias: 'Account alias',
                symbol: 'Symbol',
                side: 'Side',
                quantity: 'Quantity',
                order_type: 'Order type',
                limit_price: 'Limit price',
                copy_text: 'Broker copy text',
              },
              fields: [
                {
                  key: 'account_alias',
                  label: 'Account alias',
                  value: 'local-review',
                },
                { key: 'symbol', label: 'Symbol', value: '019999' },
                { key: 'side', label: 'Side', value: 'sell' },
                { key: 'quantity', label: 'Quantity', value: 100 },
                { key: 'order_type', label: 'Order type', value: 'limit' },
                { key: 'limit_price', label: 'Limit price', value: 1720.25 },
              ],
              fee_tax_assumptions: {
                source: 'oms_order_payload_or_fee_rule',
                estimated_total_fee: 5.2,
                estimated_net_cash_impact: -168805.1,
                fee_components: {
                  commission: '5.00',
                  stamp_tax: '0.00',
                  transfer_fee: '0.20',
                },
                notes: [
                  'Broker client final fee and tax preview remains authoritative.',
                ],
              },
              trading_session_constraints: {
                market: 'China exchange session',
                timezone: 'Asia/Shanghai',
                allowed_session: 'regular_exchange_session_only',
                notes: [
                  'Operator must enter this ticket only while the broker client accepts regular-session orders.',
                ],
              },
              safety: {
                submitted_to_broker: false,
                broker_submission_enabled: false,
                requires_human_broker_entry: true,
              },
              cash_impact_preview: {
                source: 'oms_order_payload_or_order_intent',
                estimated_gross_amount: 168800,
                estimated_total_fee: 5.2,
                estimated_net_cash_impact: -168805.1,
                available_cash_before: 200000,
                available_cash_after: 31194.9,
                cash_status: 'sufficient',
                cash_shortfall: 0,
              },
              position_cost_preview: {
                source: 'daily_trading_plan_position_effect',
                current_quantity: 100,
                current_avg_cost: 1600,
                current_market_value: 168800,
                estimated_quantity_after: 200,
                estimated_avg_cost_after: 1644,
                cost_basis_method: 'weighted_average_preview',
              },
            },
          },
          export: {
            schema_version: 'karkinos.manual_ticket_export.v1',
            format: 'json',
            mime_type: 'application/json',
            file_name: 'karkinos-manual-ticket-ORD-CONFIRMED.json',
            copy_text: 'SELL 019999 100 LIMIT 1720.25',
            content: {
              operator_form: {
                account_alias: 'local-review',
                field_labels: {
                  copy_text: 'Broker copy text',
                },
              },
            },
            content_json:
              '{"operator_form":{"account_alias":"local-review"},"submitted_to_broker":false,"requires_human_broker_entry":true}',
          },
          limitations: [
            'This prepares a copyable manual-ticket export only.',
            'It does not submit to a broker, record an event, or change OMS status.',
          ],
        });
      }
      if (
        url.includes(
          '/api/broker-gateway/orders/ORD-CONFIRMED/manual-execution/preview',
        )
      ) {
        return jsonResponse({
          schema_version: 'karkinos.broker_gateway.v1',
          gateway_id: 'manual_ticket',
          status: 'manual_execution_preview_ready',
          dry_run: true,
          submitted_to_broker: false,
          does_not_mutate_production_ledger: true,
          order_id: 'ORD-CONFIRMED',
          actor: 'web',
          preview_fingerprint:
            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          fingerprint_scope:
            'order_id, execution_preview, ledger_entry_draft, position_cost_preview, controlled_bridge_policy',
          execution_preview: {
            source: 'manual_ticket_operator_entry',
            symbol: '019999',
            side: 'sell',
            asset_class: 'stock',
            quantity: '100',
            fill_price: '1720.25',
            gross_amount: '172025.00',
            fee: '5.00',
            tax: '0.00',
            transfer_fee: '0.20',
            total_cost: '5.20',
            net_cash_impact: '172019.80',
            currency: 'CNY',
          },
          ledger_entry_draft: {
            schema_version: 'karkinos.manual_execution_ledger_draft.v1',
            entry_type: 'trade',
            symbol: '019999',
            side: 'sell',
            asset_class: 'stock',
            quantity: '100',
            price: '1720.25',
            gross_amount: '172025.00',
            fee: '5.00',
            tax: '0.00',
            transfer_fee: '0.20',
            amount: '172019.80',
            source_order_id: 'ORD-CONFIRMED',
            source: 'manual_ticket_execution_preview',
            requires_operator_save: true,
            does_not_mutate_production_ledger: true,
          },
          position_cost_preview: {
            source: 'daily_trading_plan_position_effect',
            current_quantity: 100,
            current_avg_cost: 1600,
            estimated_quantity_after: 200,
            estimated_avg_cost_after: 1644,
            cost_basis_method: 'weighted_average_preview',
          },
          validation: {
            manual_confirmation_status: 'pass',
            gateway_evidence_status: 'pass',
            broker_submission_enabled: false,
            requires_human_broker_entry: true,
            required_gate_summary: {
              schema_version: 'karkinos.controlled_bridge_gate_summary.v1',
              status: 'pass',
              required_gates: [
                'account_truth',
                'research_evidence',
                'risk',
                'paper_shadow',
                'manual_confirmation',
                'kill_switch_clear',
                'connector_health',
                'execution_reconciliation',
              ],
              gates: {
                account_truth: {
                  status: 'pass',
                  evidence_ref: 'account-truth:1',
                  source: 'oms_gateway_evidence',
                },
                research_evidence: {
                  status: 'pass',
                  evidence_ref: 'research:1',
                  source: 'oms_gateway_evidence',
                },
                risk: {
                  status: 'pass',
                  evidence_ref: 'risk:risk-001',
                  source: 'oms_gateway_evidence',
                },
                paper_shadow: {
                  status: 'pass',
                  evidence_ref: 'paper_shadow:run-001',
                  source: 'oms_gateway_evidence',
                },
                manual_confirmation: {
                  status: 'pass',
                  evidence_ref: 'oms_order:ORD-CONFIRMED:manual_ticket_created',
                  source: 'oms_status',
                },
                kill_switch_clear: {
                  status: 'pass',
                  evidence_ref: 'trading_controls:kill_switch_clear',
                  source: 'trading_controls_snapshot',
                },
                connector_health: {
                  status: 'not_applicable_manual_ticket',
                  evidence_ref: 'manual_ticket:local_operator_entry',
                  source: 'manual_ticket_gateway',
                },
                execution_reconciliation: {
                  status: 'pending_after_manual_execution',
                  evidence_ref:
                    'execution_reconciliation:pending:ORD-CONFIRMED',
                  source: 'execution_reconciliation_runbook',
                },
              },
              broker_submission_enabled: false,
              submitted_to_broker: false,
              does_not_authorize_execution: true,
            },
          },
          safety: {
            broker_submission_enabled: false,
            submitted_to_broker: false,
            requires_human_broker_entry: true,
            requires_operator_save: true,
            does_not_mutate_oms: true,
            does_not_mutate_production_ledger: true,
          },
          limitations: [
            'This previews a manual execution record only.',
            'It does not submit to a broker, create gateway events, change OMS status, or write ledger entries.',
          ],
        });
      }
      if (
        url.includes(
          '/api/broker-gateway/orders/ORD-CONFIRMED/manual-execution',
        )
      ) {
        return jsonResponse({
          schema_version: 'karkinos.broker_gateway.v1',
          gateway_id: 'manual_ticket',
          status: 'manual_execution_recorded',
          dry_run: true,
          submitted_to_broker: false,
          does_not_mutate_oms: true,
          does_not_mutate_production_ledger: true,
          requires_operator_ledger_save: true,
          order_id: 'ORD-CONFIRMED',
          actor: 'web',
          event_id: 42,
          preview_fingerprint:
            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          fingerprint_scope:
            'order_id, execution_preview, ledger_entry_draft, position_cost_preview, controlled_bridge_policy',
          operator_note: null,
          execution_preview: {
            source: 'manual_ticket_operator_entry',
            symbol: '019999',
            side: 'sell',
            asset_class: 'stock',
            quantity: '100',
            fill_price: '1720.25',
            gross_amount: '172025.00',
            fee: '5.00',
            tax: '0.00',
            transfer_fee: '0.20',
            total_cost: '5.20',
            net_cash_impact: '172019.80',
            currency: 'CNY',
          },
          ledger_entry_draft: {
            schema_version: 'karkinos.manual_execution_ledger_draft.v1',
            entry_type: 'trade',
            symbol: '019999',
            side: 'sell',
            asset_class: 'stock',
            quantity: '100',
            price: '1720.25',
            gross_amount: '172025.00',
            fee: '5.00',
            tax: '0.00',
            transfer_fee: '0.20',
            amount: '172019.80',
            source_order_id: 'ORD-CONFIRMED',
            source: 'manual_ticket_execution_preview',
            requires_operator_save: true,
            does_not_mutate_production_ledger: true,
          },
          position_cost_preview: {
            source: 'daily_trading_plan_position_effect',
            current_quantity: 100,
            current_avg_cost: 1600,
            estimated_quantity_after: 200,
            estimated_avg_cost_after: 1644,
            cost_basis_method: 'weighted_average_preview',
          },
          validation: {
            manual_confirmation_status: 'pass',
            gateway_evidence_status: 'pass',
            broker_submission_enabled: false,
            requires_human_broker_entry: true,
            required_gate_summary: {
              schema_version: 'karkinos.controlled_bridge_gate_summary.v1',
              status: 'pass',
              required_gates: [
                'account_truth',
                'research_evidence',
                'risk',
                'paper_shadow',
                'manual_confirmation',
                'kill_switch_clear',
                'connector_health',
                'execution_reconciliation',
              ],
              gates: {
                risk: {
                  status: 'pass',
                  evidence_ref: 'risk:risk-001',
                  source: 'oms_gateway_evidence',
                },
                paper_shadow: {
                  status: 'pass',
                  evidence_ref: 'paper_shadow:run-001',
                  source: 'oms_gateway_evidence',
                },
                execution_reconciliation: {
                  status: 'pending_after_manual_execution',
                  evidence_ref:
                    'execution_reconciliation:pending:ORD-CONFIRMED',
                  source: 'execution_reconciliation_runbook',
                },
              },
              broker_submission_enabled: false,
              submitted_to_broker: false,
              does_not_authorize_execution: true,
            },
          },
          limitations: [
            'This records manual execution evidence for audit only.',
            'It does not submit to a broker, create fills, change OMS status, or write ledger entries.',
          ],
        });
      }
      if (url.includes('/api/trading/orders')) {
        if (ordersFail) {
          return jsonResponse(
            { detail: 'orders unavailable' },
            { status: 503 },
          );
        }
        if (url.includes('status=pending_confirm')) {
          return jsonResponse(
            orders.filter(
              (order) =>
                typeof order === 'object' &&
                order !== null &&
                'status' in order &&
                order.status === 'pending_confirm',
            ),
          );
        }
        return jsonResponse(orders);
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderTradingPage(
  options?: Parameters<typeof installTradingFetchMock>[0] & {
    locale?: 'en' | 'zh';
  },
) {
  window.localStorage.clear();
  if (options?.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const { locale: _locale, ...fetchOptions } = options ?? {};
  const fetchMock = installTradingFetchMock(fetchOptions);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <TradingPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the trading approvals workspace', async () => {
  renderTradingPage();

  expect(await screen.findByText('Trading approvals')).toBeTruthy();
  expect(await screen.findByText('Operating mode')).toBeTruthy();
  expect(await screen.findByText('Manual confirmation default')).toBeTruthy();
  expect(await screen.findByText('Broker bridge disabled')).toBeTruthy();
  expect(await screen.findByText('Global kill switch')).toBeTruthy();
  expect(await screen.findByText('Execution audit')).toBeTruthy();
  expect(
    await screen.findByText('Order facts, fills, and simulation review'),
  ).toBeTruthy();
  expect(await screen.findByText('Order facts')).toBeTruthy();
  expect(await screen.findByText('Fill facts')).toBeTruthy();
  expect(await screen.findByText('Order queue')).toBeTruthy();
  expect(await screen.findByText('贵州茅台 600519')).toBeTruthy();
  expect(await screen.findByText('示例成长混合C 019999')).toBeTruthy();
  expect(
    screen.queryByText('Order facts, fills, and shadow review'),
  ).toBeNull();
  expect(screen.queryByText(/real-time/i)).toBeNull();
});

test('shows trading operating mode safety labels in Chinese', async () => {
  renderTradingPage({ locale: 'zh' });

  expect(await screen.findByText('运行模式')).toBeTruthy();
  expect(await screen.findByText('默认人工确认')).toBeTruthy();
  expect(await screen.findByText('券商桥接未启用')).toBeTruthy();
});

test('localizes generated manual-order notes without exposing action ids', async () => {
  renderTradingPage({
    orders: [
      {
        ...pendingOrder,
        note: 'Prepared from signal action 42.',
      },
      {
        ...confirmedOrder,
        note: 'Prepared from signal action 42.',
      },
    ],
  });

  expect(
    await screen.findAllByText('Prepared from Decision action queue.'),
  ).toHaveLength(2);
  expect(screen.queryByText('Prepared from signal action 42.')).toBeNull();
});

test('hides dotted backend operational note codes in trading rows', async () => {
  renderTradingPage({
    orders: [
      {
        ...pendingOrder,
        note: 'backend.order.review',
      },
    ],
  });

  expect(await screen.findByText('Review note')).toBeTruthy();
  expect(screen.queryByText('backend.order.review')).toBeNull();
});

test('uses a public audit-note placeholder instead of raw order ids', async () => {
  renderTradingPage({
    orders: [
      {
        ...confirmedOrder,
        note: null,
      },
    ],
  });

  expect(await screen.findByText('No public note recorded.')).toBeTruthy();
  expect(screen.queryByText('ORD-CONFIRMED')).toBeNull();
});

test('runs daily simulation review from the execution audit panel', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage();

  await screen.findByText('Execution audit');
  await user.click(
    screen.getByRole('button', { name: 'Run daily simulation review' }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/shadow-runs/daily',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  expect(
    await screen.findByText(/Simulation review prepared 1 orders/),
  ).toBeTruthy();
});

test('surfaces latest paper shadow run evidence in execution audit', async () => {
  renderTradingPage({
    operationsToday: {
      ...defaultOperationsToday,
      conclusion_status: 'manual_action_required',
      primary_target: 'paper-shadow',
      health: {
        total: 8,
        pass: 5,
        degraded: 0,
        blocked: 1,
        manual_action_required: 1,
        skipped: 1,
      },
      paper_shadow: {
        status: 'diverged',
        run_id: 'shadow:2026-05-16:diverged',
        input_fingerprint: 'diverged',
        evidence_refs: [
          'paper_shadow_order:SHADOW-1',
          'paper_shadow_fill:FILL-1',
          'oms_transition:SHADOW-1:2:submitted',
          'oms_transition:SHADOW-1:3:accepted',
          'oms_transition:SHADOW-1:4:partially_filled',
        ],
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 0,
        divergence_reviewed_count: 1,
        divergence_status: 'diverged',
        review_status: null,
        next_manual_review_step: 'resolve_shadow_divergence',
        last_run_at: '2026-05-16T10:10:00+08:00',
        review_queue: [
          {
            review_id: 'shadow:2026-05-16:diverged:SHADOW-1',
            order_id: 'SHADOW-1',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
            severity: 'warning',
            required_action: 'resolve_shadow_divergence',
            reason:
              'Simulated paper order partially filled; review before approval.',
            oms_status_path: [
              'staged',
              'submitted',
              'accepted',
              'partially_filled',
            ],
            oms_transition_refs: [
              'oms_transition:SHADOW-1:2:submitted',
              'oms_transition:SHADOW-1:3:accepted',
              'oms_transition:SHADOW-1:4:partially_filled',
            ],
            does_not_submit_broker_order: true,
            does_not_mutate_production_ledger: true,
          },
        ],
        divergence_summary: {
          execution_comparison: {
            diverged_order_refs: ['paper_shadow_order:SHADOW-1'],
            simulated_status_counts: { partially_filled: 1 },
          },
          cost_summary: {
            simulated_slippage_cost: '4.50',
            simulated_total_execution_cost: '16.85',
          },
          does_not_submit_broker_order: true,
          does_not_mutate_production_ledger: true,
        },
        limitations: [],
        orders: [
          {
            order_id: 'SHADOW-1',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
          },
        ],
      },
      limitations: [],
    },
  });

  expect(await screen.findByText('Latest paper/shadow run')).toBeTruthy();
  expect(screen.getByText('Run: shadow:2026-05-16:diverged')).toBeTruthy();
  expect(screen.getByText('Status: Diverged')).toBeTruthy();
  expect(screen.getByText('Order intents: 1')).toBeTruthy();
  expect(screen.getByText('Sim orders: 1')).toBeTruthy();
  expect(screen.getByText('Sim fills: 0')).toBeTruthy();
  expect(
    screen.getByText('Next: Resolve paper/shadow divergence before approval'),
  ).toBeTruthy();
  expect(
    screen.getByText('Diverged orders: Simulation review order · SHADOW-1'),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'Evidence refs: Simulation review order · SHADOW-1; Simulation review fill · FILL-1; OMS transition · SHADOW-1 #4 Partially Filled',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'Review queue: 600519 · Resolve paper/shadow divergence before approval',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'Reason: Simulated paper order partially filled; review before approval.',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'OMS path: Staged → Submitted → Accepted → Partially Filled',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'Latest transition: OMS transition · SHADOW-1 #4 Partially Filled',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'Review safety: No broker submission · No production ledger mutation',
    ),
  ).toBeTruthy();
  expect(screen.getByText('Sim slippage: ¥4.50')).toBeTruthy();
  expect(screen.getByText('No broker submission')).toBeTruthy();
  expect(screen.getByText('No production ledger mutation')).toBeTruthy();
  expect(document.body.textContent).not.toContain('resolve_shadow_divergence');
  expect(document.body.textContent).not.toContain('partially_filled');
  expect(document.body.textContent).not.toContain('oms_transition:');
  expect(document.body.textContent).not.toContain('#2 Submitted');
  expect(document.body.textContent).not.toContain('Submit broker order');
});

test('records accepted simulation review for the latest diverged run', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage({
    operationsToday: {
      ...defaultOperationsToday,
      conclusion_status: 'manual_action_required',
      primary_target: 'paper-shadow',
      health: {
        total: 8,
        pass: 5,
        degraded: 0,
        blocked: 1,
        manual_action_required: 1,
        skipped: 1,
      },
      paper_shadow: {
        status: 'diverged',
        run_id: 'shadow:2026-05-16:diverged',
        input_fingerprint: 'diverged',
        order_intent_count: 1,
        simulated_order_count: 1,
        simulated_fill_count: 0,
        divergence_reviewed_count: 1,
        divergence_status: 'diverged',
        review_status: null,
        next_manual_review_step: 'resolve_shadow_divergence',
        last_run_at: '2026-05-16T10:10:00+08:00',
        limitations: [],
        orders: [
          {
            order_id: 'SHADOW-1',
            symbol: '600519',
            status: 'partially_filled',
            divergence_status: 'diverged',
          },
        ],
      },
      limitations: [],
    },
  });

  expect(
    await screen.findByText('Simulation review needs attention'),
  ).toBeTruthy();
  await user.click(
    screen.getByRole('button', { name: 'Record simulation review' }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/operations/paper-shadow/runs/shadow%3A2026-05-16%3Adiverged/review',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  expect(
    await screen.findByText(
      'Simulation review accepted; continue with manual confirmation.',
    ),
  ).toBeTruthy();
  expect(screen.getByText('Reviewed by: web')).toBeTruthy();
  expect(screen.getByText('Reviewed at: 05/16, 10:20')).toBeTruthy();
  expect(
    screen.getByText(
      'Review safety: No broker submission · No production ledger mutation',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Record simulation review' }),
  ).toBeNull();
  expect(document.body.textContent).not.toContain(
    'accepted_for_manual_confirmation',
  );
  expect(document.body.textContent).not.toContain('resolve_shadow_divergence');
});

test('uses consistent Chinese simulation-review wording in execution audit', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage({ locale: 'zh' });

  expect(await screen.findByText('执行审计')).toBeTruthy();
  expect(await screen.findByText('订单事实、成交事实与模拟复核')).toBeTruthy();
  expect(
    await screen.findByText(
      '查看归一化订单/成交证据，并手动触发模拟复核；不会提交券商订单。',
    ),
  ).toBeTruthy();

  await user.click(screen.getByRole('button', { name: '运行当日模拟复核' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/shadow-runs/daily',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  expect(await screen.findByText(/模拟复核准备 1 笔订单/)).toBeTruthy();
  expect(document.body.textContent).not.toContain('shadow');
  expect(document.body.textContent).not.toContain('模拟复盘');
});

test('uses execution fact display names when the instrument is not in current holdings', async () => {
  renderTradingPage({
    locale: 'zh',
    positions: [],
    orderFacts: [
      {
        ...orderFact,
        order_id: 'ORD-FACT-NAME',
        symbol: '000001',
        display_name: '平安银行',
        status: 'confirmed',
      },
    ],
    fillFacts: [
      {
        ...fillFact,
        fill_id: 'FILL-NAME',
        symbol: '000001',
        display_name: '平安银行',
      },
    ],
  });

  expect(await screen.findByText('买入 平安银行 000001')).toBeTruthy();
  expect(
    await screen.findByText(
      /金额\s+(?:CN)?¥172,025\.00 · 份额\/数量 100 · 价格\s+(?:CN)?¥1,720\.25 · 状态 已确认/u,
    ),
  ).toBeTruthy();
  expect(await screen.findByText('平安银行 000001 · 买入')).toBeTruthy();
  expect(screen.queryByText('000001 · confirmed')).toBeNull();
  expect(screen.queryByText('000001 · buy')).toBeNull();
});

test('shows order facts with shared ledger action and detail formatting', async () => {
  renderTradingPage({
    orderFacts: [
      {
        ...orderFact,
        status: 'confirmed',
      },
    ],
  });

  expect(await screen.findByText('Buy 贵州茅台 600519')).toBeTruthy();
  expect(
    await screen.findByText(
      /Amount ¥172,025\.00 · Quantity 100 · Price ¥1,720\.25 · Status Confirmed/,
    ),
  ).toBeTruthy();
  expect(screen.queryByText('贵州茅台 600519 · Confirmed')).toBeNull();
  expect(screen.queryByText('Buy 100 @ ¥1,720.25')).toBeNull();
});

test('does not default unknown execution fact sides to buy', async () => {
  renderTradingPage({
    locale: 'zh',
    orderFacts: [
      {
        ...orderFact,
        order_id: 'ORD-FACT-UNKNOWN-SIDE',
        side: 'broker_special_side',
        status: 'confirmed',
      },
    ],
    fillFacts: [
      {
        ...fillFact,
        fill_id: 'FILL-UNKNOWN-SIDE',
        side: 'broker_special_side',
      },
    ],
  });

  expect(await screen.findByText('待确认状态 贵州茅台 600519')).toBeTruthy();
  expect(await screen.findByText('贵州茅台 600519 · 待确认状态')).toBeTruthy();
  expect(screen.queryByText('买入 贵州茅台 600519')).toBeNull();
  expect(screen.queryByText('贵州茅台 600519 · 买入')).toBeNull();
  expect(screen.queryByText('broker_special_side')).toBeNull();
});

test('shows structured fill cash impact and fee breakdown in execution audit', async () => {
  renderTradingPage({
    fillFacts: [
      {
        ...fillFact,
        asset_class: 'stock',
        metadata_json: JSON.stringify({
          gross_amount: 172025,
          net_cash_impact: -172030.2,
          fee_breakdown: {
            commission: '5.00',
            stamp_tax: '0.00',
            transfer_fee: '0.20',
            other_fees: '0.00',
            total_fee: '5.20',
          },
          fee_rule_id: 'manual_configured_commission',
          fee_rule_version: 'broker_fee_schedule',
        }),
      },
    ],
  });

  expect(await screen.findByText(/Gross amount ¥172,025\.00/)).toBeTruthy();
  expect(await screen.findByText(/Net cash impact -¥172,030\.20/)).toBeTruthy();
  expect(await screen.findByText(/Commission ¥5\.00/)).toBeTruthy();
  expect(await screen.findByText(/Stamp tax ¥0\.00/)).toBeTruthy();
  expect(await screen.findByText(/Transfer fee ¥0\.20/)).toBeTruthy();
  expect(screen.queryByText(/manual_configured_commission/)).toBeNull();
  expect(screen.queryByText(/fee_breakdown/)).toBeNull();
});

test('confirms a pending manual order and refreshes the queue', async () => {
  const { fetchMock } = renderTradingPage();

  await screen.findByText('贵州茅台 600519');
  fireEvent.click(
    screen.getByRole('button', { name: 'Confirm: 贵州茅台 600519' }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/orders/ORD-PENDING/confirm',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).includes('/api/trading/orders?status=pending_confirm'),
      ).length,
    ).toBeGreaterThan(1);
  });
});

test('exports confirmed manual ticket without broker submission controls', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage();

  fireEvent.change(await screen.findByLabelText('Status'), {
    target: { value: 'confirmed' },
  });
  expect(
    screen.queryByRole('button', { name: 'Export ticket: 贵州茅台 600519' }),
  ).toBeNull();

  await user.click(
    await screen.findByRole('button', {
      name: 'Export ticket: 示例成长混合C 019999',
    }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/broker-gateway/orders/ORD-CONFIRMED/manual-ticket/export',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ actor: 'web' }),
      }),
    );
  });
  expect(await screen.findByText('Manual ticket export')).toBeTruthy();
  expect(screen.getByText('SELL 019999 100 LIMIT 1720.25')).toBeTruthy();
  expect(screen.getByText('Account alias')).toBeTruthy();
  expect(screen.getByText('local-review')).toBeTruthy();
  expect(screen.getByText('Estimated total fee')).toBeTruthy();
  expect(screen.getByText('5.2')).toBeTruthy();
  expect(screen.getByText('Net cash impact')).toBeTruthy();
  expect(screen.getByText('-168805.1')).toBeTruthy();
  expect(screen.getByText('Position after')).toBeTruthy();
  expect(screen.getByText('200')).toBeTruthy();
  expect(screen.getByText('Cost basis method')).toBeTruthy();
  expect(screen.getByText('weighted_average_preview')).toBeTruthy();
  expect(screen.getByText('Trading session')).toBeTruthy();
  expect(screen.getByText('regular_exchange_session_only')).toBeTruthy();
  expect(screen.getByText('Export file')).toBeTruthy();
  expect(
    screen.getByText('karkinos-manual-ticket-ORD-CONFIRMED.json'),
  ).toBeTruthy();
  expect(screen.getByText('MIME type')).toBeTruthy();
  expect(screen.getByText('application/json')).toBeTruthy();
  expect(screen.getByText('Export schema')).toBeTruthy();
  expect(screen.getByText('karkinos.manual_ticket_export.v1')).toBeTruthy();
  expect(screen.getByText('Export limitations')).toBeTruthy();
  expect(
    screen.getByText('This prepares a copyable manual-ticket export only.'),
  ).toBeTruthy();
  expect(screen.getByText('Broker copy text')).toBeTruthy();
  expect(screen.getByText('submitted_to_broker=false')).toBeTruthy();
  expect(screen.getByText(/requires_human_broker_entry/)).toBeTruthy();
  expect(screen.queryByText(/Submit to broker/i)).toBeNull();
});

test('previews manual execution draft without ledger or broker submission controls', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage();

  fireEvent.change(await screen.findByLabelText('Status'), {
    target: { value: 'confirmed' },
  });
  await user.click(
    await screen.findByRole('button', {
      name: 'Export ticket: 示例成长混合C 019999',
    }),
  );
  await user.click(
    await screen.findByRole('button', {
      name: 'Preview manual execution',
    }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/broker-gateway/orders/ORD-CONFIRMED/manual-execution/preview',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          actor: 'web',
          fill_price: '1720.25',
          quantity: '100',
          fee: '5.00',
          tax: '0.00',
          transfer_fee: '0.20',
        }),
      }),
    );
  });
  expect(await screen.findByText('Manual execution preview')).toBeTruthy();
  expect(screen.getByText('Gross amount')).toBeTruthy();
  expect(screen.getByText('172025.00')).toBeTruthy();
  expect(screen.getAllByText('Net cash impact').length).toBeGreaterThan(1);
  expect(screen.getAllByText('172019.80').length).toBeGreaterThan(1);
  expect(screen.getByText('Ledger draft')).toBeTruthy();
  expect(screen.getByText('Controlled bridge gate summary')).toBeTruthy();
  expect(screen.getByText('account truth')).toBeTruthy();
  expect(screen.getByText('research evidence')).toBeTruthy();
  expect(screen.getByText('paper shadow')).toBeTruthy();
  expect(screen.getByText('manual confirmation')).toBeTruthy();
  expect(screen.getByText('kill switch clear')).toBeTruthy();
  expect(screen.getByText('connector health')).toBeTruthy();
  expect(screen.getByText('execution reconciliation')).toBeTruthy();
  expect(screen.getByText('account-truth:1')).toBeTruthy();
  expect(screen.getByText('risk:risk-001')).toBeTruthy();
  expect(screen.getByText('paper_shadow:run-001')).toBeTruthy();
  expect(screen.getByText('does_not_authorize_execution=true')).toBeTruthy();
  expect(screen.getByText('Preview fingerprint')).toBeTruthy();
  expect(
    screen.getByText(
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    ),
  ).toBeTruthy();
  expect(screen.getByText('requires_operator_save=true')).toBeTruthy();
  expect(
    screen.getAllByText('does_not_mutate_production_ledger=true').length,
  ).toBeGreaterThan(0);
  expect(screen.queryByText(/Save ledger/i)).toBeNull();
  expect(screen.queryByText(/Submit to broker/i)).toBeNull();
  expect(screen.queryByText(/Apply fill/i)).toBeNull();
});

test('records manual execution evidence without saving ledger or submitting broker orders', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage();

  fireEvent.change(await screen.findByLabelText('Status'), {
    target: { value: 'confirmed' },
  });
  await user.click(
    await screen.findByRole('button', {
      name: 'Export ticket: 示例成长混合C 019999',
    }),
  );
  await user.click(
    await screen.findByRole('button', {
      name: 'Preview manual execution',
    }),
  );
  await user.click(
    await screen.findByRole('button', {
      name: 'Record manual execution evidence',
    }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/broker-gateway/orders/ORD-CONFIRMED/manual-execution',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          actor: 'web',
          fill_price: '1720.25',
          quantity: '100',
          fee: '5.00',
          tax: '0.00',
          transfer_fee: '0.20',
          preview_fingerprint:
            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        }),
      }),
    );
  });
  expect(
    await screen.findByText('Manual execution evidence recorded'),
  ).toBeTruthy();
  expect(screen.getByText('Gateway event')).toBeTruthy();
  expect(screen.getByText('42')).toBeTruthy();
  expect(screen.getByText('Controlled bridge gate summary')).toBeTruthy();
  expect(
    screen.getByText('execution_reconciliation:pending:ORD-CONFIRMED'),
  ).toBeTruthy();
  expect(
    screen.getAllByText('submitted_to_broker=false').length,
  ).toBeGreaterThan(1);
  expect(screen.getByText('does_not_mutate_oms=true')).toBeTruthy();
  expect(screen.getByText('requires_operator_ledger_save=true')).toBeTruthy();
  expect(
    screen.getAllByText('does_not_mutate_production_ledger=true').length,
  ).toBeGreaterThan(0);
  expect(screen.queryByText(/Save ledger/i)).toBeNull();
  expect(screen.queryByText(/Submit to broker/i)).toBeNull();
  expect(screen.queryByText(/Apply fill/i)).toBeNull();
});

test('shows reject errors without changing local order state', async () => {
  const user = userEvent.setup();
  renderTradingPage({ rejectFails: true });

  await screen.findByText('贵州茅台 600519');
  await user.type(
    screen.getByLabelText('Reject reason: 贵州茅台 600519'),
    'risk note changed',
  );
  const rejectButton = screen.getByRole('button', {
    name: 'Reject: 贵州茅台 600519',
  });
  await user.click(rejectButton);
  await user.click(rejectButton);

  expect((await screen.findByRole('alert')).textContent).toContain(
    'manual order not found',
  );
  expect(await screen.findByText('贵州茅台 600519')).toBeTruthy();
});

test('renders loading error and empty states', async () => {
  renderTradingPage({ ordersFail: true });
  expect(
    await screen.findByText('Failed to load pending orders.'),
  ).toBeTruthy();

  cleanup();
  vi.unstubAllGlobals();
  renderTradingPage({ orders: [] });
  expect(
    await screen.findByText('No orders are waiting for manual confirmation.'),
  ).toBeTruthy();
  expect(
    await screen.findByText('No completed order decisions are available yet.'),
  ).toBeTruthy();
});
