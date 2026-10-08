import { useEffect, useState } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import { usePublishedDatasets } from '../dataset-api';
import { observationError } from '../copy-observations';
import { useObservationSource } from '../observation-api';
import { researchDatasetRange } from './backtest-universe';
import { VerifiedDatasetPreparation } from './verified-dataset-preparation';

export function ObservationForwardInput({
  sourceResultId,
  disabled,
  onChange,
}: {
  sourceResultId: number;
  disabled: boolean;
  onChange: (value: { datasetId: string | null; busy: boolean }) => void;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const source = useObservationSource(sourceResultId);
  const datasets = usePublishedDatasets(true);
  const [datasetId, setDatasetId] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [preparing, setPreparing] = useState(false);
  const instruments = source.data?.instruments;
  const matching =
    datasets.data?.datasets?.filter(
      (dataset) =>
        dataset.cross_source_verified === true &&
        dataset.partition_count >= (source.data?.minimum_bars ?? Infinity) &&
        dataset.instruments.length === instruments?.length &&
        dataset.instruments.every((item) =>
          instruments.some(
            (expected) =>
              item.symbol === expected.symbol &&
              item.instrument_type === expected.instrument_type,
          ),
        ),
    ) ?? [];
  const selected = matching.find((dataset) => dataset.dataset_id === datasetId);
  const busy = preparing || source.isFetching || datasets.isFetching;
  const validId =
    !source.isError && !datasets.isError
      ? (selected?.dataset_id ?? null)
      : null;
  useEffect(() => {
    onChange({ datasetId: validId, busy });
  }, [validId, busy, onChange]);
  const range = researchDatasetRange(
    instruments?.map((item) => ({
      symbol: item.symbol,
      asset_class: item.instrument_type,
    })),
    start,
    end,
  );

  return (
    <section className="min-w-0 space-y-3 border-y border-[var(--app-divider)] py-3 text-xs leading-5">
      <p className="app-muted">
        {zh
          ? '为本次新观察选择独立的预热数据。原研究报告和结果保留；策略状态会从所选数据起点重新计算，后续目标只在启动后发布。'
          : 'Choose warmup data for a new forward experiment. The original report is preserved; strategy state is recomputed from this history and targets are published only after starting.'}
      </p>
      {source.isError ? (
        <p role="alert">{observationError(source.error, locale)}</p>
      ) : source.data ? (
        <p>
          {source.data.instruments
            .map((item) => `${item.symbol} (${item.instrument_type})`)
            .join(', ')}
          {' · '}
          {zh
            ? `每个标的至少 ${source.data.minimum_bars} 个交易日`
            : `At least ${source.data.minimum_bars} sessions per instrument`}
        </p>
      ) : (
        <p role="status">
          {zh
            ? '正在读取冻结策略所需数据…'
            : 'Loading strategy input requirements…'}
        </p>
      )}
      <label className="grid min-w-0 gap-2">
        {zh ? '本次前向观察的预热数据' : 'Warmup dataset for this observation'}
        <select
          className="app-field min-h-11 w-full min-w-0 px-3 py-2"
          value={validId ?? ''}
          disabled={disabled || busy || source.isError || datasets.isError}
          onChange={(event) => setDatasetId(event.target.value)}
        >
          <option value="">
            {zh
              ? '选择匹配的已核验数据集'
              : 'Choose a matching verified dataset'}
          </option>
          {matching.map((dataset) => (
            <option key={dataset.dataset_id} value={dataset.dataset_id}>
              {dataset.start_date} → {dataset.end_date} ·{' '}
              {dataset.partition_count} {zh ? '交易日' : 'sessions'} ·{' '}
              {dataset.dataset_id.slice(7, 17)}
            </option>
          ))}
        </select>
      </label>
      <p className="app-muted">
        {zh
          ? '数据须覆盖最近已收盘交易日。开始时会重新核验完整交易日、预热长度和可用时间；双源一致不等于历史 PIT 或完整总收益。'
          : 'Data must reach the latest closed session. Starting rechecks session coverage, warmup and availability; source agreement does not establish historical PIT or total returns.'}
      </p>
      <button
        type="button"
        className="app-button-secondary min-h-11 px-3 py-2"
        disabled={disabled || busy}
        onClick={() => {
          void source.refetch();
          void datasets.refetch();
        }}
      >
        {zh ? '刷新可用前向数据' : 'Refresh forward inputs'}
      </button>
      {datasets.isError ? (
        <p role="alert">
          {zh
            ? '无法读取数据集，请刷新重试。'
            : 'Could not load datasets. Refresh to retry.'}
        </p>
      ) : null}
      <details className="min-w-0" open={!selected}>
        <summary className="cursor-pointer font-semibold">
          {zh ? '准备本次观察的数据' : 'Prepare data for this observation'}
        </summary>
        <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
          <label className="grid min-w-0 gap-2">
            {zh ? '预热开始日期' : 'Warmup start date'}
            <input
              type="date"
              className="app-field min-h-11 px-3 py-2"
              value={start}
              disabled={disabled || busy}
              onChange={(event) => setStart(event.target.value)}
            />
          </label>
          <label className="grid min-w-0 gap-2">
            {zh ? '最近已收盘交易日' : 'Latest closed session'}
            <input
              type="date"
              className="app-field min-h-11 px-3 py-2"
              value={end}
              disabled={disabled || busy}
              onChange={(event) => setEnd(event.target.value)}
            />
          </label>
        </div>
        <VerifiedDatasetPreparation
          range={range}
          zh={zh}
          disabled={disabled || source.isError || !source.data}
          onPendingChange={setPreparing}
          onPublished={(dataset) => setDatasetId(dataset.dataset_id)}
        />
      </details>
    </section>
  );
}
