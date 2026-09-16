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
  fireEvent.toggle(disclosure);
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
  fireEvent.toggle(disclosure);
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
