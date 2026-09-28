import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';

export type PublishedDataset = {
  dataset_id: string;
  start_date: string;
  end_date: string;
  cutoff: string;
  instruments: { symbol: string; instrument_type: 'stock' | 'etf' }[];
  partition_count: number;
  price_basis: string;
  point_in_time_verified: boolean;
  cross_source_verified?: boolean;
};

export type VerifiedDatasetJob = {
  trade_date: string;
  job_id: string;
  status: string;
  result_ref: string | null;
  error?: string | null;
};

export type VerifiedDatasetRange = {
  symbol: string;
  instrument_type: 'stock' | 'etf';
  start_date: string;
  end_date: string;
};

type DatasetStatus = {
  tdx_configured: boolean;
  storage_path: string;
  busy: boolean;
  datasets: PublishedDataset[];
};

export function usePublishedDatasets(enabled: boolean) {
  return useQuery({
    queryKey: ['published-research-datasets'],
    queryFn: () => apiClient<DatasetStatus>('/api/backtest/datasets'),
    enabled,
    retry: false,
  });
}

export function usePrepareDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      symbol: string;
      instrument_type: 'stock' | 'etf';
      start_date: string;
      end_date: string;
      refresh: boolean;
    }) => postJson<PublishedDataset>('/api/backtest/datasets', payload),
    retry: false,
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ['published-research-datasets'] }),
  });
}

export function usePrepareVerifiedDatasetJobs() {
  return useMutation({
    mutationFn: (payload: VerifiedDatasetRange) =>
      postJson<{ jobs: VerifiedDatasetJob[] }>(
        '/api/backtest/datasets/verified-jobs',
        payload,
      ),
    retry: false,
  });
}

export async function getVerifiedDatasetJob(jobId: string) {
  return apiClient<VerifiedDatasetJob>(
    `/api/backtest/datasets/verified-jobs/${encodeURIComponent(jobId)}`,
  );
}

export function usePublishVerifiedIntervalDataset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: VerifiedDatasetRange & { job_ids: string[] }) =>
      postJson<PublishedDataset>(
        '/api/backtest/datasets/verified-interval',
        payload,
      ),
    retry: false,
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ['published-research-datasets'] }),
  });
}

export function datasetErrorMessage(error: unknown, zh: boolean): string {
  const code = error instanceof Error ? error.message : '';
  if (code.startsWith('dataset_calendar_unavailable:')) {
    const year = code.split(':')[1];
    return zh
      ? `${year} 年交易日历尚未完成核验。请在行情页面同步并核验该年份，或选择已有核验日历覆盖的区间。不会用周一至周五猜测交易日。`
      : `The ${year} exchange calendar is not verified. Sync and verify it on the Market page before preparing this range.`;
  }
  const messages: Record<string, [string, string]> = {
    verified_daily_market_trading_dates_unavailable: [
      '所选区间没有已核验且已收盘的交易日，请检查交易日历与日期。',
      'No verified closed trading sessions are available in this range.',
    ],
    verified_interval_job_incomplete: [
      '双源核验任务尚未全部成功，请刷新状态后再发布。',
      'Some verification jobs have not succeeded. Refresh their status before publishing.',
    ],
    verified_interval_calendar_evidence_mismatch: [
      '交易日历证据已变化，请重新提交双源核验。',
      'Calendar evidence has changed. Submit verification again.',
    ],
    verified_interval_range_exceeds_366_days: [
      '双源核验一次最多覆盖 366 个自然日。',
      'A verified interval can cover at most 366 calendar days.',
    ],
    dataset_preparation_busy: [
      '已有数据准备任务正在运行，请稍后重试。',
      'Another preparation is running. Please retry later.',
    ],
    dataset_range_exceeds_two_years: [
      '一次最多准备两年的数据，请缩小区间。',
      'Prepare at most two years per request.',
    ],
    dataset_session_not_closed: [
      '结束日期尚未收盘，请选择已结束的交易日。',
      'The end session has not closed yet.',
    ],
    dataset_no_trading_sessions: [
      '所选区间没有交易日。',
      'No trading sessions in this range.',
    ],
    tdx_runtime_configuration_invalid: [
      'TDX 配置不可用。请在启动服务所用的 .env 中配置 Key，然后重启服务。',
      'Configure the TDX key in the server environment file and restart.',
    ],
    dataset_preparation_timeout: [
      '准备超时。已完成的交易日保留，再次准备会补采缺口。',
      'Preparation timed out. Completed sessions are retained for retry.',
    ],
    dataset_preparation_failed: [
      '数据准备失败。已完成的交易日保留；请检查数据权限及该股票的上市、停牌日期后重试。',
      'Preparation failed. Completed sessions are retained. Check data access, listing and suspension dates.',
    ],
  };
  return (
    messages[code]?.[zh ? 0 : 1] ??
    (zh
      ? '研究数据当前不可用，请检查区间、数据完整性及服务状态。'
      : 'Research data is unavailable. Check the range, integrity and server status.')
  );
}
