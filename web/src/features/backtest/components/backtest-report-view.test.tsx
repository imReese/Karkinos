import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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

  await user.tab();
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
