import { useEffect, useState } from 'react';

import {
  datasetErrorMessage,
  getVerifiedDatasetJob,
  usePrepareVerifiedDatasetJobs,
  usePrepareDataset,
  usePublishVerifiedIntervalDataset,
  usePublishedDatasets,
  type VerifiedDatasetJob,
  type VerifiedDatasetRange,
} from '../dataset-api';
import { useBacktestPage } from './backtest-page-context';
import { DatasetCorporateActions } from './dataset-corporate-actions';

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
  const [reobserve, setReobserve] = useState(false);
  const [error, setError] = useState('');
  const [verification, setVerification] = useState<{
    key: string;
    jobs: VerifiedDatasetJob[];
  } | null>(null);
  const [refreshingJobs, setRefreshingJobs] = useState(false);
  const [collectingActions, setCollectingActions] = useState(false);
  const datasets = usePublishedDatasets(open);
  const prepare = usePrepareDataset();
  const prepareVerified = usePrepareVerifiedDatasetJobs();
  const publishVerified = usePublishVerifiedIntervalDataset();
  const zh = locale === 'zh';
  const supported = assetClass === 'stock' || assetClass === 'etf';
  const range: VerifiedDatasetRange | null = supported
    ? {
        symbol: symbol.trim(),
        instrument_type: assetClass,
        start_date: startDate,
        end_date: endDate,
      }
    : null;
  const rangeKey = range ? JSON.stringify(range) : '';
  const currentJobs = verification?.key === rangeKey ? verification.jobs : null;
  const verificationPolicy = currentJobs?.[0]?.source_policy_id;
  const sameVerificationPolicy =
    !!verificationPolicy &&
    currentJobs?.every((job) => job.source_policy_id === verificationPolicy);
  const verificationSucceeded =
    !!currentJobs?.length &&
    sameVerificationPolicy &&
    currentJobs.every((job) => job.status === 'succeeded');
  const failedJob = currentJobs?.find((job) => job.status === 'failed');
  const retriedJob = currentJobs?.find(
    (job) => job.status !== 'failed' && job.error,
  );
  const busy =
    prepare.isPending ||
    prepareVerified.isPending ||
    publishVerified.isPending ||
    collectingActions ||
    refreshingJobs;
  useEffect(() => {
    setDatasetPreparing(busy);
  }, [busy, setDatasetPreparing]);

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

  async function prepareVerification() {
    if (!range) return;
    setError('');
    try {
      const result = await prepareVerified.mutateAsync(
        reobserve ? { ...range, reobserve: true } : range,
      );
      setVerification({ key: rangeKey, jobs: result.jobs });
    } catch (failure) {
      setError(datasetErrorMessage(failure, zh));
    }
  }

  async function refreshVerification() {
    if (!currentJobs) return;
    setError('');
    setRefreshingJobs(true);
    try {
      const jobs = await Promise.all(
        currentJobs.map((job) => getVerifiedDatasetJob(job.job_id)),
      );
      setVerification({ key: rangeKey, jobs });
    } catch (failure) {
      setError(datasetErrorMessage(failure, zh));
    } finally {
      setRefreshingJobs(false);
    }
  }

  async function publishVerification() {
    if (!range || !currentJobs || !verificationSucceeded) return;
    setError('');
    try {
      const result = await publishVerified.mutateAsync({
        ...range,
        job_ids: currentJobs.map((job) => job.job_id),
      });
      selectDataset(result);
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
            ? '使用上方的标的和日期准备数据。成功后保存在当前 workspace，重启仍可选择；回测只读取选定 Dataset，不会自动刷新或换源。'
            : 'Prepare the symbol and dates above. Published datasets survive restarts; bound backtests stay offline without refreshing or switching sources.'}
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
                {item.instruments.map((asset) => asset.symbol).join(', ')} ·{' '}
                {item.start_date} — {item.end_date} ·{' '}
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
          disabled={busy || !supported || !/^\d{6}$/.test(symbol.trim())}
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
        <div className="border-t border-[var(--app-divider)] pt-3">
          <p className="font-medium">
            {zh ? '显式双源核验' : 'Explicit two-source verification'}
          </p>
          <p className="app-muted mt-1 text-xs leading-5">
            {zh
              ? '按上方标的和日期为每个已核验交易日提交任务。任务成功后手动发布一个区间 Dataset；核验只证明两份日线相符，不证明历史 PIT 可用或总收益口径。'
              : 'Submit one job per verified trading day for the symbol and dates above. Publish an interval Dataset after every job succeeds. Source agreement does not prove historical PIT availability or total return.'}
          </p>
          <p className="app-muted mt-1 text-xs leading-5">
            {zh
              ? '默认核验策略首选 BaoStock 与腾讯日线（经 AKShare SDK），按不同上游计两源；同一腾讯上游的 tencent 与 akshare_tencent 不算两票。实际任务策略以提交后返回的 ID 为准。'
              : 'The default verification policy first pairs BaoStock with Tencent daily bars through the AKShare SDK. They have different upstreams; tencent and akshare_tencent share one upstream and do not count as two sources. The returned policy ID identifies this request.'}
          </p>
          <label className="mt-2 flex items-start gap-2 text-xs leading-5">
            <input
              type="checkbox"
              checked={reobserve}
              disabled={busy}
              onChange={(event) => setReobserve(event.target.checked)}
            />
            {zh
              ? '重新观察供应商修订（同日相同请求复用任务；旧 Dataset 保留）'
              : 'Observe provider revisions again (identical same-day requests reuse jobs; old datasets remain)'}
          </label>
          {currentJobs ? (
            <p
              className="app-muted mt-1 break-all text-xs"
              data-testid="verified-job-policy"
            >
              {zh ? '本次核验策略：' : 'Verification policy: '}
              {sameVerificationPolicy
                ? verificationPolicy
                : zh
                  ? '任务策略不一致'
                  : 'Job policies differ'}
            </p>
          ) : null}
          {currentJobs?.[0]?.observation_round ? (
            <p className="app-muted mt-1 break-all text-xs">
              {zh ? '观察轮次：' : 'Observation round: '}
              <span className="font-mono tabular-nums">
                {currentJobs[0].observation_round}
              </span>
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2"
              disabled={busy || !range || !/^\d{6}$/.test(range.symbol)}
              onClick={() => void prepareVerification()}
            >
              {zh ? '提交双源核验' : 'Submit two-source verification'}
            </button>
            {currentJobs ? (
              <button
                type="button"
                className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2"
                disabled={busy}
                onClick={() => void refreshVerification()}
              >
                {zh ? '刷新核验状态' : 'Refresh verification status'}
              </button>
            ) : null}
            {currentJobs ? (
              <button
                type="button"
                className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2"
                disabled={busy || !verificationSucceeded}
                onClick={() => void publishVerification()}
              >
                {zh
                  ? '发布核验区间 Dataset'
                  : 'Publish verified interval Dataset'}
              </button>
            ) : null}
          </div>
          {currentJobs ? (
            <p
              className="app-muted mt-2 text-xs"
              data-testid="verified-job-status"
            >
              {zh ? '任务：' : 'Jobs: '}
              {currentJobs.filter((job) => job.status === 'succeeded').length}/
              {currentJobs.length} {zh ? '成功' : 'succeeded'}
              {failedJob
                ? zh
                  ? ` · 失败：${failedJob.error ?? '未知原因'}；当前无法发布`
                  : ` · Failed: ${failedJob.error ?? 'unknown cause'}; cannot publish`
                : retriedJob
                  ? zh
                    ? ` · 最近一次尝试：${retriedJob.error}；任务尚未成功`
                    : ` · Latest attempt: ${retriedJob.error}; job has not succeeded`
                  : ''}
            </p>
          ) : null}
        </div>
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
