import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { ResearchDatasetPanel } from './research-dataset-panel';

const context = vi.hoisted(() => ({
  symbol: '600000',
  assetClass: 'stock',
  startDate: '2026-09-07',
  endDate: '2026-09-11',
  locale: 'zh',
  selectedDataset: null,
  selectDataset: vi.fn(),
  setDatasetPreparing: vi.fn(),
}));
vi.mock('./backtest-page-context', () => ({ useBacktestPage: () => context }));

const dataset = {
  dataset_id: `sha256:${'a'.repeat(64)}`,
  start_date: '2026-09-07',
  end_date: '2026-09-11',
  cutoff: '2026-09-16T08:00:00Z',
  instruments: [{ symbol: '600000', instrument_type: 'stock' }],
  partition_count: 5,
  price_basis: 'unadjusted',
  point_in_time_verified: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function mount() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ResearchDatasetPanel />
    </QueryClientProvider>,
  );
}

test('preparation is an explicit action and selects the durable published dataset', async () => {
  let published = false;
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        published = true;
        return new Response(JSON.stringify(dataset), { status: 200 });
      }
      return new Response(
        JSON.stringify({
          tdx_configured: true,
          busy: false,
          storage_path: '/workspace/data/research',
          datasets: published ? [dataset] : [],
        }),
        { status: 200 },
      );
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const { container } = mount();
  expect(fetchMock).not.toHaveBeenCalled();
  const disclosure = container.querySelector('details')!;
  disclosure.open = true;
  fireEvent(disclosure, new Event('toggle'));
  await screen.findByText(/持久目录：/);
  expect(
    fetchMock.mock.calls.every(([, init]) => init?.method !== 'POST'),
  ).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '从 TDX 准备并保存' }));
  await waitFor(() =>
    expect(context.selectDataset).toHaveBeenCalledWith(dataset),
  );
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    symbol: '600000',
    instrument_type: 'stock',
    start_date: '2026-09-07',
    end_date: '2026-09-11',
    refresh: false,
  });
  await waitFor(() =>
    expect(context.setDatasetPreparing).toHaveBeenLastCalledWith(false),
  );
});

test('selecting a stored dataset does not trigger acquisition and errors do not select data', async () => {
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, init?: RequestInit) => {
      return init?.method === 'POST'
        ? new Response(
            JSON.stringify({ detail: 'dataset_preparation_failed' }),
            { status: 409 },
          )
        : new Response(
            JSON.stringify({
              tdx_configured: true,
              busy: false,
              storage_path: '/workspace/data/research',
              datasets: [dataset],
            }),
            { status: 200 },
          );
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const { container } = mount();
  const disclosure = container.querySelector('details')!;
  disclosure.open = true;
  fireEvent(disclosure, new Event('toggle'));
  await screen.findByText(/持久目录：/);
  fireEvent.change(screen.getByLabelText('本次回测的数据输入'), {
    target: { value: dataset.dataset_id },
  });
  expect(context.selectDataset).toHaveBeenCalledWith(dataset);
  expect(
    fetchMock.mock.calls.every(([, init]) => init?.method !== 'POST'),
  ).toBe(true);
  context.selectDataset.mockClear();
  fireEvent.click(screen.getByRole('button', { name: '从 TDX 准备并保存' }));
  await screen.findByRole('alert');
  expect(context.selectDataset).not.toHaveBeenCalled();
  expect(
    fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST'),
  ).toHaveLength(1);
});

test('explicit verification publishes only after every job succeeds and selects the interval Dataset', async () => {
  const firstId = '1'.repeat(64);
  const secondId = '2'.repeat(64);
  const jobs = [
    {
      trade_date: '2026-09-07',
      job_id: firstId,
      status: 'queued',
      result_ref: null,
    },
    {
      trade_date: '2026-09-08',
      job_id: secondId,
      status: 'queued',
      result_ref: null,
    },
  ];
  const verifiedDataset = { ...dataset, cross_source_verified: true };
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith('/verified-jobs') && init?.method === 'POST') {
        return new Response(JSON.stringify({ jobs }), { status: 200 });
      }
      if (path.includes('/verified-jobs/') && init?.method !== 'POST') {
        const job = jobs.find((item) => path.endsWith(item.job_id));
        return new Response(
          JSON.stringify({
            ...job,
            status: 'succeeded',
            result_ref: 'dataset:sha256:ok',
          }),
          { status: 200 },
        );
      }
      if (path.endsWith('/verified-interval') && init?.method === 'POST') {
        return new Response(JSON.stringify(verifiedDataset), { status: 200 });
      }
      return new Response(
        JSON.stringify({
          tdx_configured: true,
          busy: false,
          storage_path: '/workspace/data/research',
          datasets: [],
        }),
        { status: 200 },
      );
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const { container } = mount();
  const disclosure = container.querySelector('details')!;
  disclosure.open = true;
  fireEvent(disclosure, new Event('toggle'));
  await screen.findByText(/持久目录：/);
  fireEvent.click(screen.getByRole('button', { name: '提交双源核验' }));
  await screen.findByText('任务：0/2 成功');
  const publish = screen.getByRole('button', { name: '发布核验区间 Dataset' });
  expect((publish as HTMLButtonElement).disabled).toBe(true);
  const submission = fetchMock.mock.calls.find(
    ([input, init]) =>
      String(input).endsWith('/verified-jobs') && init?.method === 'POST',
  );
  expect(JSON.parse(String(submission?.[1]?.body))).toEqual({
    symbol: '600000',
    instrument_type: 'stock',
    start_date: '2026-09-07',
    end_date: '2026-09-11',
  });
  expect(
    fetchMock.mock.calls.some(
      ([input, init]) =>
        String(input) === '/api/backtest/datasets' && init?.method === 'POST',
    ),
  ).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: '刷新核验状态' }));
  await screen.findByText('任务：2/2 成功');
  expect((publish as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(publish);
  await waitFor(() =>
    expect(context.selectDataset).toHaveBeenCalledWith(verifiedDataset),
  );
  const publication = fetchMock.mock.calls.find(
    ([input, init]) =>
      String(input).endsWith('/verified-interval') && init?.method === 'POST',
  );
  expect(JSON.parse(String(publication?.[1]?.body))).toEqual({
    symbol: '600000',
    instrument_type: 'stock',
    start_date: '2026-09-07',
    end_date: '2026-09-11',
    job_ids: [firstId, secondId],
  });
});
