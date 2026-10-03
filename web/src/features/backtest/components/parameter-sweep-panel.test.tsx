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
import { CopyContext } from '../../../shared/i18n/context';
import { copy } from '../../../app/copy';
import type {
  BacktestReport,
  BacktestSweepResponse,
  StrategyParameterSchema,
} from '../api';
import { ParameterSweepPanel } from './parameter-sweep-panel';
import { MetricsGrid } from './metrics-grid';

const datasetId = `sha256:${'a'.repeat(64)}`;
const schema: StrategyParameterSchema[] = [
  {
    name: 'short_period',
    type: 'int',
    default: 2,
    required: true,
    description: '',
  },
  {
    name: 'long_period',
    type: 'int',
    default: 3,
    required: true,
    description: '',
  },
];
const response: BacktestSweepResponse = {
  strategy: 'dual_ma',
  rank_by: 'total_return',
  tested_count: 1,
  warnings: [],
  results: [
    {
      rank: 1,
      result_id: 10,
      strategy: 'dual_ma',
      params: { short_period: 2, long_period: 3 },
      score: 0.1,
      metrics: {
        initial_cash: 100000,
        final_equity: 110000,
        total_return: 0.1,
        annual_return: 0.2,
        sharpe: 1.2,
        sortino: 1.3,
        max_drawdown: 0.01,
        win_rate: 0.5,
        duration_days: 5,
      },
    },
  ],
  selected_test_result_id: 11,
  chronological_validation: {
    schema_version: 'karkinos.chronological_sweep.v1',
    experiment_id: 'experiment-1',
    source_dataset_id: datasetId,
    test_start_date: '2026-09-15',
    rank_by: 'total_return',
    selection_basis: 'training_only',
    selected_params: { short_period: 2, long_period: 3 },
    selected_training_result_id: 10,
    training_result_ids: [10],
    tested_count: 1,
    exploratory: true,
    independent_final: false,
    fingerprint: 'chronology-fingerprint',
    limitations: [],
  },
};
const testReport: BacktestReport = {
  id: 11,
  created_at: '2026-10-03T08:00:00Z',
  config: {
    strategy: 'dual_ma',
    dataset_id: datasetId,
    start_date: '2026-09-01',
    end_date: '2026-09-30',
    initial_cash: 100000,
  },
  metrics: {
    ...response.results[0].metrics,
    final_equity: 98000,
    total_return: -0.02,
    annual_return: -0.4,
    sharpe: -0.4,
    sortino: -0.6,
    max_drawdown: 0.02,
    win_rate: 0,
    duration_days: 10,
  },
  equity_curve: [],
  metrics_json: {
    chronological_validation: {
      ...response.chronological_validation!,
      role: 'test',
    },
    execution_window: {
      schema_version: 'karkinos.backtest_execution_window.v1',
      source_dataset_id: datasetId,
      source_snapshot_id: 'source-snapshot',
      source_start_date: '2026-09-01',
      source_end_date: '2026-09-30',
      history_end_date: '2026-09-30',
      evaluation_start_date: '2026-09-15',
      evaluation_end_date: '2026-09-30',
      metric_start_date: '2026-09-16',
      metric_end_date: '2026-09-30',
      warmup_policy: 'strategy_state_only_no_orders_or_book_carry',
      independent_initial_cash: true,
      exploratory: true,
      independent_final: false,
      fingerprint: 'window-fingerprint',
    },
  },
};

function mount({
  dataset = datasetId,
  strategy = 'dual_ma',
  locale = 'en',
}: { dataset?: string; strategy?: string; locale?: 'en' | 'zh' } = {}) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <PreferencesContext.Provider
        value={{
          locale,
          setLocale: () => {},
          theme: 'dark',
          setTheme: () => {},
          resolvedTheme: 'dark',
        }}
      >
        <CopyContext.Provider value={copy[locale]}>
          <ParameterSweepPanel
            startDate="2026-09-01"
            endDate="2026-09-30"
            initialCash="100000"
            strategy={strategy}
            datasetId={dataset}
            parameterSchema={schema}
            parameterValues={{ short_period: '2', long_period: '3' }}
            corporateActionMode="reported_distributions_gross"
            costAssumptions={{ slippage_bps: 12.5 }}
            assets={[{ symbol: '600000', asset_class: 'stock' }]}
          />
        </CopyContext.Provider>
      </PreferencesContext.Provider>
    </QueryClientProvider>,
  );
}
function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200 });
}
afterEach(() => vi.unstubAllGlobals());

test('legacy sweep stays default and omits the chronological boundary and test-report read', async () => {
  const fetchMock = vi.fn(async () =>
    json({
      ...response,
      chronological_validation: undefined,
      selected_test_result_id: undefined,
    }),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount();
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Run parameter sweep' }));
  await screen.findByText('Sweep rankings');
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
  expect(calls).toHaveLength(1);
  expect(JSON.parse(String(calls[0][1].body))).not.toHaveProperty(
    'test_start_date',
  );
  expect(screen.queryByText('Selected candidate · test result')).toBeNull();
});

test.each([{ dataset: '' }, { strategy: 'custom' }])(
  'chronological mode requires a formal Dataset and canonical strategy: %j',
  (options) => {
    mount(options);
    expect(screen.getByRole('checkbox')).toBeDisabled();
    expect(
      screen.getByText(/saved immutable Dataset to use this mode/),
    ).toBeVisible();
    expect(
      screen.getByRole('button', { name: 'Run parameter sweep' }),
    ).toBeEnabled();
  },
);

test('ranks training candidates and reads the selected later test report without mixing its metrics into ranking', async () => {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) =>
      json(String(input).endsWith('/sweep') ? response : testReport),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount();
  fireEvent.click(screen.getByRole('checkbox'));
  const button = screen.getByRole('button', {
    name: 'Run training selection and test',
  });
  expect(button).toBeDisabled();
  const date = screen.getByLabelText('Test start date');
  expect(date).toHaveValue('');
  for (const value of ['2026-09-01', '2026-10-01']) {
    fireEvent.change(date, { target: { value } });
    expect(button).toBeDisabled();
  }
  fireEvent.change(date, { target: { value: '2026-09-15' } });
  fireEvent.click(button);
  await screen.findByText('Training-period rankings');
  const result = await screen.findByRole('region', {
    name: 'Selected candidate · test result',
  });
  await within(result).findByText('-2.0%');
  expect(screen.getByRole('table')).toHaveTextContent('10.0%');
  expect(screen.getByRole('table')).not.toHaveTextContent('-2.0%');
  expect(screen.getByRole('table')).not.toHaveTextContent('Result #11');
  expect(result).toHaveTextContent('Selected training report: #10');
  expect(result).toHaveTextContent('Saved test report: #11');
  expect(result).toHaveTextContent('Recorded performance window · Test period');
  expect(result).toHaveTextContent(
    'Actual metric dates: 2026-09-16 → 2026-09-30',
  );
  expect(result).toHaveTextContent('carries no positions or pending orders');
  expect(result).toHaveTextContent(
    'does not make it an untouched final holdout',
  );
  const detail = within(result)
    .getByText('Chronological evaluation details')
    .closest('details')!;
  detail.open = true;
  expect(within(detail).getByText('2026-09-01 → 2026-09-30')).toBeVisible();
  const submitted = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(submitted).toMatchObject({
    test_start_date: '2026-09-15',
    start_date: '2026-09-01',
    end_date: '2026-09-30',
    dataset_id: datasetId,
    corporate_action_mode: 'reported_distributions_gross',
    cost_assumptions: { slippage_bps: 12.5 },
  });
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/results/11',
      expect.anything(),
    ),
  );
});

test('saved training report uses its own metric window even though input config spans the full Dataset', () => {
  const training = structuredClone(testReport);
  training.metrics_json!.chronological_validation!.role = 'training';
  training.metrics_json!.execution_window!.metric_start_date = '2026-09-01';
  training.metrics_json!.execution_window!.metric_end_date = '2026-09-14';
  render(
    <PreferencesContext.Provider
      value={{
        locale: 'zh',
        setLocale: () => {},
        theme: 'dark',
        setTheme: () => {},
        resolvedTheme: 'dark',
      }}
    >
      <CopyContext.Provider value={copy.zh}>
        <MetricsGrid report={training} />
      </CopyContext.Provider>
    </PreferencesContext.Provider>,
  );
  expect(screen.getByText('已记录绩效区间 · 训练期')).toBeVisible();
  expect(
    screen.getByText('实际指标日期: 2026-09-01 → 2026-09-14'),
  ).toBeVisible();
  expect(screen.getByText(/不继承持仓或待执行订单/)).toBeVisible();
});

test('a rejected split explains missing trading sessions without displaying a selected test result', async () => {
  const fetchMock = vi.fn(
    async () =>
      new Response(
        JSON.stringify({ detail: 'chronological_sweep_insufficient_sessions' }),
        { status: 409 },
      ),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.change(screen.getByLabelText('Test start date'), {
    target: { value: '2026-09-15' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Run training selection and test' }),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'longest moving-average window plus one earlier session',
  );
  expect(screen.queryByText('Selected candidate · test result')).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
