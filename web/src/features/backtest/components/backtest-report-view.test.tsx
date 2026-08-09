import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
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
    await screen.findByRole('combobox', { name: 'Select backtest report' }),
  ).toBeTruthy();
  expect(screen.getByText('Summary return')).toBeTruthy();
  expect(screen.getByText('8.2%')).toBeTruthy();

  const skeleton = screen.getByTestId('backtest-report-skeleton');
  expect(skeleton.getAttribute('aria-busy')).toBe('true');
  expect(screen.getByText('Loading selected report.')).toBeTruthy();
  expect(screen.getByTestId('backtest-report-skeleton-chart')).toBeTruthy();
  expect(
    screen.getByTestId('backtest-report-skeleton-disclosures').children,
  ).toHaveLength(4);
  expect(skeleton.className).not.toContain('animate-pulse');
});
