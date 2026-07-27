import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { AiResearchPage } from './ai-research-page';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    status: 200,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('opens the cited research canvas from canonical persisted context', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/backtest/results')) {
      return jsonResponse([
        {
          id: 17,
          created_at: '2026-07-27T08:00:00Z',
          strategy: 'dual_ma',
          total_return: 0.04,
          sharpe: 0.8,
          max_drawdown: -0.09,
        },
      ]);
    }
    if (url.includes('/api/account-strategy')) {
      return jsonResponse({
        strategy_id: 'dual_ma',
        strategy_name: 'Dual Moving Average',
        status: 'research_only',
        scope: 'account',
        auto_trade_enabled: false,
        attribution_status: 'not_started',
        limitations: [],
      });
    }
    if (url.includes('/api/ai/research-tasks?limit=20')) {
      return jsonResponse({ tasks: [] });
    }
    if (url.includes('/api/ai/research-task-analyses?limit=20')) {
      return jsonResponse({ analyses: [] });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <AiResearchPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect(
    await screen.findByRole('heading', { name: 'Cited research review' }),
  ).toBeTruthy();
  expect(await screen.findByText('Canonical report #17')).toBeTruthy();
  expect(
    await screen.findByText('Exact persisted account assignment'),
  ).toBeTruthy();
  expect(screen.getByTestId('ai-research-primary-canvas')).toBeTruthy();
  expect(await screen.findByText('Human research tasks')).toBeTruthy();
  const reviewQueue = await screen.findByText(
    'No human research task has been recorded yet.',
  );
  const researchQuestion = screen.getByLabelText('Research question');
  expect(
    reviewQueue.compareDocumentPosition(researchQuestion) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    screen.getByText('No broker, order, or capital authority'),
  ).toBeTruthy();
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/ai/research-tasks?limit=20'),
    ),
  ).toBe(true);
});
