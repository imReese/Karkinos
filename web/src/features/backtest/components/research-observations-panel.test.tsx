import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesContext } from '../../../shared/preferences/context';
import type { BacktestReport } from '../api';
import type {
  ResearchObservation,
  ObservationPublication,
} from '../observation-contracts';
import { ResearchObservationsPanel } from './research-observations-panel';

const datasetId = `sha256:${'a'.repeat(64)}`;
const futureDatasetId = `sha256:${'b'.repeat(64)}`;
const observationId = '11111111-1111-4111-8111-111111111111';
const report: BacktestReport = {
  id: 7,
  created_at: '2026-09-15T08:00:00Z',
  config: {
    strategy: 'dual_ma',
    dataset_id: datasetId,
    start_date: '2026-09-01',
    end_date: '2026-09-15',
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
    duration_days: 14,
  },
  equity_curve: [],
};
const dataset = {
  dataset_id: datasetId,
  start_date: '2026-09-01',
  end_date: '2026-09-15',
  instruments: [{ symbol: '600001', instrument_type: 'stock' }],
  cross_source_verified: true,
};
const initial: ResearchObservation = {
  id: observationId,
  source_backtest_result_id: 7,
  started_at: '2026-09-15T08:00:00Z',
  lifecycle: 'active',
  version: 0,
  last_blocker: null,
  source: {
    strategy_kind: 'dual_ma',
    start_date: '2026-09-01',
    dataset_id: datasetId,
    source_code_verified: false,
    source_historical_pit_verified: false,
  },
  universe: [{ symbol: '600001', instrument_type: 'stock' }],
  policy: {
    horizon_sessions: 5,
    max_symbol_weight: '0.25',
    max_gross_weight: '1',
  },
  publications: [],
  outcomes: [],
};
const publication: ObservationPublication = {
  id: 'publication-1',
  decision_session: '2026-09-15',
  published_at: '2026-09-15T08:02:00Z',
  dataset_id: datasetId,
  payload: {
    forecasts: [
      { symbol: '600001', instrument_type: 'stock', action: 'enter' },
    ],
    previous_target_weights: { '600001': '0' },
    target_weights: { '600001': '0.25' },
    rebalance_weight_deltas: { '600001': '0.25' },
    risk_decision: { status: 'allowed', reasons: [] },
    reference_session: '2026-09-16',
    end_session: '2026-09-23',
    horizon_sessions: 5,
  },
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}

function mount(locale: 'en' | 'zh' = 'en', savedReport = report) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <PreferencesContext.Provider
        value={{
          locale,
          setLocale: () => {},
          theme: 'dark',
          setTheme: () => {},
          resolvedTheme: 'dark',
        }}
      >
        <ResearchObservationsPanel report={savedReport} />
      </PreferencesContext.Provider>
    </QueryClientProvider>,
  );
  return view;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test('prepares verified warmup and starts an old report as a separate forward experiment', async () => {
  const oldReport = {
    ...report,
    config: {
      ...report.config,
      dataset_id: null,
      start_date: '2024-01-02',
      end_date: '2024-12-31',
    },
  };
  const warmup = { ...dataset, partition_count: 11 };
  let published = false;
  let saved: ResearchObservation | null = null;
  const commands: { path: string; body: Record<string, unknown> }[] = [];
  const job = {
    job_id: 'job-1',
    trade_date: '2026-09-15',
    source_policy_id: 'verified-policy',
    status: 'queued',
    result_ref: null,
    instruments: warmup.instruments,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (init?.method === 'POST') commands.push({ path, body });
      if (path === '/api/research-observations/sources/7')
        return json({
          source_backtest_result_id: 7,
          strategy_kind: 'dual_ma',
          instruments: warmup.instruments,
          minimum_bars: 3,
        });
      if (path === '/api/backtest/datasets')
        return json({ datasets: published ? [warmup] : [] });
      if (path === '/api/backtest/datasets/verified-jobs')
        return json({ jobs: [job] });
      if (path === '/api/backtest/datasets/verified-jobs/job-1')
        return json({ ...job, status: 'succeeded' });
      if (path === '/api/backtest/datasets/verified-interval') {
        published = true;
        return json(warmup);
      }
      if (path.startsWith('/api/research-observations?'))
        return json(saved ? [saved] : []);
      if (path === '/api/research-observations' && init?.method === 'POST') {
        saved = {
          ...initial,
          source: {
            ...initial.source,
            start_date: '2024-01-02',
            dataset_id: null,
            forward_input: {
              dataset_id: datasetId,
              start_date: warmup.start_date,
              end_date: warmup.end_date,
            },
          },
        };
        return json({ id: observationId });
      }
      if (path === `/api/research-observations/${observationId}`)
        return json(saved);
      throw new Error(`Unexpected request ${path}`);
    }),
  );
  mount('en', oldReport);
  await screen.findByText(/At least 3 sessions per instrument/);
  expect(
    screen.getByRole('button', { name: 'Start observation' }),
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Warmup start date'), {
    target: { value: warmup.start_date },
  });
  fireEvent.change(screen.getByLabelText('Latest closed session'), {
    target: { value: warmup.end_date },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Submit two-source verification' }),
  );
  await screen.findByTestId('verified-job-status');
  expect(
    screen.getByRole('button', { name: 'Publish verified interval Dataset' }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole('button', { name: 'Refresh verification status' }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Publish verified interval Dataset' }),
    ).toBeEnabled(),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Publish verified interval Dataset' }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Start observation' }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Start observation' }));
  await screen.findByText(/Warmup history for this observation/);
  expect(commands.map((command) => command.path)).toEqual([
    '/api/backtest/datasets/verified-jobs',
    '/api/backtest/datasets/verified-interval',
    '/api/research-observations',
  ]);
  expect(commands[0].body).toMatchObject({
    symbol: '600001',
    instrument_type: 'stock',
    start_date: warmup.start_date,
    end_date: warmup.end_date,
  });
  expect(commands[2].body).toMatchObject({
    source_backtest_result_id: 7,
    forward_dataset_id: datasetId,
  });
  expect(oldReport.config.start_date).toBe('2024-01-02');
  expect(oldReport.config.dataset_id).toBeNull();
});

test('cannot select mismatched, unverified or short warmup data for a new observation', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === '/api/research-observations/sources/7')
      return json({
        source_backtest_result_id: 7,
        strategy_kind: 'dual_ma',
        minimum_bars: 20,
        instruments: dataset.instruments,
      });
    if (path === '/api/backtest/datasets')
      return json({
        datasets: [
          { ...dataset, partition_count: 19 },
          { ...dataset, partition_count: 30, cross_source_verified: false },
          {
            ...dataset,
            partition_count: 30,
            instruments: [{ symbol: '600001', instrument_type: 'etf' }],
          },
        ],
      });
    return json([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  mount('en', { ...report, config: { ...report.config, dataset_id: null } });
  await screen.findByText(/At least 20 sessions per instrument/);
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Refresh forward inputs' }),
    ).toBeEnabled(),
  );
  expect(
    within(
      screen.getByLabelText('Warmup dataset for this observation'),
    ).getAllByRole('option'),
  ).toHaveLength(1);
  expect(
    screen.getByRole('button', { name: 'Start observation' }),
  ).toBeDisabled();
});

test('opens the forward journey immediately and permits a saved ETF rotation source', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json([])),
  );
  mount('en', {
    ...report,
    config: { ...report.config, strategy: 'etf_rotation' },
  });
  expect(screen.getByTestId('research-observations-panel')).toHaveAttribute(
    'open',
  );
  expect(screen.getByText('Independent forward observation')).toBeVisible();
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Start observation' }),
    ).toBeEnabled(),
  );
  expect(
    screen.queryByText(/Start from a saved dual moving-average/),
  ).toBeNull();
});

test('starts, publishes, reloads persisted evidence, measures future data and pauses new publications', async () => {
  let saved: ResearchObservation | null = null;
  const commands: { path: string; body: Record<string, unknown> }[] = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === '/api/backtest/datasets')
        return json({
          datasets: [
            dataset,
            { ...dataset, dataset_id: futureDatasetId, end_date: '2026-09-23' },
          ],
        });
      if (
        path ===
        '/api/research-observations?source_backtest_result_id=7&limit=100'
      )
        return json(saved ? [saved] : []);
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        commands.push({ path, body });
        expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
        if (path === '/api/research-observations')
          saved = structuredClone(initial);
        else {
          expect(body.expected_version).toBe(saved!.version);
          saved!.version++;
          if (path.endsWith('/pause')) saved!.lifecycle = 'paused';
          else if (body.dataset_id === datasetId)
            saved!.publications = [publication];
          else
            saved!.outcomes = [
              {
                publication_id: publication.id,
                horizon: 5,
                measured_at: '2026-09-23T08:00:00Z',
                dataset_id: futureDatasetId,
                payload: {
                  status: 'measured',
                  weighted_price_response: '0.025',
                  return_basis: 'unadjusted_price_only',
                  observations: [
                    {
                      symbol: '600001',
                      target_weight: '0.25',
                      price_return: '0.1',
                      weighted_price_response: '0.025',
                    },
                  ],
                },
              },
            ];
        }
        return json({ id: observationId });
      }
      if (path === `/api/research-observations/${observationId}`)
        return json(saved);
      throw new Error(`Unexpected request ${path}`);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const view = mount();
  const start = screen.getByRole('button', { name: 'Start observation' });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await screen.findByText(/No targets published yet/);
  expect(commands[0].body).toMatchObject({
    source_backtest_result_id: 7,
    horizon_sessions: 5,
    max_symbol_weight: '0.25',
    max_gross_weight: '1',
    health_policy: null,
  });
  expect(
    screen.getByText(/original backtest did not bind its code/),
  ).toBeVisible();
  expect(
    screen.getByText(/does not establish historical point-in-time membership/),
  ).toBeVisible();
  await screen.findByRole('option', { name: /2026-09-15 · aaaaaaaaaa/ });
  fireEvent.change(
    screen.getByRole('combobox', {
      name: 'Verified dataset for this observation',
    }),
    { target: { value: datasetId } },
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Publish targets and measure outcomes',
    }),
  );
  await screen.findByText('Awaiting future data');
  expect(commands[1].body).toMatchObject({
    expected_version: 0,
    dataset_id: datasetId,
  });

  view.unmount();
  mount();
  await screen.findByText('Awaiting future data');
  expect(commands).toHaveLength(2);
  await screen.findByRole('option', { name: /2026-09-23 · bbbbbbbbbb/ });
  fireEvent.change(
    screen.getByRole('combobox', {
      name: 'Verified dataset for this observation',
    }),
    { target: { value: futureDatasetId } },
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Publish targets and measure outcomes',
    }),
  );
  await screen.findByText('Measured price response · 2.5%');
  const publicationDetail = screen
    .getByText('Measured price response · 2.5%')
    .closest('details')!;
  publicationDetail.open = true;
  const row = within(publicationDetail)
    .getByRole('rowheader', { name: '600001' })
    .closest('tr')!;
  expect(within(row).getByText('Enter')).toBeVisible();
  expect(within(row).getAllByText('25.0%')).toHaveLength(2);
  expect(within(row).getByText('2.5%')).toBeVisible();
  expect(
    within(publicationDetail).getByText('Within target limits'),
  ).toBeVisible();
  expect(commands[2].body).toMatchObject({
    expected_version: 1,
    dataset_id: futureDatasetId,
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Pause new publications' }),
  );
  await screen.findByRole('button', { name: 'Measure existing publications' });
  expect(
    screen.getByRole('button', { name: 'Pause new publications' }),
  ).toBeDisabled();
  expect(commands[3].body).toMatchObject({ expected_version: 2 });
  expect(screen.getByText(/are not NAV or investment returns/)).toBeVisible();
  expect(
    fetchMock.mock.calls.some(
      ([path]) =>
        String(path) === `/api/research-observations/${observationId}`,
    ),
  ).toBe(true);
  expect(saved!.publications).toHaveLength(1);
  expect(screen.getByText('Health rule not configured')).toBeVisible();
  fireEvent.click(
    screen.getByRole('button', { name: 'Measure existing publications' }),
  );
  await waitFor(() => expect(commands).toHaveLength(5));
  expect(commands[4]).toMatchObject({
    path: `/api/research-observations/${observationId}/advance`,
    body: { expected_version: 3, dataset_id: futureDatasetId },
  });
  expect(saved!.publications).toHaveLength(1);
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Measure existing publications' }),
    ).toBeEnabled(),
  );
});

test('health rules are opt-in and require explicit valid values before freezing the submitted rule', async () => {
  let saved: ResearchObservation | null = null;
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        requests.push(body);
        saved = {
          ...initial,
          policy: { ...initial.policy, health_policy: body.health_policy },
        };
        return json({ id: observationId });
      }
      if (path === `/api/research-observations/${observationId}`)
        return json(saved);
      if (path === '/api/backtest/datasets') return json({ datasets: [] });
      return json(saved ? [saved] : []);
    }),
  );
  mount();
  const start = screen.getByRole('button', { name: 'Start observation' });
  const enable = screen.getByRole('checkbox', {
    name: 'Configure a forward health rule',
  });
  await waitFor(() => expect(start).toBeEnabled());
  expect(enable).not.toBeChecked();
  fireEvent.click(enable);
  expect(start).toBeDisabled();
  const window = screen.getByLabelText('Window of matured intervals');
  const minimum = screen.getByLabelText('Minimum eligible intervals');
  const threshold = screen.getByLabelText(
    'Minimum mean relative price response (decimal)',
  );
  expect(window).toHaveValue(null);
  expect(minimum).toHaveValue(null);
  expect(threshold).toHaveValue('');
  fireEvent.change(window, { target: { value: '4' } });
  fireEvent.change(minimum, { target: { value: '5' } });
  fireEvent.change(threshold, { target: { value: '-0.015' } });
  expect(start).toBeDisabled();
  fireEvent.change(minimum, { target: { value: '3' } });
  fireEvent.change(threshold, { target: { value: 'Infinity' } });
  expect(start).toBeDisabled();
  fireEvent.change(threshold, { target: { value: '-0.015' } });
  fireEvent.change(screen.getByLabelText('When the rule is breached'), {
    target: { value: 'pause_on_breach' },
  });
  expect(start).toBeEnabled();
  fireEvent.click(start);
  await screen.findByText('Awaiting saved health evaluation');
  expect(requests[0].health_policy).toEqual({
    mode: 'pause_on_breach',
    window_intervals: 4,
    minimum_eligible_intervals: 3,
    minimum_mean_relative_price_response: '-0.015',
  });
  const rule = screen.getByRole('region', { name: 'Forward health rule' });
  expect(rule).toHaveTextContent('Minimum eligible intervals: 3');
  expect(rule).toHaveTextContent('100% equal-weight allocation');
  fireEvent.change(threshold, { target: { value: '0.1' } });
  expect(rule).toHaveTextContent('response (decimal): -0.015');
  expect(rule).not.toHaveTextContent('response (decimal): 0.1');
  expect(requests).toHaveLength(1);
});

test('keeps the request identity after an ambiguous start failure and retries the same operation', async () => {
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === 'POST') {
        bodies.push(JSON.parse(String(init.body)));
        if (bodies.length === 1)
          throw new TypeError('connection lost after server commit');
        return json({ id: observationId });
      }
      if (path === `/api/research-observations/${observationId}`)
        return json(initial);
      if (path === '/api/backtest/datasets') return json({ datasets: [] });
      return json(bodies.length > 1 ? [initial] : []);
    }),
  );
  mount();
  const start = screen.getByRole('button', { name: 'Start observation' });
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Start observation' }));
  await screen.findByText(/No targets published yet/);
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual(bodies[0]);
});

test('shows localized blockers and only offers datasets with the exact verified universe and start', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/backtest/datasets')
        return json({
          datasets: [
            dataset,
            {
              ...dataset,
              dataset_id: futureDatasetId,
              cross_source_verified: false,
            },
            {
              ...dataset,
              dataset_id: `sha256:${'c'.repeat(64)}`,
              start_date: '2026-09-02',
            },
            {
              ...dataset,
              dataset_id: `sha256:${'d'.repeat(64)}`,
              instruments: [{ symbol: '600001', instrument_type: 'etf' }],
            },
          ],
        });
      return json([
        { ...initial, last_blocker: { code: 'observation_code_changed' } },
      ]);
    }),
  );
  mount('zh');
  await screen.findByText(/当前实现与观察冻结时不同/);
  const selector = screen.getByRole('combobox', {
    name: '用于本次观察的核验数据集',
  });
  await waitFor(() =>
    expect(selector.querySelectorAll('option')).toHaveLength(2),
  );
  expect(
    screen.getByRole('button', { name: '发布目标并评估结果' }),
  ).toBeDisabled();
});

test('invalid settings and unsupported saved reports cannot start an observation', async () => {
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => json([]),
  );
  vi.stubGlobal('fetch', fetchMock);
  const view = mount();
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Start observation' }),
    ).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText('Maximum symbol weight (0–1)'), {
    target: { value: '0' },
  });
  expect(
    screen.getByRole('button', { name: 'Start observation' }),
  ).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('weights greater than 0');
  view.unmount();
  mount('en', {
    ...report,
    config: { ...report.config, strategy: 'unsupported_custom' },
  });
  await screen.findByText(/Start from a saved dual moving-average/);
  expect(
    screen.getByRole('button', { name: 'Start observation' }),
  ).toBeDisabled();
  expect(fetchMock.mock.calls.every((call) => call[1]?.method !== 'POST')).toBe(
    true,
  );
});

test('a saved health pause disables new publications while preserving measurement controls', async () => {
  const paused: ResearchObservation = {
    ...initial,
    lifecycle: 'paused',
    last_blocker: { code: 'observation_health_rule_paused' },
    policy: {
      ...initial.policy,
      health_policy: {
        mode: 'pause_on_breach',
        window_intervals: 1,
        minimum_eligible_intervals: 1,
        minimum_mean_relative_price_response: '-0.01',
      },
    },
    health_decision: {
      policy_id: 'karkinos.research.forward_price_health.v1',
      status: 'threshold_breached',
      action: 'pause_observation',
      evaluated_at: '2026-09-23T08:00:00Z',
      market_as_of: '2026-09-23',
      data_available: true,
      counts: {
        scheduled_matured: 1,
        pending: 0,
        missing_matured: 0,
        zero_exposure: 0,
        corporate_action_excluded: 0,
        unresolved: 0,
        eligible: 1,
      },
      mean_relative_price_response: '-0.075',
      threshold: '-0.01',
      selected_publication_ids: [publication.id],
      input_fingerprint: 'sha256:health-inputs',
      blockers: [],
      limitations: [],
      return_basis: 'unadjusted_price_only',
    },
  };
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) =>
      String(input) === '/api/backtest/datasets'
        ? json({ datasets: [dataset] })
        : json([paused]),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount();
  await screen.findByText('Configured threshold breached');
  expect(
    screen.getAllByText(/saved rule paused new publications/),
  ).toHaveLength(1);
  expect(
    screen.getByRole('button', { name: 'Pause new publications' }),
  ).toBeDisabled();
  expect(
    screen.queryByRole('button', {
      name: 'Publish targets and measure outcomes',
    }),
  ).toBeNull();
  await screen.findByRole('option', { name: /2026-09-15 · aaaaaaaaaa/ });
  fireEvent.change(
    screen.getByLabelText('Verified dataset for this observation'),
    {
      target: { value: datasetId },
    },
  );
  expect(
    screen.getByRole('button', { name: 'Measure existing publications' }),
  ).toBeEnabled();
  expect(screen.queryByText(/could not advance/)).toBeNull();
  expect(fetchMock.mock.calls.every((call) => call[1]?.method !== 'POST')).toBe(
    true,
  );
});
