import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { AutomaticTradingSnapshot } from '../api';
import { AutomaticTradingPanel } from './automatic-trading-panel';

const disabledSnapshot: AutomaticTradingSnapshot = {
  enabled: false,
  configured_enabled: false,
  status: 'disabled',
  revision: 7,
  control_fingerprint: 'control-disabled-7',
  reason: '',
  operator_id: '',
  effective_at: null,
  expires_at: null,
  updated_at: '2026-08-28T09:00:00+08:00',
  blockers: [],
  grants_capital_authority: false,
  automatic_broker_submission_implemented: false,
};

const enabledSnapshot: AutomaticTradingSnapshot = {
  ...disabledSnapshot,
  enabled: true,
  configured_enabled: true,
  status: 'enabled',
  revision: 9,
  control_fingerprint: 'control-enabled-9',
  reason: 'bounded operating window',
  operator_id: 'operator-a',
  effective_at: '2099-08-28T09:00:00+08:00',
  expires_at: '2099-08-28T17:00:00+08:00',
  updated_at: '2099-08-28T09:00:00+08:00',
  blockers: ['automatic_broker_submission_not_implemented'],
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function renderPanel() {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'zh');
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <AutomaticTradingPanel />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test.each([
  {
    name: 'missing response data',
    response: () => jsonResponse(null),
  },
  {
    name: 'request error',
    response: () => jsonResponse({ detail: 'unavailable' }, { status: 503 }),
  },
  {
    name: 'unknown backend status',
    response: () =>
      jsonResponse({ ...disabledSnapshot, status: 'future_control_mode' }),
  },
])('fails closed for $name', async ({ response }) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response()),
  );

  renderPanel();

  const panel = await screen.findByTestId('automatic-trading-panel');
  await waitFor(() => {
    expect(panel.getAttribute('data-automatic-trading-state')).toBe(
      'unavailable',
    );
  });
  expect(screen.getByText('门禁状态不可用，按关闭处理')).toBeTruthy();
  expect(screen.getByTestId('automatic-trading-status').className).toContain(
    'var(--app-danger-border)',
  );
  expect(
    (screen.getByRole('button', { name: '开启限时门禁' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    (screen.getByRole('button', { name: '立即关闭' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test('enables a bounded gate with operator, reason, ttl, acknowledgement, and current revision', async () => {
  let currentSnapshot = disabledSnapshot;
  const putBodies: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)));
        currentSnapshot = { ...enabledSnapshot, revision: 8 };
        return jsonResponse(currentSnapshot);
      }
      return jsonResponse(currentSnapshot);
    }),
  );

  renderPanel();
  const user = userEvent.setup();

  expect(await screen.findByText('自动化交易已关闭')).toBeTruthy();
  await user.type(screen.getByLabelText('操作员标识'), 'owner-web');
  await user.type(screen.getByLabelText('操作原因'), '开启日内限时门禁');
  expect((screen.getByLabelText('有效期') as HTMLSelectElement).value).toBe(
    '28800',
  );
  await user.click(screen.getByRole('button', { name: '开启限时门禁' }));

  await waitFor(() => expect(putBodies).toHaveLength(1));
  expect(putBodies[0]).toEqual({
    enabled: true,
    reason: '开启日内限时门禁',
    operator_id: 'owner-web',
    expected_revision: 7,
    ttl_seconds: 28_800,
    acknowledgement:
      'enable_bounded_automatic_trading_gate_without_capital_authority',
  });
  expect(await screen.findByText('限时门禁已开启')).toBeTruthy();
  expect(screen.getByText('修改立即生效，无需重启服务。')).toBeTruthy();
  expect(
    screen.getByText(
      '开启此门禁不会恢复旧的 bounded session，也不会授予交易或资本权限。',
    ),
  ).toBeTruthy();
  expect(screen.getByText('当前尚未实现自动向券商提交订单。')).toBeTruthy();
  expect(
    screen.queryByText('automatic_broker_submission_not_implemented'),
  ).toBeNull();
});

test('disables an enabled gate immediately with the observed revision and no ttl', async () => {
  let currentSnapshot = enabledSnapshot;
  let putBody: Record<string, unknown> | null = null;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        putBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        currentSnapshot = { ...disabledSnapshot, revision: 10 };
        return jsonResponse(currentSnapshot);
      }
      return jsonResponse(currentSnapshot);
    }),
  );

  renderPanel();
  const user = userEvent.setup();

  expect(await screen.findByText('限时门禁已开启')).toBeTruthy();
  await user.clear(screen.getByLabelText('操作员标识'));
  await user.type(screen.getByLabelText('操作员标识'), 'owner-stop');
  await user.clear(screen.getByLabelText('操作原因'));
  await user.type(screen.getByLabelText('操作原因'), '立即停止自动化');
  await user.click(screen.getByRole('button', { name: '立即关闭' }));

  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody).toEqual({
    enabled: false,
    reason: '立即停止自动化',
    operator_id: 'owner-stop',
    expected_revision: 9,
    acknowledgement: 'disable_automatic_trading_gate_immediately',
  });
  expect(putBody).not.toHaveProperty('ttl_seconds');
  expect(await screen.findByText('自动化交易已关闭')).toBeTruthy();
});

test('allows an expired configured gate only to be disabled', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      jsonResponse({
        ...enabledSnapshot,
        enabled: false,
        status: 'expired',
        expires_at: '2026-08-28T08:00:00+08:00',
      }),
    ),
  );

  renderPanel();

  expect(await screen.findByText('门禁已过期，按关闭处理')).toBeTruthy();
  expect(
    (screen.getByRole('button', { name: '开启限时门禁' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    (screen.getByRole('button', { name: '立即关闭' }) as HTMLButtonElement)
      .disabled,
  ).toBe(false);
});
