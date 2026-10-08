import { useEffect, useRef, useState } from 'react';

import {
  datasetErrorMessage,
  getVerifiedDatasetJob,
  usePrepareVerifiedDatasetJobs,
  usePublishVerifiedIntervalDataset,
  type PublishedDataset,
  type VerifiedDatasetJob,
  type VerifiedDatasetRange,
} from '../dataset-api';
import { verificationMatchesResearchInputs } from './backtest-universe';

function VerificationInputsNotice({
  mismatch,
  zh,
}: {
  mismatch: boolean;
  zh: boolean;
}) {
  return mismatch ? (
    <p role="alert" className="mt-2 text-xs text-[var(--app-danger)]">
      {zh
        ? '核验任务未覆盖当前完整类型化资产篮子，请重新提交核验。'
        : 'The verification jobs do not cover this complete typed basket. Submit verification again.'}
    </p>
  ) : null;
}

export function VerifiedDatasetPreparation({
  range,
  zh,
  disabled = false,
  onPublished,
  onPendingChange,
}: {
  range: VerifiedDatasetRange | null;
  zh: boolean;
  disabled?: boolean;
  onPublished: (dataset: PublishedDataset) => void;
  onPendingChange?: (pending: boolean) => void;
}) {
  const [reobserve, setReobserve] = useState(false);
  const [error, setError] = useState('');
  const [verification, setVerification] = useState<{
    key: string;
    jobs: VerifiedDatasetJob[];
  } | null>(null);
  const [refreshingJobs, setRefreshingJobs] = useState(false);
  const prepareVerified = usePrepareVerifiedDatasetJobs();
  const publishVerified = usePublishVerifiedIntervalDataset();
  const rangeKey = range ? JSON.stringify(range) : '';
  const latestRange = useRef(rangeKey);
  latestRange.current = rangeKey;
  useEffect(
    () => () => {
      latestRange.current = '';
    },
    [],
  );
  const currentJobs = verification?.key === rangeKey ? verification.jobs : null;
  const verificationPolicy = currentJobs?.[0]?.source_policy_id;
  const sameVerificationPolicy =
    !!verificationPolicy &&
    currentJobs?.every((job) => job.source_policy_id === verificationPolicy);
  const verificationSucceeded =
    !!currentJobs?.length &&
    sameVerificationPolicy &&
    !!range &&
    verificationMatchesResearchInputs(currentJobs, range) &&
    currentJobs.every((job) => job.status === 'succeeded');
  const failedJob = currentJobs?.find((job) => job.status === 'failed');
  const retriedJob = currentJobs?.find(
    (job) => job.status !== 'failed' && job.error,
  );
  const pending =
    prepareVerified.isPending || publishVerified.isPending || refreshingJobs;
  const busy = disabled || pending;
  useEffect(() => {
    onPendingChange?.(pending);
  }, [pending, onPendingChange]);
  async function prepareVerification() {
    if (!range) return;
    setError('');
    try {
      const result = await prepareVerified.mutateAsync(
        reobserve ? { ...range, reobserve: true } : range,
      );
      setVerification({ key: rangeKey, jobs: result.jobs });
    } catch (failure) {
      if (latestRange.current === rangeKey)
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
      if (latestRange.current === rangeKey)
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
      if (latestRange.current === rangeKey) onPublished(result);
    } catch (failure) {
      if (latestRange.current === rangeKey)
        setError(datasetErrorMessage(failure, zh));
    }
  }

  return (
    <div>
      <div className="border-t border-[var(--app-divider)] pt-3">
        <p className="font-medium">
          {zh ? '显式双源核验' : 'Explicit two-source verification'}
        </p>
        <p className="app-muted mt-1 text-xs leading-5">
          {zh
            ? '按完整资产篮子和日期为每个已核验交易日提交任务。全部标的和任务成功后手动发布一个区间 Dataset；核验只证明两份日线相符，不证明历史 PIT 可用或总收益口径。'
            : 'Submit one job per verified trading day for the complete basket and dates above. Publish an interval Dataset after every instrument and job succeeds. Source agreement does not prove historical PIT availability or total return.'}
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
            disabled={busy || !range}
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
        <VerificationInputsNotice
          zh={zh}
          mismatch={
            !!currentJobs &&
            !!range &&
            !verificationMatchesResearchInputs(currentJobs, range)
          }
        />
      </div>
      {error ? (
        <p role="alert" className="text-xs text-[var(--app-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
