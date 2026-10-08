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

import { savedObservation } from '../../../../test-fixtures/shadow-observations';
import { PreferencesContext } from '../../../shared/preferences/context';
import type { ResearchPaperBook } from '../paper-book-contracts';
import { paperBookError } from '../copy-paper-book';
import { ResearchPaperBookPanel } from './research-paper-book-panel';

const identity = '11111111-1111-4111-8111-111111111111';
const datasetId = `sha256:${'a'.repeat(64)}`;
const observation = savedObservation(identity);
observation.lifecycle = 'active';

function initialBook(observationId = identity): ResearchPaperBook {
  return {
    id: `book-${observationId}`,
    observation_id: observationId,
    scope: 'independent_paper',
    lifecycle: 'active',
    version: 0,
    started_at: '2026-09-18T08:02:00Z',
    paused_at: null,
    evaluation_start: '2026-09-21',
    initial_cash: '100000',
    policy: {
      cost_assumptions: {
        schema_version: 'karkinos.backtest_cost_assumptions.v1',
        source: 'builtin',
        slippage_model: 'percent_of_reference_price',
        slippage_bps: '0',
      },
      cost_inputs: {},
      corporate_action_mode: 'reported_distributions_gross',
      currency: 'CNY',
    },
    last_settled_session: null,
    state: {
      cash: '100000',
      equity: '100000',
      dividend_receivable: '0',
      dividend_income: '0',
      positions: {},
    },
    steps: [],
    fills: [],
    attempts: [],
    limitations: [],
    account_authority: false,
    automatic: false,
  };
}
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

function mount(
  handler: (url: string, init?: RequestInit) => Promise<Response>,
  id = identity,
  datasetRows?: () => unknown[],
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/backtest/datasets')
      return Promise.resolve(
        json({
          datasets: datasetRows?.() ?? [
            {
              dataset_id: datasetId,
              start_date: observation.source.start_date,
              end_date: '2026-09-21',
              instruments: observation.universe,
              cross_source_verified: true,
              corporate_action_evidence: { status: 'observed' },
            },
          ],
        }),
      );
    return handler(url, init);
  });
  vi.stubGlobal('fetch', fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = (nextId: string) => (
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
        <ResearchPaperBookPanel
          key={nextId}
          observation={{ ...observation, id: nextId }}
        />
      </PreferencesContext.Provider>
    </QueryClientProvider>
  );
  const rendered = render(view(id));
  return {
    fetchMock,
    rerender: (nextId: string) => rendered.rerender(view(nextId)),
  };
}
function open() {
  const details = screen.getByTestId(
    'research-paper-book-panel',
  ) as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event('toggle'));
}
async function chooseDataset() {
  const select = await screen.findByLabelText(
    'Formal Dataset for paper settlement',
  );
  await waitFor(() =>
    expect(select.querySelector(`option[value="${datasetId}"]`)).not.toBeNull(),
  );
  fireEvent.change(select, { target: { value: datasetId } });
}
afterEach(() => vi.unstubAllGlobals());

test('collects missing distribution evidence in the paper journey before settling its new dataset', async () => {
  const saved = initialBook();
  const original = structuredClone(saved);
  const enrichedId = `sha256:${'b'.repeat(64)}`;
  const raw = {
    dataset_id: datasetId,
    start_date: observation.source.start_date,
    end_date: '2026-09-21',
    instruments: observation.universe,
    cross_source_verified: true,
  };
  const enriched = {
    ...raw,
    dataset_id: enrichedId,
    corporate_action_evidence: { status: 'observed' },
  };
  let available: unknown[] = [raw];
  let completeCollection!: (value: Response) => void;
  const collecting = new Promise<Response>((resolve) => {
    completeCollection = resolve;
  });
  const writes: { url: string; body: Record<string, unknown> }[] = [];
  mount(
    async (url, init) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        writes.push({ url, body });
        if (url.endsWith('/corporate-actions')) return collecting;
        expect(url).toBe(
          `/api/research-observations/${identity}/paper-book/settle`,
        );
        expect(body).toEqual({
          request_id: expect.any(String),
          expected_version: 0,
          dataset_id: enrichedId,
        });
        saved.version = 1;
        saved.last_settled_session = '2026-09-21';
      }
      return json(saved);
    },
    identity,
    () => available,
  );
  open();
  await chooseDataset();
  const settle = screen.getByRole('button', {
    name: 'Settle paper book manually',
  });
  expect(settle).toBeDisabled();
  expect(
    screen.getByText(
      /Collect evidence for the selected dataset before settling/,
    ),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Collect dividend and bonus-share evidence',
    }),
  );
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({
    url: `/api/backtest/datasets/${encodeURIComponent(datasetId)}/corporate-actions`,
    body: { refresh: false },
  });
  expect(
    screen.getByLabelText('Formal Dataset for paper settlement'),
  ).toBeDisabled();
  expect(
    screen.getByRole('button', { name: 'Stop accepting new targets' }),
  ).toBeDisabled();
  expect(settle).toBeDisabled();
  expect(saved).toEqual(original);
  await act(async () => {
    available = [raw, enriched];
    completeCollection(json(enriched));
  });
  await waitFor(() => {
    expect(
      screen.getByLabelText('Formal Dataset for paper settlement'),
    ).toHaveValue(enrichedId);
    expect(settle).toBeEnabled();
  });
  expect(saved).toEqual(original);
  expect(writes).toHaveLength(1);
  fireEvent.click(settle);
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(saved.policy.corporate_action_mode).toBe(
    'reported_distributions_gross',
  );
  await waitFor(() =>
    expect(screen.getByTestId('paper-book-as-of')).toHaveTextContent(
      '2026-09-21',
    ),
  );
});

test('opening only reads; creation needs explicit positive cash and freezes optional cost inputs', async () => {
  let saved: ResearchPaperBook | null = null;
  const writes: Record<string, unknown>[] = [];
  const { fetchMock } = mount(async (_url, init) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      writes.push(body);
      saved = initialBook();
      saved.policy.cost_inputs = body.cost_assumptions;
    }
    return json(saved);
  });
  expect(fetchMock).not.toHaveBeenCalled();
  open();
  const create = await screen.findByRole('button', {
    name: 'Create independent paper book',
  });
  expect(create).toBeDisabled();
  expect(writes).toEqual([]);
  const cash = screen.getByLabelText('Initial simulated cash (CNY)');
  for (const invalid of ['0', '-1', 'NaN', 'Infinity']) {
    fireEvent.change(cash, { target: { value: invalid } });
    expect(create).toBeDisabled();
  }
  fireEvent.change(cash, { target: { value: '100000.00' } });
  fireEvent.click(screen.getByText('Trading cost assumptions'));
  fireEvent.change(screen.getByLabelText('Cost model'), {
    target: { value: 'custom' },
  });
  const commission = screen.getByLabelText('Stock commission (bps)');
  fireEvent.change(commission, { target: { value: '-1' } });
  expect(create).toBeDisabled();
  fireEvent.change(commission, { target: { value: '3' } });
  expect(
    screen.queryByLabelText('ETF commission (bps)'),
  ).not.toBeInTheDocument();
  fireEvent.click(create);
  await screen.findByRole('region', { name: 'Saved book snapshot' });
  expect(writes).toEqual([
    {
      request_id: expect.any(String),
      initial_cash: '100000.00',
      cost_assumptions: { stock_commission_rate: 0.0003 },
    },
  ]);
  expect(screen.getByTestId('paper-book-as-of')).toHaveTextContent(
    'Not settled; initial cash only',
  );
  expect(
    screen.queryByRole('button', { name: 'Create independent paper book' }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh paper book' }));
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Refresh paper book' }),
    ).toBeEnabled(),
  );
  expect(writes).toHaveLength(1);
});

test('failed reads do not offer creation; refresh recovers without mutation', async () => {
  let reads = 0;
  const { fetchMock } = mount(async () =>
    ++reads === 1 ? json({ detail: 'unavailable' }, 503) : json(null),
  );
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not read the paper book',
  );
  expect(
    screen.queryByRole('button', { name: 'Create independent paper book' }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh paper book' }));
  await screen.findByRole('button', { name: 'Create independent paper book' });
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init?.method || init.method === 'GET',
    ),
  ).toBe(true);
});

test('health thresholds require explicit selection and freeze validated percentages with the new book', async () => {
  const writes: Record<string, unknown>[] = [];
  let saved: ResearchPaperBook | null = null;
  mount(async (_url, init) => {
    if (init?.method === 'POST') {
      writes.push(JSON.parse(String(init.body)));
      saved = initialBook();
    }
    return json(saved);
  });
  open();
  const create = await screen.findByRole('button', {
    name: 'Create independent paper book',
  });
  fireEvent.change(screen.getByLabelText('Initial simulated cash (CNY)'), {
    target: { value: '100000' },
  });
  fireEvent.click(
    screen.getByLabelText('Freeze modeled book health rules (optional)'),
  );
  fireEvent.change(screen.getByLabelText('Minimum eligible settled sessions'), {
    target: { value: '0' },
  });
  expect(create).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Minimum eligible settled sessions'), {
    target: { value: '30' },
  });
  fireEvent.change(screen.getByLabelText('Maximum drawdown (%)'), {
    target: { value: '8' },
  });
  fireEvent.change(screen.getByLabelText('Minimum modeled net excess (%)'), {
    target: { value: '-2' },
  });
  fireEvent.change(screen.getByLabelText('Action on breach'), {
    target: { value: 'pause_on_breach' },
  });
  fireEvent.click(create);
  await screen.findByRole('region', { name: 'Saved book snapshot' });
  expect(writes).toEqual([
    {
      request_id: expect.any(String),
      initial_cash: '100000',
      health_policy: {
        mode: 'pause_on_breach',
        minimum_settled_sessions: 30,
        maximum_drawdown: '0.08',
        minimum_net_excess_return: '-0.02',
      },
    },
  ]);
});

test('a version conflict keeps the dated snapshot and requires an explicit refresh without retry', async () => {
  const saved = initialBook();
  saved.last_settled_session = '2026-09-21';
  let writes = 0;
  mount(async (_url, init) => {
    if (init?.method === 'POST') {
      writes++;
      saved.version = 1;
      saved.lifecycle = 'paused';
      return json({ detail: 'paper_book_version_conflict' }, 409);
    }
    return json(saved);
  });
  open();
  await chooseDataset();
  fireEvent.click(
    screen.getByRole('button', { name: 'Settle paper book manually' }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'will not retry automatically',
  );
  expect(screen.getByTestId('paper-book-as-of')).toHaveTextContent(
    '2026-09-21',
  );
  expect(
    screen.getByRole('button', { name: 'Settle paper book manually' }),
  ).toBeDisabled();
  expect(
    screen.getByRole('button', {
      name: 'Refresh dividend and bonus-share evidence',
    }),
  ).toBeDisabled();
  expect(writes).toBe(1);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh paper book' }));
  await waitFor(() =>
    expect(screen.getByTestId('paper-book-lifecycle')).toHaveTextContent(
      'New target intake stopped',
    ),
  );
  expect(
    screen.getByRole('button', { name: 'Settle paper book manually' }),
  ).toBeEnabled();
  expect(
    screen.getByRole('button', { name: 'Stop accepting new targets' }),
  ).toBeDisabled();
  expect(writes).toBe(1);
});

test('pause persists and a paused book still settles without any resume or automation command', async () => {
  const saved = initialBook();
  const commands: string[] = [];
  mount(async (url, init) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      expect(body.expected_version).toBe(saved.version);
      saved.version++;
      if (url.endsWith('/pause')) {
        commands.push('pause');
        saved.lifecycle = 'paused';
        saved.paused_at = '2026-09-18T08:04:00Z';
      } else {
        commands.push('settle');
        expect(body.dataset_id).toBe(datasetId);
        saved.last_settled_session = '2026-09-21';
      }
    }
    return json(saved);
  });
  open();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Stop accepting new targets' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('paper-book-lifecycle')).toHaveTextContent(
      'New target intake stopped',
    ),
  );
  await chooseDataset();
  fireEvent.click(
    screen.getByRole('button', { name: 'Settle paper book manually' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('paper-book-as-of')).toHaveTextContent(
      '2026-09-21',
    ),
  );
  expect(
    screen.queryByRole('button', { name: /resume|automatic/i }),
  ).not.toBeInTheDocument();
  expect(commands).toEqual(['pause', 'settle']);
});

test('switching observations while a command waits cannot display the other book', async () => {
  const first = initialBook();
  const secondId = '22222222-2222-4222-8222-222222222222';
  const second = initialBook(secondId);
  second.state.cash = second.state.equity = second.initial_cash = '25000';
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const { rerender } = mount(async (url, init) => {
    if (init?.method === 'POST') {
      await pending;
      first.lifecycle = 'paused';
      return json(first);
    }
    return json(url.includes(secondId) ? second : first);
  });
  open();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Stop accepting new targets' }),
  );
  rerender(secondId);
  open();
  const snapshot = within(
    await screen.findByRole('region', { name: 'Saved book snapshot' }),
  );
  expect(snapshot.getAllByText('¥25,000.00')).toHaveLength(2);
  await act(async () => {
    finish();
    await pending;
  });
  expect(screen.getByTestId('paper-book-lifecycle')).toHaveTextContent(
    'Accepting newly published targets',
  );
  expect(snapshot.queryByText('¥100,000.00')).not.toBeInTheDocument();
});

test('a response bound to another observation fails closed without offering creation', async () => {
  const { fetchMock } = mount(async () =>
    json(initialBook('another-observation')),
  );
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not read the paper book',
  );
  expect(
    screen.queryByRole('region', { name: 'Saved book snapshot' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Create independent paper book' }),
  ).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test('an original command receipt is followed by the latest persisted snapshot', async () => {
  let saved = initialBook();
  const { fetchMock } = mount(async (_url, init) => {
    if (init?.method === 'POST') {
      const receipt = { ...saved, lifecycle: 'paused' as const, version: 1 };
      saved = { ...receipt, version: 2, last_settled_session: '2026-09-21' };
      return json(receipt);
    }
    return json(saved);
  });
  open();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Stop accepting new targets' }),
  );
  await waitFor(() =>
    expect(screen.getByTestId('paper-book-as-of')).toHaveTextContent(
      '2026-09-21',
    ),
  );
  expect(screen.getByTestId('paper-book-lifecycle')).toHaveTextContent(
    'New target intake stopped',
  );
  expect(
    fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(1);
});

test('a failed current read after saving keeps the previous snapshot and never resends the command', async () => {
  const saved = initialBook();
  let writes = 0;
  let failRead = true;
  mount(async (_url, init) => {
    if (init?.method === 'POST') {
      writes++;
      saved.lifecycle = 'paused';
      saved.version = 1;
      return json(saved);
    }
    return writes && failRead
      ? json({ detail: 'read_unavailable' }, 503)
      : json(saved);
  });
  open();
  fireEvent.click(
    await screen.findByRole('button', { name: 'Stop accepting new targets' }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'operation was not confirmed',
  );
  expect(screen.getByTestId('paper-book-lifecycle')).toHaveTextContent(
    'Accepting newly published targets',
  );
  expect(
    screen.getByRole('button', { name: 'Stop accepting new targets' }),
  ).toBeDisabled();
  failRead = false;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh paper book' }));
  await waitFor(() =>
    expect(screen.getByTestId('paper-book-lifecycle')).toHaveTextContent(
      'New target intake stopped',
    ),
  );
  expect(writes).toBe(1);
});

test('a blocked execution remains a single saved attempt with no invented fill or loss', async () => {
  const saved = initialBook();
  saved.last_settled_session = '2026-09-21';
  saved.attempts = [
    {
      publication_id: 'saved-target',
      symbol: '600000',
      session: '2026-09-21',
      status: 'blocked',
      reason: 'limit',
    },
  ];
  const { fetchMock } = mount(async () => json(saved));
  open();
  await screen.findByRole('region', { name: 'Saved book snapshot' });
  fireEvent.click(
    screen.getByText('Individual execution outcomes and blockers · 1'),
  );
  const attempts = within(
    screen.getByRole('region', {
      name: 'Individual execution outcomes and blockers',
    }),
  );
  expect(attempts.getByText('Attempt blocked')).toBeVisible();
  expect(
    attempts.getByText(
      'Price-limit constraint blocked this attempt; no automatic retry.',
    ),
  ).toBeVisible();
  expect(attempts.getByText('limit')).toBeVisible();
  expect(screen.getAllByText('¥100,000.00')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh paper book' }));
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Refresh paper book' }),
    ).toBeEnabled(),
  );
  expect(screen.getByText('Simulated fills and costs · 0')).toBeVisible();
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init?.method || init.method === 'GET',
    ),
  ).toBe(true);
});

test.each([
  ['paper_book_settled_prefix_conflict', 'previously settled accounting'],
  ['paper_book_code_changed', 'Code differs from the frozen source'],
  ['observation_dataset_unverified', 'cross-source verification'],
  ['corporate_action_evidence_required', 'Distribution evidence'],
  ['paper_book_no_new_sessions', 'No new closed session'],
])(
  'financial blocker %s keeps its code and gives a specific explanation',
  (code, explanation) => {
    expect(paperBookError(new Error(code), 'en')).toEqual({
      code,
      message: expect.stringContaining(explanation),
    });
  },
);
