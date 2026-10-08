import { useEffect, useState } from 'react';

import {
  datasetErrorMessage,
  usePrepareDataset,
  usePublishedDatasets,
} from '../dataset-api';
import { useBacktestPage } from './backtest-page-context';
import { DatasetCorporateActions } from './dataset-corporate-actions';
import { researchDatasetRange } from './backtest-universe';
import { VerifiedDatasetPreparation } from './verified-dataset-preparation';
import { buildSingleAsset } from './backtest-page-model';

export function ResearchDatasetPanel() {
  const {
    symbol,
    assetClass,
    runAssets,
    startDate,
    endDate,
    locale,
    selectedDataset,
    selectDataset,
    setDatasetPreparing,
    runBacktest,
  } = useBacktestPage();
  const [open, setOpen] = useState(false);
  const [refresh, setRefresh] = useState(false);
  const [error, setError] = useState('');
  const [verificationPending, setVerificationPending] = useState(false);
  const [collectingActions, setCollectingActions] = useState(false);
  const datasets = usePublishedDatasets(open);
  const prepare = usePrepareDataset();
  const zh = locale === 'zh';
  const range = researchDatasetRange(
    runAssets ?? buildSingleAsset(symbol, assetClass),
    startDate,
    endDate,
  );
  const busy =
    runBacktest.isPending ||
    prepare.isPending ||
    collectingActions ||
    verificationPending;
  useEffect(() => {
    setDatasetPreparing(busy);
  }, [busy, setDatasetPreparing]);

  async function prepareData() {
    if (!range) return;
    setError('');
    try {
      const result = await prepare.mutateAsync({
        ...range,
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
          ? '研究 Dataset · 持久保存与离线回测'
          : 'Research datasets · persistent snapshots'}
      </summary>
      <div className="mt-3 grid min-w-0 gap-3 text-sm">
        <p className="app-muted text-xs leading-5">
          {zh
            ? '使用上方完整资产篮子和日期准备数据。成功后保存在当前 workspace，重启仍可选择；选择 Dataset 会恢复其全部标的与日期，回测只读取该 Dataset，不会自动刷新或换源。'
            : 'Prepare the complete asset basket and dates above. Selecting a saved Dataset restores all its instruments and dates; bound backtests stay offline without refreshing or switching sources.'}
        </p>
        <label className="grid min-w-0 gap-2">
          {zh ? '本次回测的数据输入' : 'Data for this backtest'}
          <select
            className="app-field min-h-11 w-full min-w-0 px-3 py-2"
            value={selectedDataset?.dataset_id ?? ''}
            disabled={busy}
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
                {item.instruments
                  .map((asset) => `${asset.symbol} (${asset.instrument_type})`)
                  .join(', ')}{' '}
                · {item.start_date} — {item.end_date} ·{' '}
                {item.cross_source_verified
                  ? zh
                    ? '双源核验 · '
                    : 'Two-source verified · '
                  : ''}
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
        <DatasetCorporateActions
          dataset={selectedDataset}
          locale={locale}
          busy={busy}
          onSelect={selectDataset}
          onPendingChange={setCollectingActions}
        />
        <label className="flex items-start gap-2 text-xs leading-5">
          <input
            type="checkbox"
            checked={refresh}
            disabled={busy}
            onChange={(event) => setRefresh(event.target.checked)}
          />
          {zh
            ? '重新获取历史数据并发布新版本（不改写旧 Dataset）'
            : 'Fetch revised history and publish a new version (preserve old datasets)'}
        </label>
        <button
          type="button"
          className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2"
          disabled={busy || !range}
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
            ? '准备会请求数据服务并可能消耗积分；不自动重试。默认复用已有区间、补采缺口。一次支持最多 32 只股票 / ETF，费用与工作量随标的和交易日增加；未复权历史数据仅用于探索性回测，不代表历史 PIT 或总收益已核验。'
            : 'Preparation can use data-service credits; no automatic retries. Existing sessions are reused. Prepare up to 32 stocks / ETFs; work and data costs grow with instruments and sessions. Unadjusted backfill is exploratory, not historical PIT or total-return verification.'}
        </p>
        <VerifiedDatasetPreparation
          range={range}
          zh={zh}
          disabled={
            runBacktest.isPending || prepare.isPending || collectingActions
          }
          onPublished={selectDataset}
          onPendingChange={setVerificationPending}
        />
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
        {datasets.data?.unreadable_dataset_count ? (
          <p role="status" className="text-xs text-[var(--app-danger)]">
            {zh
              ? `本次列表有 ${datasets.data.unreadable_dataset_count} 个 Dataset 清单无法读取，已隐藏；已有引用仍须单独校验。`
              : `${datasets.data.unreadable_dataset_count} dataset manifests in this list could not be read and are hidden; existing references still require individual validation.`}
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
