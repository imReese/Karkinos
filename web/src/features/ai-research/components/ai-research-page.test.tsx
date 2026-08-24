import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
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

test('keeps canonical context neutral until persisted queries settle', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const pending = new Promise<Response>(() => undefined);
  vi.stubGlobal(
    'fetch',
    vi.fn(() => pending),
  );

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

  const metrics = screen.getByTestId('ai-research-context-metrics');
  expect(metrics.querySelector('h2')?.className).toContain(
    'app-type-section-title',
  );
  const checking = await screen.findAllByText('Checking');
  expect(checking).toHaveLength(4);
  expect(checking.filter((element) => element.tagName === 'DD')).toHaveLength(
    2,
  );
  checking
    .filter((element) => element.tagName === 'DD')
    .forEach((element) => {
      expect(element.className).toContain('text-[var(--app-text)]');
      expect(element.className).not.toContain('text-[var(--app-warning-text)]');
    });
  expect(screen.queryByText('No saved backtest is available')).toBeNull();
  expect(screen.queryByText('No account strategy is assigned')).toBeNull();
  const loadingTasks = await screen.findAllByText(
    'Loading saved research tasks…',
  );
  expect(loadingTasks.length).toBeGreaterThan(0);
  expect(loadingTasks[0]?.className).toContain('max-w-full');
  expect(loadingTasks[0]?.parentElement?.className).toContain('min-w-0');
  expect(loadingTasks[0]?.parentElement?.className).not.toContain('shrink-0');
  expect(screen.queryByText('0 tasks')).toBeNull();
  expect(metrics).toBeTruthy();
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
    await screen.findByRole('heading', { name: 'Research review' }),
  ).toBeTruthy();
  expect(await screen.findByText('Saved backtest #17')).toBeTruthy();
  expect(await screen.findByText('Current account assignment')).toBeTruthy();
  const primaryCanvas = screen.getByTestId('ai-research-primary-canvas');
  const contextMetrics = screen.getByTestId('ai-research-context-metrics');
  const commandGrid = screen.getByTestId('ai-research-command-grid');
  expect(commandGrid.className).toContain('app-ai-research-command-grid');
  expect(contextMetrics.className).toContain('xl:order-2');
  expect(primaryCanvas.className).toContain('xl:order-1');
  expect(contextMetrics.querySelector('dl')?.className).toContain(
    'app-ai-research-context-strip',
  );
  expect(
    contextMetrics.compareDocumentPosition(primaryCanvas) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    await screen.findByRole('heading', { name: 'Research tasks' }),
  ).toBeTruthy();
  const reviewQueue = await screen.findByText(
    'No human research task has been recorded yet.',
  );
  const emptyWorkflow = screen.getByTestId('ai-research-empty-workflow');
  expect(emptyWorkflow.className).toContain('grid-cols-1');
  expect(emptyWorkflow.className).toContain('sm:grid-cols-2');
  expect(emptyWorkflow.textContent).toContain('Freeze context');
  expect(emptyWorkflow.textContent).toContain('Run explicitly');
  expect(emptyWorkflow.textContent).toContain('Review the outcome');
  expect(screen.queryByLabelText('Research question')).toBeNull();
  const collapseWorkspace = screen.getByRole('button', {
    name: 'Collapse research workspace',
  });
  expect(collapseWorkspace.getAttribute('aria-expanded')).toBe('true');
  expect(collapseWorkspace.querySelector('.sm\\:hidden')?.textContent).toBe(
    'Collapse',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Draft research task' }));
  const researchQuestion = screen.getByLabelText('Research question');
  expect(
    reviewQueue.compareDocumentPosition(researchQuestion) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.getByText('Advisory only')).toBeTruthy();
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/ai/research-tasks?limit=20'),
    ),
  ).toBe(true);
});
