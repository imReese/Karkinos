import { useState } from 'react';
import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type { PublishedDataset } from '../dataset-api';
import { DatasetCorporateActions } from './dataset-corporate-actions';

const original: PublishedDataset = {
  dataset_id: `sha256:${'a'.repeat(64)}`,
  start_date: '2026-09-07',
  end_date: '2026-09-11',
  cutoff: '2026-09-16T08:00:00Z',
  instruments: [{ symbol: '600000', instrument_type: 'stock' }],
  partition_count: 5,
  price_basis: 'unadjusted',
  point_in_time_verified: false,
};
const collected: PublishedDataset = {
  ...original,
  dataset_id: `sha256:${'b'.repeat(64)}`,
  corporate_action_evidence: {
    schema_version: 'karkinos.corporate_action_evidence.v1',
    status: 'observed',
    observation_ids: ['observation-1'],
    provider: 'tushare',
    available_at: '2026-10-02T08:00:00Z',
    availability_basis: 'capture_completed_at',
    historical_availability_verified: false,
    covered_action_types: ['cash_dividend', 'bonus_share_distribution'],
    coverage_status: 'provider_reported_only',
    total_record_count: 5,
    matched_event_count: 1,
    undated_event_count: 0,
    events: [],
    returns_modeled: false,
    limitations: [],
  },
};

afterEach(() => vi.unstubAllGlobals());

function mount(initial = original) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(['published-research-datasets'], { datasets: [initial] });
  function Selection() {
    const [dataset, selectDataset] = useState(initial);
    const [pending, setPending] = useState(false);
    return (
      <>
        <output data-testid="selected-dataset">{dataset.dataset_id}</output>
        <button disabled={pending}>运行回测</button>
        <DatasetCorporateActions
          dataset={dataset}
          locale="zh"
          busy={pending}
          onSelect={selectDataset}
          onPendingChange={setPending}
        />
      </>
    );
  }
  render(
    <QueryClientProvider client={client}>
      <Selection />
    </QueryClientProvider>,
  );
  return client;
}

test('explicit collection locks the selection workflow, then selects the new Dataset and preserves the original', async () => {
  let resolve!: (value: Response) => void;
  const request = new Promise<Response>((done) => {
    resolve = done;
  });
  const fetchMock = vi.fn(() => request);
  vi.stubGlobal('fetch', fetchMock);
  const client = mount();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(screen.getByText('未评估')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '采集分红送转证据' }));
  expect(
    await screen.findByRole('button', { name: '正在采集分红送转证据…' }),
  ).toBeDisabled();
  await waitFor(() =>
    expect(screen.getByRole('button', { name: '运行回测' })).toBeDisabled(),
  );
  expect(screen.getByTestId('selected-dataset').textContent).toBe(
    original.dataset_id,
  );
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toBe(
    `/api/backtest/datasets/${encodeURIComponent(original.dataset_id)}/corporate-actions`,
  );
  expect(init.method).toBe('POST');
  expect(JSON.parse(String(init.body))).toEqual({ refresh: false });

  resolve(new Response(JSON.stringify(collected), { status: 200 }));

  await screen.findByText(/分红送转证据已采集，已选中新数据集/);
  expect(screen.getByTestId('selected-dataset').textContent).toBe(
    collected.dataset_id,
  );
  expect(screen.getByText('已采集 · 覆盖未核实')).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '重新采集分红送转证据' }),
  ).toBeEnabled();
  expect(screen.getByRole('button', { name: '运行回测' })).toBeEnabled();
  expect(
    client.getQueryData<{ datasets: PublishedDataset[] }>([
      'published-research-datasets',
    ])?.datasets,
  ).toEqual([collected, original]);
  expect(original.corporate_action_evidence).toBeUndefined();
});

test('existing evidence is refreshed only through the clearly named action', async () => {
  const next = { ...collected, dataset_id: `sha256:${'c'.repeat(64)}` };
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify(next), { status: 200 }),
  );
  vi.stubGlobal('fetch', fetchMock);
  mount(collected);
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '重新采集分红送转证据' }));
  await screen.findByText(/已选中新数据集/);
  const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(JSON.parse(String(init.body))).toEqual({ refresh: true });
  expect(screen.getByTestId('selected-dataset').textContent).toBe(
    next.dataset_id,
  );
});

test.each([
  ['tushare_token_missing', '尚未配置 Tushare Token'],
  ['dataset_corporate_actions_collection_failed', '分红送转证据采集失败'],
  ['dataset_corporate_actions_dataset_unreadable', '无法读取所选数据集'],
])(
  'a %s response stays explicit and preserves selection without retries',
  async (code, message) => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: code }), { status: 422 }),
    );
    vi.stubGlobal('fetch', fetchMock);
    mount();
    fireEvent.click(screen.getByRole('button', { name: '采集分红送转证据' }));
    expect((await screen.findByRole('alert')).textContent).toContain(message);
    expect(screen.getByTestId('selected-dataset').textContent).toBe(
      original.dataset_id,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole('button', { name: '采集分红送转证据' }),
    ).toBeEnabled();
  },
);

test('an ETF selection explains unsupported coverage without making a request', () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  mount({
    ...original,
    instruments: [{ symbol: '510300', instrument_type: 'etf' }],
  });
  expect(screen.getByText(/ETF 等品种的分红送转证据尚不支持/)).toBeTruthy();
  expect(
    screen.getByRole('button', { name: '采集分红送转证据' }),
  ).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
});
