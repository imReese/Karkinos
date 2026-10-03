import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import type { ReactNode } from 'react';

import {
  normalizedCandidate,
  researchStatus,
  savedObservation,
} from '../../../../test-fixtures/shadow-observations';
import { PreferencesContext } from '../../../shared/preferences/context';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { ShadowResearchObservations } from './shadow-research-observations';
import { ShadowResearchQualificationReview } from './shadow-research-qualification';

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

afterEach(() => vi.unstubAllGlobals());

test('loads only on disclosure and preserves multiple saved histories without mutation controls', async () => {
  const older = savedObservation('older-observation');
  older.started_at = '2026-09-17T08:00:00Z';
  older.lifecycle = 'active';
  older.last_blocker = null;
  older.source.source_code_verified = true;
  older.policy.health_policy = null;
  older.health_decision = null;
  older.publications = [];
  older.outcomes = [];
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL) =>
      new Response(
        JSON.stringify([
          savedObservation(),
          older,
          savedObservation('wrong-report', 700),
        ]),
      ),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount(<ShadowResearchObservations candidate={normalizedCandidate} />);
  expect(fetchMock).not.toHaveBeenCalled();
  open();
  await screen.findByText('saved-observation · v2');
  expect(fetchMock.mock.calls[0]?.[0]).toBe(
    '/api/research-observations?source_backtest_result_id=8&limit=100',
  );
  const rows = screen.getAllByTestId('shadow-research-observation-record');
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent('saved-observation');
  expect(rows[1]).toHaveTextContent('older-observation');
  expect(screen.queryByText(/wrong-report/)).not.toBeInTheDocument();
  rows.forEach(open);
  expect(
    screen.getByText(
      /equivalence to the original backtest code is not established/,
    ),
  ).toBeVisible();
  expect(
    screen.getByText(
      'The frozen record marks source code binding as verified.',
    ),
  ).toBeVisible();
  expect(
    screen.getByText('This observation has no saved publications.'),
  ).toBeVisible();
  expect(screen.getByText(/Measured price response · 1.0%/)).toBeVisible();
  expect(
    screen.getByText(
      /do not replace independent final evaluation or account qualification/,
    ),
  ).toBeVisible();
  expect(screen.getByText(/100 most recently started/)).toBeVisible();
  expect(
    screen.getAllByRole('button').map((button) => button.textContent),
  ).toEqual(['Refresh saved evidence']);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('switching source reports during a pending request never shows the previous response', async () => {
  let resolveFirst!: (response: Response) => void;
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve;
  });
  const fetchMock = vi.fn((url: string) =>
    url.includes('result_id=8&')
      ? first
      : Promise.resolve(
          new Response(JSON.stringify([savedObservation('second-source', 9)])),
        ),
  );
  vi.stubGlobal('fetch', fetchMock);
  const view = mount(
    <ShadowResearchObservations candidate={normalizedCandidate} />,
  );
  open();
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Loading saved observations',
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
  await screen.findByText('second-source · v2');
  await act(async () => {
    resolveFirst(
      new Response(JSON.stringify([savedObservation('first-source')])),
    );
    await first;
  });
  expect(screen.queryByText(/first-source/)).not.toBeInTheDocument();
  expect(screen.getByText('second-source · v2')).toBeVisible();
  expect(screen.getByText('#9')).toBeVisible();
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
  'does not substitute a baseline or an account-bound report for an unbound source',
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

test('a failed read is unavailable rather than empty, and refresh can retrieve the empty history', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response('{}', { status: 503 }))
    .mockResolvedValueOnce(new Response('[]'));
  vi.stubGlobal('fetch', fetchMock);
  mount(<ShadowResearchObservations candidate={normalizedCandidate} />);
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not load observations',
  );
  expect(
    screen.queryByText('No saved observations for this report.'),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole('button', { name: 'Refresh saved evidence' }),
  );
  expect(
    await screen.findByText('No saved observations for this report.'),
  ).toBeVisible();
});

test('qualification resolves both source candidate and run, never an unrelated report, without altering approval', async () => {
  const status = researchStatus(true);
  status.candidates.unshift({
    ...normalizedCandidate,
    run_id: 'different-run',
    candidate_result_id: 99,
  });
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL) => new Response('[]'),
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
  await screen.findByText('No saved observations for this report.');
  expect(fetchMock.mock.calls[0]?.[0]).toBe(
    '/api/research-observations?source_backtest_result_id=8&limit=100',
  );
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
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(approve).not.toHaveBeenCalled();
  expect(
    screen.queryByRole('button', {
      name: 'Approve qualified winner for paper/shadow only',
    }),
  ).not.toBeInTheDocument();
});
