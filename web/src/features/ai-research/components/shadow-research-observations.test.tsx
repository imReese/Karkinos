import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ReactNode } from 'react';

import {
  candidateSourceReport as sourceReport,
  normalizedCandidate,
  savedPaperBook,
  researchStatus,
  savedObservation,
} from '../../../../test-fixtures/shadow-observations';
import { PreferencesContext } from '../../../shared/preferences/context';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { ShadowResearchObservations } from './shadow-research-observations';
import { ShadowResearchQualificationReview } from './shadow-research-qualification';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(children, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>
        <PreferencesContext.Provider
          value={{
            locale: 'en',
            setLocale: () => {},
            theme: 'light',
            setTheme: () => {},
            resolvedTheme: 'light',
          }}
        >
          {children}
        </PreferencesContext.Provider>
      </QueryClientProvider>
    ),
  });
}

function open(element = screen.getByTestId('shadow-research-observations')) {
  (element as HTMLDetailsElement).open = true;
  fireEvent(element, new Event('toggle'));
}

function reads(url: string) {
  if (url.startsWith('/api/backtest/results/'))
    return json(sourceReport(Number(url.split('/').pop())));
  if (url === '/api/backtest/datasets') return json({ datasets: [] });
  if (url.endsWith('/paper-book')) return json(null);
  return json([]);
}

afterEach(() => vi.unstubAllGlobals());

test('loads the exact candidate report on disclosure and starts observation in place only after explicit submit', async () => {
  const observation = savedObservation();
  observation.lifecycle = 'active';
  observation.publications = [];
  observation.outcomes = [];
  observation.health_decision = null;
  observation.last_blocker = null;
  let started = false;
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/research-observations' && init?.method === 'POST') {
        started = true;
        return json({ id: observation.id });
      }
      if (url === `/api/research-observations/${observation.id}`)
        return json(observation);
      if (url.includes('/api/research-observations?'))
        return json(started ? [observation] : []);
      return reads(url);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  mount(<ShadowResearchObservations candidate={normalizedCandidate} />);
  expect(fetchMock).not.toHaveBeenCalled();
  open();
  const start = await screen.findByRole('button', {
    name: 'Start observation',
  });
  await waitFor(() => expect(start).toBeEnabled());
  expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/backtest/results/8');
  expect(started).toBe(false);
  fireEvent.click(start);
  await screen.findByText('Publishing enabled · saved-ob');
  const writes = fetchMock.mock.calls.filter(
    ([, init]) => init?.method === 'POST',
  );
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({
    source_backtest_result_id: 8,
    horizon_sessions: 5,
  });
  expect(
    fetchMock.mock.calls.some(([url]) => String(url).includes('/results/7')),
  ).toBe(false);
});

test('keeps multiple exact-source histories and shows paper net excess, costs, sample limits and health', async () => {
  const older = savedObservation('older-observation');
  older.started_at = '2026-09-17T08:00:00Z';
  const book = savedPaperBook();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/research-observations?'))
        return json([
          savedObservation(),
          older,
          savedObservation('wrong-report', 700),
        ]);
      if (url.endsWith('/saved-observation/paper-book')) return json(book);
      return reads(url);
    }),
  );
  mount(<ShadowResearchObservations candidate={normalizedCandidate} />);
  open();
  const select = await screen.findByLabelText(
    'Saved observations for this report',
  );
  await waitFor(() =>
    expect(select.querySelectorAll('option')).toHaveLength(2),
  );
  expect(select).not.toHaveTextContent('wrong-report');
  open(await screen.findByTestId('research-paper-book-panel'));
  expect(await screen.findByText('-0.7%')).toBeVisible();
  expect(screen.getByText(/ETF distributions are unverified/)).toBeVisible();
  expect(screen.getByText(/Execution fees:/)).toHaveTextContent(
    'Slippage cost:',
  );
  expect(
    screen.getByText(/Settled sessions after a real target: 2/),
  ).toBeVisible();
  expect(
    screen.getByText(
      'New target intake stopped; continue settling existing positions.',
    ),
  ).toBeVisible();
});

test('switching candidates during a pending source read never mounts the previous report', async () => {
  let resolveFirst!: (response: Response) => void;
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve;
  });
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    return url === '/api/backtest/results/8'
      ? first
      : Promise.resolve(reads(url));
  });
  vi.stubGlobal('fetch', fetchMock);
  const view = mount(
    <ShadowResearchObservations candidate={normalizedCandidate} />,
  );
  open();
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Loading the exact source report',
  );
  view.rerender(
    <ShadowResearchObservations
      candidate={{
        ...normalizedCandidate,
        candidate_id: 'second-candidate',
        candidate_result_id: 9,
      }}
    />,
  );
  await screen.findByRole('button', { name: 'Start observation' });
  await act(async () => {
    resolveFirst(json(sourceReport(8)));
    await first;
  });
  expect(screen.getByText('#9')).toBeVisible();
  expect(screen.queryByText('#8')).not.toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes('source_backtest_result_id=8'),
    ),
  ).toBe(false);
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes('source_backtest_result_id=9'),
    ),
  ).toBe(true);
});

test.each([
  undefined,
  { ...normalizedCandidate, candidate_result_id: null },
  {
    ...normalizedCandidate,
    comparison: {
      ...normalizedCandidate.comparison,
      research_capital_mode: 'account_bound' as const,
    },
  },
])(
  'does not substitute a baseline or account report for an unbound source',
  (candidate) => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    mount(<ShadowResearchObservations candidate={candidate} />);
    open();
    expect(screen.getByRole('status')).toHaveTextContent(
      'No exact normalized source candidate',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  },
);

test.each([503, 200])(
  'a failed or mismatched report cannot start an observation; reload recovers (%s)',
  async (status) => {
    let readCount = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input) === '/api/backtest/results/8' && readCount++ === 0)
          return json(sourceReport(7), status);
        return reads(String(input));
      }),
    );
    mount(<ShadowResearchObservations candidate={normalizedCandidate} />);
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'unavailable or does not match',
    );
    expect(
      screen.queryByRole('button', { name: 'Start observation' }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Reload source report' }),
    );
    expect(
      await screen.findByRole('button', { name: 'Start observation' }),
    ).toBeVisible();
  },
);

test('qualification resolves both source candidate and run without changing approval eligibility', async () => {
  const status = researchStatus(true);
  status.candidates.unshift({
    ...normalizedCandidate,
    run_id: 'different-run',
    candidate_result_id: 99,
  });
  const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
    reads(String(input)),
  );
  const approve = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  const props = {
    approvedBy: 'human:fixture',
    copy: SHADOW_RESEARCH_COPY.en,
    locale: 'en' as const,
    onApprove: approve,
    pending: false,
  };
  const view = mount(
    <ShadowResearchQualificationReview {...props} status={status} />,
  );
  const button = screen.getByRole('button', {
    name: 'Approve qualified winner for paper/shadow only',
  });
  expect(button).toBeDisabled();
  open();
  await screen.findByRole('button', { name: 'Start observation' });
  expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/backtest/results/8');
  expect(button).toBeDisabled();
  status.candidates = status.candidates.filter(
    (candidate) => candidate.run_id !== 'normalized-run',
  );
  view.rerender(
    <ShadowResearchQualificationReview {...props} status={status} />,
  );
  expect(
    within(screen.getByTestId('shadow-research-observations')).getByRole(
      'status',
    ),
  ).toHaveTextContent('No exact normalized source candidate');
  expect(screen.queryByText('#8')).not.toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) => String(url).includes('/results/99')),
  ).toBe(false);
  expect(approve).not.toHaveBeenCalled();
});
