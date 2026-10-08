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
import type { BacktestReport } from '../api';
import type {
  ObservationAutomation,
  ResearchObservation,
} from '../observation-contracts';
import { ResearchObservationsPanel } from './research-observations-panel';

const identity = '11111111-1111-4111-8111-111111111111';
const otherIdentity = '22222222-2222-4222-8222-222222222222';
const generation = '33333333-3333-4333-8333-333333333333';
const nextGeneration = '44444444-4444-4444-8444-444444444444';
const datasetId = `sha256:${'a'.repeat(64)}`;
const report: BacktestReport = {
  id: 7,
  created_at: '2026-09-18T08:00:00Z',
  config: {
    strategy: 'dual_ma',
    dataset_id: datasetId,
    start_date: '2026-09-01',
    end_date: '2026-09-18',
    initial_cash: 100000,
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 100000,
    total_return: 0,
    annual_return: 0,
    sharpe: 0,
    sortino: 0,
    max_drawdown: 0,
    win_rate: 0,
    duration_days: 1,
  },
  equity_curve: [],
};

function state(id = identity): ObservationAutomation {
  return {
    observation_id: id,
    enabled: false,
    generation: null,
    status: 'disabled',
    last_checked_at: null,
    last_attempt_at: null,
    last_blocker: null,
    dataset_id: null,
    decision_session: null,
    dataset_discovery_complete: null,
  };
}
function observation(id = identity): ResearchObservation {
  return {
    ...savedObservation(id, 7),
    lifecycle: 'active',
    last_blocker: null,
    publications: [],
    outcomes: [],
    health_decision: null,
    automation: state(id),
  };
}
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}

function mount(
  fetchSaved: (url: string, init?: RequestInit) => Promise<Response>,
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/backtest/datasets')
      return Promise.resolve(
        json({
          datasets: [
            {
              dataset_id: datasetId,
              cross_source_verified: true,
              start_date: '2026-09-01',
              end_date: '2026-09-18',
              instruments: [{ symbol: '600000', instrument_type: 'stock' }],
            },
          ],
        }),
      );
    return fetchSaved(url, init);
  });
  vi.stubGlobal('fetch', fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
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
        <ResearchObservationsPanel report={report} />
      </PreferencesContext.Provider>
    </QueryClientProvider>,
  );
  const details = screen.getByTestId(
    'research-observations-panel',
  ) as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event('toggle'));
  return fetchMock;
}
async function controls() {
  return within(
    await screen.findByRole('region', {
      name: 'Automatic advance',
    }),
  );
}
afterEach(() => vi.unstubAllGlobals());

test('paper settlement is separately opted in and survives toggling forecast advance', async () => {
  const saved = observation();
  saved.automation = {
    ...state(),
    generation,
    paper_settlement: {
      enabled: false,
      status: 'disabled',
      last_checked_at: null,
      last_settled_session: null,
      last_blocker: null,
      dataset_id: null,
    },
  };
  const writes: unknown[] = [];
  mount(async (url, init) => {
    if (init?.method === 'PUT') {
      const payload = JSON.parse(String(init.body));
      writes.push(payload);
      saved.automation = {
        ...saved.automation!,
        enabled: payload.enabled,
        generation: nextGeneration,
        status: payload.enabled ? 'ready' : 'disabled',
        paper_settlement: {
          ...saved.automation!.paper_settlement!,
          enabled: payload.paper_settlement_enabled,
          status: payload.paper_settlement_enabled ? 'ready' : 'disabled',
        },
      };
      return json(saved.automation);
    }
    return json(url.includes('?') ? [saved] : saved);
  });
  const view = await controls();
  expect(writes).toEqual([]);
  fireEvent.click(
    view.getByRole('button', { name: 'Enable paper automatic settlement' }),
  );
  await view.findByRole('button', {
    name: 'Disable paper automatic settlement',
  });
  expect(writes).toEqual([
    {
      enabled: false,
      paper_settlement_enabled: true,
      expected_generation: generation,
    },
  ]);
  fireEvent.click(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  );
  await view.findByRole('button', { name: 'Disable automatic advance' });
  expect(writes).toEqual([
    {
      enabled: false,
      paper_settlement_enabled: true,
      expected_generation: generation,
    },
    {
      enabled: true,
      paper_settlement_enabled: true,
      expected_generation: nextGeneration,
    },
  ]);
});

test('opt-in and disable use saved generations, reload persisted state, and preserve manual commands', async () => {
  const saved = observation();
  const writes: unknown[] = [];
  mount(async (url, init) => {
    if (init?.method === 'PUT') {
      const body = JSON.parse(String(init.body));
      writes.push(body);
      expect(url).toBe(`/api/research-observations/${identity}/automation`);
      expect(body.expected_generation).toBe(saved.automation!.generation);
      saved.automation = {
        ...state(),
        enabled: body.enabled,
        generation: body.enabled ? generation : nextGeneration,
        status: body.enabled ? 'waiting' : 'disabled',
        last_checked_at: '2026-09-18T08:05:00Z',
        decision_session: '2026-09-18',
        last_blocker: body.enabled
          ? { code: 'observation_automation_dataset_missing' }
          : null,
      };
      return json(saved.automation);
    }
    return json(url.includes('?') ? [saved] : saved);
  });
  const view = await controls();
  expect(view.getByRole('status')).toHaveTextContent('Automatic advance off');
  expect(view.queryByText('Dataset discovery details')).not.toBeInTheDocument();
  expect(writes).toEqual([]);
  fireEvent.click(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  );
  await waitFor(() =>
    expect(
      view.getByRole('button', { name: 'Disable automatic advance' }),
    ).toBeEnabled(),
  );
  expect(view.getByText(/No complete verified local Dataset/)).toBeVisible();
  expect(view.getByText('2026-09-18')).toBeVisible();
  expect(
    screen.getByRole('button', { name: 'Pause new publications' }),
  ).toBeEnabled();
  fireEvent.click(
    view.getByRole('button', { name: 'Disable automatic advance' }),
  );
  await waitFor(() =>
    expect(
      view.getByRole('button', { name: 'Enable automatic advance' }),
    ).toBeEnabled(),
  );
  expect(saved.lifecycle).toBe('active');
  expect(writes).toEqual([
    { enabled: true, expected_generation: null },
    { enabled: false, expected_generation: generation },
  ]);
});

test('generation conflict never retries and requires refresh before a new explicit change', async () => {
  const saved = observation();
  let writes = 0;
  mount(async (url, init) => {
    if (init?.method === 'PUT') {
      writes++;
      if (writes === 1) {
        saved.automation = {
          ...state(),
          enabled: true,
          generation,
          status: 'ready',
        };
        return json({ detail: 'observation_automation_policy_conflict' }, 409);
      }
      expect(JSON.parse(String(init.body))).toEqual({
        enabled: false,
        expected_generation: generation,
      });
      saved.automation = { ...state(), generation: nextGeneration };
      return json(saved.automation);
    }
    return json(url.includes('?') ? [saved] : saved);
  });
  const view = await controls();
  fireEvent.click(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  );
  expect(await view.findByRole('alert')).toHaveTextContent(
    'your change was not retried',
  );
  expect(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  ).toBeDisabled();
  expect(writes).toBe(1);
  fireEvent.click(
    view.getByRole('button', { name: 'Refresh automatic advance state' }),
  );
  await waitFor(() =>
    expect(
      view.getByRole('button', { name: 'Disable automatic advance' }),
    ).toBeEnabled(),
  );
  fireEvent.click(
    view.getByRole('button', { name: 'Disable automatic advance' }),
  );
  await waitFor(() =>
    expect(
      view.getByRole('button', { name: 'Enable automatic advance' }),
    ).toBeEnabled(),
  );
  expect(writes).toBe(2);
});

test.each([false, true])(
  'a paused observation cannot enable but can turn off existing automation (%s)',
  async (enabled) => {
    const saved = observation();
    saved.lifecycle = 'paused';
    saved.automation = {
      ...state(),
      enabled,
      generation,
      status: enabled ? 'paused' : 'disabled',
    };
    const writes: unknown[] = [];
    mount(async (url, init) => {
      if (init?.method === 'PUT') {
        writes.push(JSON.parse(String(init.body)));
        saved.automation = { ...state(), generation: nextGeneration };
        return json(saved.automation);
      }
      return json(url.includes('?') ? [saved] : saved);
    });
    const view = await controls();
    await waitFor(() =>
      expect(
        screen
          .getByLabelText('Verified dataset for this observation')
          .querySelector(`option[value="${datasetId}"]`),
      ).not.toBeNull(),
    );
    fireEvent.change(
      screen.getByLabelText('Verified dataset for this observation'),
      { target: { value: datasetId } },
    );
    expect(
      screen.getByRole('button', {
        name: 'Measure existing publications',
      }),
    ).toBeEnabled();
    if (enabled) {
      fireEvent.click(
        view.getByRole('button', { name: 'Disable automatic advance' }),
      );
      await waitFor(() =>
        expect(
          view.getByRole('button', { name: 'Enable automatic advance' }),
        ).toBeDisabled(),
      );
      expect(writes).toEqual([
        { enabled: false, expected_generation: generation },
      ]);
    } else
      expect(
        view.getByRole('button', { name: 'Enable automatic advance' }),
      ).toBeDisabled();
    expect(saved.lifecycle).toBe('paused');
  },
);

test('legacy state and failed refresh cannot imply enabled state; diagnostics remain inspectable', async () => {
  const saved = observation();
  delete saved.automation;
  let reads = 0;
  const fetchMock = mount(async () => {
    reads++;
    if (reads === 2) return json({ detail: 'unavailable' }, 503);
    if (reads > 2)
      saved.automation = {
        ...state(),
        enabled: true,
        generation,
        status: 'waiting',
        dataset_discovery_complete: false,
        unreadable_candidate_dataset_ids: ['sha256:unreadable'],
        last_blocker: { code: 'observation_automation_dataset_unreadable' },
      };
    return json([saved]);
  });
  const view = await controls();
  expect(view.getByRole('status')).toHaveTextContent(
    'unavailable in this response',
  );
  expect(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  ).toBeDisabled();
  fireEvent.click(
    view.getByRole('button', { name: 'Refresh automatic advance state' }),
  );
  expect(await view.findByRole('alert')).toHaveTextContent(
    'Could not load the latest',
  );
  fireEvent.click(
    view.getByRole('button', { name: 'Refresh automatic advance state' }),
  );
  await waitFor(() =>
    expect(
      view.getByRole('button', { name: 'Disable automatic advance' }),
    ).toBeEnabled(),
  );
  fireEvent.click(view.getByText('Dataset discovery details'));
  expect(view.getByText('sha256:unreadable')).toBeVisible();
  expect(view.getByText(/Dataset discovery is incomplete/)).toBeVisible();
  expect(
    fetchMock.mock.calls.every(
      ([, init]) => !init?.method || init.method === 'GET',
    ),
  ).toBe(true);
});

test('switching observations during save does not apply the first setting to the newly selected observation', async () => {
  const first = observation();
  const second = observation(otherIdentity);
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  mount(async (url, init) => {
    if (init?.method === 'PUT') {
      expect(url).toContain(identity);
      await pending;
      first.automation = {
        ...state(),
        enabled: true,
        generation,
        status: 'ready',
      };
      return json(first.automation);
    }
    return json(url.includes('?') ? [first, second] : first);
  });
  const view = await controls();
  fireEvent.click(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  );
  expect(
    await view.findByRole('button', { name: 'Saving automatic advance…' }),
  ).toBeDisabled();
  fireEvent.change(
    screen.getByLabelText('Saved observations for this report'),
    { target: { value: otherIdentity } },
  );
  expect((await controls()).getByRole('status')).toHaveTextContent(
    'Automatic advance off',
  );
  await act(async () => {
    finish();
    await pending;
  });
  await waitFor(() =>
    expect(
      (
        screen.getByLabelText(
          'Saved observations for this report',
        ) as HTMLSelectElement
      ).value,
    ).toBe(otherIdentity),
  );
  expect((await controls()).getByRole('status')).toHaveTextContent(
    'Automatic advance off',
  );
  fireEvent.change(
    screen.getByLabelText('Saved observations for this report'),
    { target: { value: identity } },
  );
  expect(
    await (
      await controls()
    ).findByRole('button', { name: 'Disable automatic advance' }),
  ).toBeEnabled();
});

test('an unconfirmed post-save read cannot optimistically change state or resend the write', async () => {
  const saved = observation();
  let writes = 0;
  mount(async (url, init) => {
    if (init?.method === 'PUT') {
      writes++;
      saved.automation = {
        ...state(),
        enabled: true,
        generation,
        status: 'ready',
      };
      return json(saved.automation);
    }
    if (!url.includes('?')) return json({}, 503);
    return json([saved]);
  });
  const view = await controls();
  fireEvent.click(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  );
  expect(await view.findByRole('alert')).toHaveTextContent(
    'Could not confirm the saved state',
  );
  expect(view.getByRole('status')).toHaveTextContent('Automatic advance off');
  expect(
    view.getByRole('button', { name: 'Enable automatic advance' }),
  ).toBeDisabled();
  fireEvent.click(
    view.getByRole('button', { name: 'Refresh automatic advance state' }),
  );
  await waitFor(() =>
    expect(
      view.getByRole('button', { name: 'Disable automatic advance' }),
    ).toBeEnabled(),
  );
  expect(writes).toBe(1);
});
