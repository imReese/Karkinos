import { useEffect, useState } from 'react';

import {
  datasetErrorMessage,
  usePrepareDataset,
  usePublishedDatasets,
} from '../dataset-api';
import { useBacktestPage } from './backtest-page-context';

export function ResearchDatasetPanel() {
  const {
    symbol,
    assetClass,
    startDate,
    endDate,
    locale,
    selectedDataset,
    selectDataset,
    setDatasetPreparing,
  } = useBacktestPage();
  const [open, setOpen] = useState(false);
  const [refresh, setRefresh] = useState(false);
  const [error, setError] = useState('');
  const datasets = usePublishedDatasets(open);
  const prepare = usePrepareDataset();
  const zh = locale === 'zh';
  const supported = assetClass === 'stock' || assetClass === 'etf';
  useEffect(() => {
    setDatasetPreparing(prepare.isPending);
  }, [prepare.isPending, setDatasetPreparing]);

  async function prepareData() {
    if (assetClass !== 'stock' && assetClass !== 'etf') return;
    setError('');
    try {
      const result = await prepare.mutateAsync({
        symbol: symbol.trim(),
        instrument_type: assetClass,
        start_date: startDate,
        end_date: endDate,
        refresh,
      });
      selectDataset(result);
      setRefresh(false);
    } catch (failure) {
      setError(datasetErrorMessage(failure, zh));
    }
  }

  return (
    <details
      className="min-w-0 border-y border-[var(--app-divider)] py-3"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm font-semibold">
        {zh
          ? 'TDX 研究数据 · 持久保存与离线回测'
          : 'TDX research data · persistent snapshots'}
      </summary>
      <div className="mt-3 grid min-w-0 gap-3 text-sm">
        <p className="app-muted text-xs leading-5">
          {zh
            ? '使用上方的标的和日期准备数据。成功后保存在当前 workspace，重启仍可选择；回测只读取选定 Dataset，不会自动刷新或换源。'
            : 'Prepare the symbol and dates above. Published datasets survive restarts; bound backtests stay offline without refreshing or switching sources.'}
        </p>
        <label className="grid min-w-0 gap-2">
          {zh ? '本次回测的数据输入' : 'Data for this backtest'}
          <select
            className="app-field min-h-11 w-full min-w-0 px-3 py-2"
            value={selectedDataset?.dataset_id ?? ''}
            disabled={prepare.isPending}
            onChange={(event) =>
              selectDataset(
                datasets.data?.datasets.find(
                  (item) => item.dataset_id === event.target.value,
                ) ?? null,
              )
            }
          >
            <option value="">
              {zh
                ? '原有数据源（不绑定新 Dataset）'
                : 'Existing data source (no Dataset binding)'}
            </option>
            {datasets.data?.datasets.map((item) => (
              <option key={item.dataset_id} value={item.dataset_id}>
                {item.instruments.map((asset) => asset.symbol).join(', ')} ·{' '}
                {item.start_date} — {item.end_date} ·{' '}
                {item.dataset_id.slice(7, 17)}
              </option>
            ))}
          </select>
        </label>
        {selectedDataset ? (
          <p
            className="break-all font-mono text-xs"
            data-testid="selected-dataset-id"
          >
            Dataset: {selectedDataset.dataset_id}
          </p>
        ) : null}
        <label className="flex items-start gap-2 text-xs leading-5">
          <input
            type="checkbox"
            checked={refresh}
            disabled={prepare.isPending}
            onChange={(event) => setRefresh(event.target.checked)}
          />
          {zh
            ? '重新获取历史数据并发布新版本（不改写旧 Dataset）'
            : 'Fetch revised history and publish a new version (preserve old datasets)'}
        </label>
        <button
          type="button"
          className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2"
          disabled={
            prepare.isPending || !supported || !/^\d{6}$/.test(symbol.trim())
          }
          onClick={() => void prepareData()}
        >
          {prepare.isPending
            ? zh
              ? '正在准备并保存数据…'
              : 'Preparing and saving…'
            : zh
              ? '从 TDX 准备并保存'
              : 'Prepare and save from TDX'}
        </button>
        <p className="app-muted text-xs leading-5">
          {zh
            ? '准备会请求数据服务并可能消耗积分；不自动重试。默认复用已有区间、补采缺口。当前支持单只股票或 ETF；未复权历史数据仅用于探索性回测，不代表历史 PIT 或总收益已核验。'
            : 'Preparation can use data-service credits; no automatic retries. Existing sessions are reused. One stock or ETF per request; unadjusted backfill is exploratory, not historical PIT or total-return verification.'}
        </p>
        {datasets.data ? (
          <p className="app-muted break-all text-xs">
            {zh ? '持久目录：' : 'Storage: '}
            {datasets.data.storage_path}
            {!datasets.data.tdx_configured
              ? zh
                ? ' · 当前服务未配置 TDX Key'
                : ' · TDX key missing in server configuration'
              : ''}
          </p>
        ) : null}
        {error || datasets.error ? (
          <p role="alert" className="text-xs text-[var(--app-danger)]">
            {error || datasetErrorMessage(datasets.error, zh)}
          </p>
        ) : null}
      </div>
    </details>
  );
}
