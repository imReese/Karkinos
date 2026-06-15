import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { BacktestPage } from './backtest-page';

const savedSummary = {
  id: 1,
  created_at: '2026-05-15T10:00:00+08:00',
  strategy: 'dual_ma',
  total_return: 0.082,
  sharpe: 1.27,
  max_drawdown: 0.044,
};

const savedReport = {
  id: 1,
  created_at: '2026-05-15T10:00:00+08:00',
  config: {
    start_date: '2025-01-02',
    end_date: '2026-05-15',
    initial_cash: 100000,
    strategy: 'dual_ma',
    short_period: 5,
    long_period: 20,
    assets: [{ symbol: '600519', asset_class: 'stock' }],
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 108200,
    total_return: 0.082,
    annual_return: 0.11,
    sharpe: 1.27,
    sortino: 1.56,
    max_drawdown: 0.044,
    calmar: 2.5,
    volatility: 0.14,
    win_rate: 0.58,
    duration_days: 260,
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  metrics_json: {
    calmar: 2.5,
    volatility: 0.14,
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  cost_summary_json: {
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  fills: [],
  equity_curve: [],
};

const runReport = {
  ...savedReport,
  id: 2,
  created_at: '',
  metrics: {
    ...savedReport.metrics,
    final_equity: 112000,
    total_return: 0.12,
    max_drawdown: 0.06,
  },
  metrics_json: {
    ...savedReport.metrics_json,
    calmar: 3.1,
    total_trades: 3,
  },
  cost_summary_json: {
    total_commission: 12.5,
    total_slippage: 3.5,
    total_trades: 3,
    gross_turnover: 24000,
  },
  fills: [],
  equity_curve: [],
};

const strategyCatalog = [
  {
    strategy_id: 'dual_ma',
    name: 'dual_ma',
    display_name: 'Dual Moving Average',
    description: 'Dual moving-average crossover baseline.',
    params: [
      {
        name: 'short_period',
        type: 'int',
        default: 5,
        required: false,
        min: 1,
        max: 250,
        allowed_values: null,
        description: 'Short moving-average window in trading bars.',
      },
      {
        name: 'long_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Long moving-average window in trading bars.',
      },
    ],
    parameter_schema: [
      {
        name: 'short_period',
        type: 'int',
        default: 5,
        required: false,
        min: 1,
        max: 250,
        allowed_values: null,
        description: 'Short moving-average window in trading bars.',
      },
      {
        name: 'long_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Long moving-average window in trading bars.',
      },
    ],
    benchmark_role: 'etf_rotation_trend_following',
    benchmark_universe: ['etf'],
    requires_out_of_sample_validation: true,
    requires_after_cost_report: true,
    validation_notes: [],
  },
  {
    strategy_id: 'bollinger',
    name: 'bollinger',
    display_name: 'Bollinger Mean Reversion',
    description: 'Bollinger band mean-reversion baseline.',
    params: [
      {
        name: 'bb_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Bollinger lookback window in trading bars.',
      },
      {
        name: 'num_std',
        type: 'float',
        default: 2,
        required: false,
        min: 0.1,
        max: 10,
        allowed_values: null,
        description: 'Number of standard deviations used for bands.',
      },
    ],
    parameter_schema: [
      {
        name: 'bb_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Bollinger lookback window in trading bars.',
      },
      {
        name: 'num_std',
        type: 'float',
        default: 2,
        required: false,
        min: 0.1,
        max: 10,
        allowed_values: null,
        description: 'Number of standard deviations used for bands.',
      },
    ],
    benchmark_role: 'a_share_or_etf_mean_reversion',
    benchmark_universe: ['stock', 'etf'],
    requires_out_of_sample_validation: true,
    requires_after_cost_report: true,
    validation_notes: [],
  },
];

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installBacktestFetchMock({
  runFails = false,
  results = [savedSummary],
  strategies = strategyCatalog,
}: {
  runFails?: boolean;
  results?: unknown[];
  strategies?: unknown[];
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/backtest/strategies')) {
        return jsonResponse(strategies);
      }
      if (url.includes('/api/backtest/run')) {
        return runFails
          ? jsonResponse({ detail: 'backtest unavailable' }, { status: 503 })
          : jsonResponse(runReport);
      }
      if (url.includes('/api/backtest/results/1')) {
        return jsonResponse(savedReport);
      }
      if (url.includes('/api/backtest/results')) {
        return jsonResponse(results);
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderBacktestPage(
  options?: Parameters<typeof installBacktestFetchMock>[0] & {
    locale?: 'en' | 'zh';
    navigatorLanguage?: string;
  },
) {
  window.localStorage.clear();
  if (options?.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  Object.defineProperty(window.navigator, 'language', {
    value: options?.navigatorLanguage ?? 'en-US',
    configurable: true,
  });
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installBacktestFetchMock(options);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <BacktestPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the backtest workspace and saved report history', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Strategy replay')).toBeTruthy();
  expect(await screen.findByText('Backtest configuration')).toBeTruthy();
  expect(await screen.findByDisplayValue('Dual Moving Average')).toBeTruthy();
  expect(
    await screen.findByLabelText('Short moving-average window'),
  ).toBeTruthy();
  expect(await screen.findByText('Report selection')).toBeTruthy();
  expect(await screen.findByText('Equity and drawdown')).toBeTruthy();
});

test('defaults strategy parameters to chinese for chinese browser locales', async () => {
  renderBacktestPage({ results: [], navigatorLanguage: 'zh-CN' });

  expect(await screen.findByText('策略回放')).toBeTruthy();
  expect(await screen.findByLabelText('短期均线周期')).toBeTruthy();
  expect(
    await screen.findByText(
      '用于计算短期移动平均线的交易 bar 数，例如 5 表示最近 5 根日线或分钟线。',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText('Short moving-average window in trading bars.'),
  ).toBeNull();
});

test('switches strategy schema controls from the registry', async () => {
  renderBacktestPage({ results: [] });

  await screen.findByText('Bollinger Mean Reversion');
  const strategySelect = screen.getByLabelText('Strategy');
  fireEvent.change(strategySelect, { target: { value: 'bollinger' } });

  expect(
    await screen.findByLabelText('Bollinger lookback window'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Standard-deviation multiplier'),
  ).toBeTruthy();
  expect(screen.queryByLabelText('Short moving-average window')).toBeNull();
});

test('accepts ordinary whole-number initial cash values in browser validation', async () => {
  renderBacktestPage({ results: [] });

  const initialCashInput = (await screen.findByLabelText(
    'Initial cash',
  )) as HTMLInputElement;
  fireEvent.change(initialCashInput, { target: { value: '10000' } });

  expect(initialCashInput.validity.valid).toBe(true);
});

test('localizes built-in strategy names without changing strategy ids', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  expect(await screen.findByText('策略回放')).toBeTruthy();
  expect(await screen.findByDisplayValue('双均线策略')).toBeTruthy();
  expect(await screen.findByText('布林带均值回归')).toBeTruthy();

  fireEvent.change(await screen.findByLabelText('标的代码'), {
    target: { value: '603659' },
  });
  const runButton = screen.getByRole('button', { name: '运行回测' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.strategy).toBe('dual_ma');
});

test('localizes built-in parameter labels and descriptions without changing payload keys', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  expect(await screen.findByLabelText('短期均线周期')).toBeTruthy();
  expect(await screen.findByLabelText('长期均线周期')).toBeTruthy();
  expect(
    await screen.findByText(
      '用于计算短期移动平均线的交易 bar 数，例如 5 表示最近 5 根日线或分钟线。',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText('Short moving-average window in trading bars.'),
  ).toBeNull();

  fireEvent.change(await screen.findByLabelText('短期均线周期'), {
    target: { value: '3' },
  });
  fireEvent.change(await screen.findByLabelText('长期均线周期'), {
    target: { value: '9' },
  });
  const runButton = screen.getByRole('button', { name: '运行回测' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.params).toEqual({ short_period: 3, long_period: 9 });
});

test('runs a backtest and displays metrics_json and cost_summary_json fields', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '603659' },
  });
  fireEvent.change(
    await screen.findByLabelText('Short moving-average window'),
    {
      target: { value: '3' },
    },
  );
  fireEvent.change(await screen.findByLabelText('Long moving-average window'), {
    target: { value: '9' },
  });
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.strategy).toBe('dual_ma');
  expect(payload.params).toEqual({ short_period: 3, long_period: 9 });
  expect(payload.assets).toEqual([{ symbol: '603659', asset_class: 'stock' }]);
  expect(await screen.findByText('Run output')).toBeTruthy();
  expect(await screen.findByText('Calmar 3.10')).toBeTruthy();
  expect(await screen.findByText('3 fills')).toBeTruthy();
  expect(
    await screen.findByText(
      'No equity curve is available for this backtest result.',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'No fill details are available for this saved result. New runs expose per-fill cost records when the backtest engine returns them.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('NaN')).toBeNull();
});

test('shows a clear error when the run endpoint fails', async () => {
  renderBacktestPage({ runFails: true, results: [] });

  await screen.findByText('Strategy replay');
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  expect((await screen.findByRole('alert')).textContent).toContain(
    'backtest unavailable',
  );
  expect(screen.queryByText(/real-time/i)).toBeNull();
});
