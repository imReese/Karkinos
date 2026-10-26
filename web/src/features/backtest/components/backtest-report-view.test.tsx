import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { BacktestReportView } from './backtest-report-view';

const summary = {
  id: 7,
  created_at: '2026-08-09T08:30:00+08:00',
  strategy: 'dual_ma',
  total_return: 0.082,
  sharpe: 1.27,
  max_drawdown: 0.044,
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    status: 200,
  });
}

function renderReportView() {
  window.localStorage.setItem('karkinos.locale', 'en');
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      addEventListener: vi.fn(),
      matches: false,
      media: query,
      removeEventListener: vi.fn(),
    })),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <BacktestReportView />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

afterEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/backtest');
  vi.unstubAllGlobals();
});

test('preserves the report structure while persisted evidence is loading', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.endsWith('/api/backtest/results')) {
        return jsonResponse([summary]);
      }
      if (url.endsWith('/api/backtest/results/7')) {
        return new Promise<Response>(() => undefined);
      }
      return new Response('Not found', { status: 404 });
    }),
  );

  renderReportView();

  expect(
    await screen.findByRole('listbox', { name: 'Select backtest run' }),
  ).toBeTruthy();
  const registryRow = await screen.findByTestId('backtest-run-registry-row');
  expect(registryRow.getAttribute('aria-selected')).toBe('true');
  expect(registryRow.textContent).toContain('#7');
  expect(registryRow.textContent).toContain('dual_ma');
  expect(screen.getByText('Summary return')).toBeTruthy();
  expect(screen.getAllByText('8.2%')).toHaveLength(2);

  const skeleton = screen.getByTestId('backtest-report-skeleton');
  expect(skeleton.getAttribute('aria-busy')).toBe('true');
  expect(screen.getByText('Loading selected report.')).toBeTruthy();
  expect(screen.getByTestId('backtest-report-skeleton-chart')).toBeTruthy();
  expect(
    screen.getByTestId('backtest-report-skeleton-disclosures').children,
  ).toHaveLength(4);
  expect(skeleton.className).not.toContain('animate-pulse');
});

test('moves listbox focus with arrows and selects a run with Enter or Space', async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.endsWith('/api/backtest/results')) {
        return jsonResponse([
          summary,
          { ...summary, id: 8 },
          { ...summary, id: 9 },
        ]);
      }
      return new Promise<Response>(() => undefined);
    }),
  );
  renderReportView();
  const options = await screen.findAllByRole('option');
  const selectedContext = screen.getByTestId(
    'backtest-selected-report-context',
  );

  fireEvent.click(screen.getByText('Change saved report'));
  options[0].focus();
  expect(options[0]).toHaveFocus();
  await user.keyboard('{ArrowUp}');
  expect(options[0]).toHaveFocus();
  await user.keyboard('{ArrowDown}');
  expect(options[1]).toHaveFocus();
  expect(options[0]).toHaveAttribute('aria-selected', 'true');
  expect(options.filter((option) => option.tabIndex === 0)).toEqual([
    options[1],
  ]);
  expect(selectedContext).toHaveTextContent('Selected report #7');

  await user.keyboard('{Enter}');
  expect(options[1]).toHaveAttribute('aria-selected', 'true');
  expect(selectedContext).toHaveTextContent('Selected report #8');
  await user.keyboard('{End}{ArrowDown}');
  expect(options[2]).toHaveFocus();
  await user.keyboard(' ');
  expect(options[2]).toHaveAttribute('aria-selected', 'true');
  expect(selectedContext).toHaveTextContent('Selected report #9');

  await user.keyboard('{Home}');
  expect(options[0]).toHaveFocus();
  await user.tab();
  expect(options.every((option) => document.activeElement !== option)).toBe(
    true,
  );
  await user.tab({ shift: true });
  expect(options[2]).toHaveFocus();
});

test('retries a failed saved-run read without treating it as an empty history', async () => {
  let attempts = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/backtest/results')) {
        attempts += 1;
        return attempts === 1
          ? new Response(JSON.stringify({ detail: 'unavailable' }), {
              status: 503,
            })
          : jsonResponse([]);
      }
      return new Response('Not found', { status: 404 });
    }),
  );
  renderReportView();
  const retry = await screen.findByRole('button', { name: 'Retry' });
  expect(
    screen.queryByText(/No backtest reports have been saved yet/),
  ).toBeNull();
  await userEvent.setup().click(retry);
  expect(
    await screen.findByText(/No backtest reports have been saved yet/),
  ).toBeTruthy();
  expect(attempts).toBe(2);
});

test('auto-selects the report requested by the url query parameter', async () => {
  window.history.pushState({}, '', '/backtest?id=8');
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.endsWith('/api/backtest/results')) {
        return jsonResponse([
          summary,
          { ...summary, id: 8, strategy: 'etf_rotation' },
        ]);
      }
      if (url.endsWith('/api/backtest/results/8')) {
        return jsonResponse({
          id: 8,
          created_at: '2026-08-09T08:30:00+08:00',
          config: { strategy: 'etf_rotation' },
          initial_cash: 100000,
          final_equity: 150000,
          total_return: 0.5,
          annual_return: 0.15,
          sharpe: 1.5,
          max_drawdown: 0.08,
          equity_curve: [],
          fills: [],
        });
      }
      return new Response('Not found', { status: 404 });
    }),
  );

  renderReportView();

  expect(
    await screen.findByRole('listbox', { name: 'Select backtest run' }),
  ).toBeTruthy();
  const selectedContext = await screen.findByTestId(
    'backtest-selected-report-context',
  );
  expect(selectedContext).toHaveTextContent('Selected report #8');
});

test('allows choosing another saved report from a deep link and restores the URL selection on navigation', async () => {
  window.history.replaceState({}, '', '/backtest?id=8');
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/backtest/results')) {
        return jsonResponse([summary, { ...summary, id: 8 }]);
      }
      return new Promise<Response>(() => undefined);
    }),
  );
  renderReportView();
  const context = await screen.findByTestId('backtest-selected-report-context');
  expect(context).toHaveTextContent('Selected report #8');
  fireEvent.click(screen.getByText('Change saved report'));
  const options = await screen.findAllByRole('option');
  fireEvent.click(options[0]);
  expect(context).toHaveTextContent('Selected report #7');
  expect(window.location.search).toBe('?id=7');
  expect(
    screen.getByRole('link', { name: 'Open report link' }),
  ).toHaveAttribute('href', '/backtest?id=7');
  window.history.pushState({}, '', '/backtest?id=8');
  fireEvent(window, new PopStateEvent('popstate'));
  expect(context).toHaveTextContent('Selected report #8');
});

test.each([
  {
    status: 'invalidated',
    text: 'This backtest evidence was withdrawn from current research and promotion. The original historical record is retained below.',
  },
  {
    status: 'unavailable',
    text: 'Evidence validity is unavailable for current research or promotion. The original historical record is retained below.',
  },
])(
  'labels $status evidence while retaining its saved history',
  async ({ status, text }) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input instanceof Request ? input.url : input.toString();
        if (url.endsWith('/api/backtest/results'))
          return jsonResponse([
            { ...summary, evidence_invalidation: { status } },
          ]);
        if (url.endsWith('/api/backtest/results/7'))
          return new Promise<Response>(() => undefined);
        return new Response('Not found', { status: 404 });
      }),
    );
    renderReportView();
    expect(
      await screen.findByTestId('backtest-evidence-withdrawal'),
    ).toHaveTextContent(text);
    expect(screen.getByText('Selected report #7')).toBeTruthy();
    expect(screen.getAllByText('8.2%')).toHaveLength(2);
  },
);
