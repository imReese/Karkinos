import { useRef, useState } from 'react';

import { formatPercent, formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import type { BacktestReport } from '../api';
import { usePublishedDatasets } from '../dataset-api';
import { observationCopy, observationError } from '../copy-observations';
import {
  useObservationCommand,
  useResearchObservations,
} from '../observation-api';
import type {
  ObservationCommand,
  ResearchObservation,
} from '../observation-contracts';
import { ResearchObservationHistory } from './research-observation-history';
import { ResearchObservationHealth } from './research-observation-health';
import { ObservationAutomationControls } from './observation-automation';
import { ResearchPaperBookPanel } from './research-paper-book-panel';
import {
  configuredHealthPolicy,
  ObservationHealthSettings,
  type ObservationHealthDraft,
} from './observation-health-settings';

const fieldClass = 'app-field min-h-11 w-full min-w-0 px-3 py-2';
const buttonClass =
  'app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2 text-xs disabled:opacity-50';

export function ResearchObservationsPanel({
  report,
}: {
  report: BacktestReport;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  const [open, setOpen] = useState(true);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const pendingRequest = useRef<{ key: string; id: string } | null>(null);
  const query = useResearchObservations(open, report.id);
  const mutation = useObservationCommand();
  const observations =
    query.data?.filter(
      (item) => item.source_backtest_result_id === report.id,
    ) ?? [];
  const observation =
    observations.find((item) => item.id === selectedId) ?? observations[0];

  function requestId(key: string) {
    if (pendingRequest.current?.key !== key)
      pendingRequest.current = { key, id: crypto.randomUUID() };
    return pendingRequest.current.id;
  }

  async function submit(command: ObservationCommand) {
    setError(null);
    setSaved(false);
    try {
      const result = await mutation.mutateAsync(command);
      setSelectedId(result.id);
      pendingRequest.current = null;
      setSaved(true);
    } catch (failure) {
      setError(failure);
    }
  }

  return (
    <details
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-testid="research-observations-panel"
    >
      <summary className="cursor-pointer text-sm font-semibold">
        {labels.title}
      </summary>
      <div className="mt-3 min-w-0 space-y-4">
        <p className="app-muted text-xs leading-5">{labels.detail}</p>
        <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
          {labels.boundary}
        </p>
        <ObservationStartForm
          report={report}
          saving={mutation.isPending}
          busy={mutation.isPending || query.isLoading || query.isError}
          onStart={(payload) =>
            void submit({
              kind: 'start',
              payload: {
                ...payload,
                request_id: requestId(`start:${JSON.stringify(payload)}`),
              },
            })
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <label className="grid min-w-0 flex-1 basis-64 gap-2 text-xs">
            {labels.select}
            <select
              className={fieldClass}
              value={observation?.id ?? ''}
              disabled={mutation.isPending || !observations.length}
              onChange={(event) => {
                setSelectedId(event.target.value);
                setSaved(false);
                setError(null);
              }}
            >
              {!observations.length ? (
                <option value="">{labels.none}</option>
              ) : null}
              {observations.map((item) => (
                <option value={item.id} key={item.id}>
                  {formatTimestamp(item.started_at)} ·{' '}
                  {item.lifecycle === 'active' ? labels.active : labels.paused}{' '}
                  · {item.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <button
            className={buttonClass}
            type="button"
            disabled={mutation.isPending || query.isFetching}
            onClick={() => {
              setError(null);
              void query.refetch();
            }}
          >
            {labels.refresh}
          </button>
        </div>
        {query.isLoading ? (
          <p role="status" className="app-muted text-xs">
            {labels.loading}
          </p>
        ) : null}
        {query.isError ? (
          <p role="alert" className="text-xs">
            {labels.loadFailed}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-xs leading-5">
            {observationError(error, locale)}
          </p>
        ) : saved ? (
          <p role="status" className="app-muted text-xs">
            {labels.saved}
          </p>
        ) : null}
        {observation ? (
          <ObservationDetail
            key={observation.id}
            observation={observation}
            busy={mutation.isPending}
            readBusy={query.isFetching}
            readFailed={query.isError}
            onRefresh={async () => !(await query.refetch()).isError}
            onCommand={(kind, datasetId) => {
              const payload = {
                expected_version: observation.version,
                ...(kind === 'advance' ? { dataset_id: datasetId! } : {}),
              };
              const id = requestId(
                `${kind}:${observation.id}:${JSON.stringify(payload)}`,
              );
              if (kind === 'advance')
                void submit({
                  kind,
                  id: observation.id,
                  payload: {
                    request_id: id,
                    expected_version: observation.version,
                    dataset_id: datasetId!,
                  },
                });
              else
                void submit({
                  kind,
                  id: observation.id,
                  payload: {
                    request_id: id,
                    expected_version: observation.version,
                  },
                });
            }}
          />
        ) : null}
      </div>
    </details>
  );
}

function ObservationStartForm({
  report,
  busy,
  saving,
  onStart,
}: {
  report: BacktestReport;
  busy: boolean;
  saving: boolean;
  onStart: (
    payload: Omit<
      Extract<ObservationCommand, { kind: 'start' }>['payload'],
      'request_id'
    >,
  ) => void;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  const [horizon, setHorizon] = useState('5');
  const [symbolLimit, setSymbolLimit] = useState('0.25');
  const [grossLimit, setGrossLimit] = useState('1');
  const [health, setHealth] = useState<ObservationHealthDraft>({
    enabled: false,
    mode: 'observe_only',
    window: '',
    minimum: '',
    threshold: '',
  });
  const healthPolicy = configuredHealthPolicy(health);
  const supported = ['dual_ma', 'ai_formula_research', 'etf_rotation'].includes(
    report.config.strategy,
  );
  const valid =
    Number.isInteger(Number(horizon)) &&
    Number(horizon) >= 1 &&
    Number(horizon) <= 60 &&
    [symbolLimit, grossLimit].every(
      (value) =>
        value.trim() !== '' &&
        Number.isFinite(Number(value)) &&
        Number(value) > 0 &&
        Number(value) <= 1,
    );
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (valid && healthPolicy !== undefined && supported && !busy)
          onStart({
            source_backtest_result_id: report.id,
            horizon_sessions: Number(horizon),
            max_symbol_weight: symbolLimit.trim(),
            max_gross_weight: grossLimit.trim(),
            health_policy: healthPolicy,
          });
      }}
    >
      <fieldset disabled={busy} className="min-w-0 space-y-3">
        <legend className="text-xs font-semibold">{labels.setup}</legend>
        <div className="grid min-w-0 gap-3 sm:grid-cols-3">
          <label className="grid min-w-0 gap-2 text-xs">
            {labels.horizon}
            <input
              className={fieldClass}
              type="number"
              min="1"
              max="60"
              step="1"
              value={horizon}
              onChange={(event) => setHorizon(event.target.value)}
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs">
            {labels.symbolLimit}
            <input
              className={fieldClass}
              type="number"
              min="0"
              max="1"
              step="any"
              value={symbolLimit}
              onChange={(event) => setSymbolLimit(event.target.value)}
            />
          </label>
          <label className="grid min-w-0 gap-2 text-xs">
            {labels.grossLimit}
            <input
              className={fieldClass}
              type="number"
              min="0"
              max="1"
              step="any"
              value={grossLimit}
              onChange={(event) => setGrossLimit(event.target.value)}
            />
          </label>
        </div>
        <ObservationHealthSettings value={health} onChange={setHealth} />
        {!valid ? (
          <p className="text-xs" role="alert">
            {labels.invalid}
          </p>
        ) : null}
        {!supported ? (
          <p className="app-muted text-xs leading-5">{labels.unsupported}</p>
        ) : null}
        <button
          className={buttonClass}
          type="submit"
          disabled={!valid || healthPolicy === undefined || !supported}
        >
          {saving ? labels.busy : labels.start}
        </button>
      </fieldset>
    </form>
  );
}

function ObservationDetail({
  observation,
  busy,
  readBusy,
  readFailed,
  onRefresh,
  onCommand,
}: {
  observation: ResearchObservation;
  busy: boolean;
  readBusy: boolean;
  readFailed: boolean;
  onRefresh: () => Promise<boolean>;
  onCommand: (kind: 'advance' | 'pause', datasetId?: string) => void;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  const datasets = usePublishedDatasets(true);
  const [datasetId, setDatasetId] = useState('');
  const matching =
    datasets.data?.datasets.filter(
      (item) =>
        item.cross_source_verified === true &&
        /^sha256:[0-9a-f]{64}$/.test(item.dataset_id) &&
        item.start_date === observation.source.start_date &&
        item.instruments.length === observation.universe.length &&
        new Set(
          item.instruments.map(
            (asset) => `${asset.instrument_type}:${asset.symbol}`,
          ),
        ).size === observation.universe.length &&
        item.instruments.every((asset) =>
          observation.universe.some(
            (target) =>
              target.symbol === asset.symbol &&
              target.instrument_type === asset.instrument_type,
          ),
        ),
    ) ?? [];
  const selected = matching.find((item) => item.dataset_id === datasetId);
  const paused = observation.lifecycle === 'paused';
  return (
    <div className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-4">
      <p className="text-sm font-semibold">
        {paused ? labels.paused : labels.active} · {observation.id.slice(0, 8)}
      </p>
      <p className="app-muted text-xs">
        {labels.started} · {formatTimestamp(observation.started_at)}
      </p>
      <p className="app-muted text-xs leading-5">
        {labels.horizon}: {observation.policy.horizon_sessions} ·{' '}
        {labels.symbolCap}:{' '}
        {formatPercent(Number(observation.policy.max_symbol_weight))} ·{' '}
        {labels.grossCap}:{' '}
        {formatPercent(Number(observation.policy.max_gross_weight))}
      </p>
      {!observation.source.source_code_verified ? (
        <p className="app-muted text-xs leading-5">{labels.sourceUnknown}</p>
      ) : null}
      {!observation.source.source_historical_pit_verified ? (
        <p className="app-muted text-xs leading-5">{labels.pitUnknown}</p>
      ) : null}
      {observation.last_blocker &&
      !(
        observation.last_blocker.code === 'observation_health_rule_paused' &&
        observation.health_decision?.action === 'pause_observation'
      ) ? (
        <p role="status" className="text-xs leading-5">
          {observationError(observation.last_blocker.code, locale)}
        </p>
      ) : null}
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid min-w-0 flex-1 basis-64 gap-2 text-xs">
          {labels.dataset}
          <select
            className={fieldClass}
            value={selected?.dataset_id ?? ''}
            disabled={busy || datasets.isLoading}
            onChange={(event) => setDatasetId(event.target.value)}
          >
            <option value="">{labels.choose}</option>
            {matching.map((item) => (
              <option key={item.dataset_id} value={item.dataset_id}>
                {item.start_date} → {item.end_date} ·{' '}
                {item.dataset_id.slice(7, 17)}
              </option>
            ))}
          </select>
        </label>
        <button
          className={buttonClass}
          type="button"
          disabled={busy || datasets.isFetching}
          onClick={() => void datasets.refetch()}
        >
          {labels.refresh}
        </button>
      </div>
      <p className="app-muted text-xs leading-5">{labels.datasetHint}</p>
      {datasets.isError ? (
        <p role="alert" className="text-xs">
          {labels.datasetFailed}
        </p>
      ) : !datasets.isLoading && !matching.length ? (
        <p className="app-muted text-xs">{labels.noDatasets}</p>
      ) : null}
      {selected ? (
        <p
          className="break-all font-mono text-xs"
          data-testid="observation-dataset-id"
        >
          {selected.dataset_id}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          className={buttonClass}
          type="button"
          disabled={busy || !selected}
          onClick={() => onCommand('advance', selected?.dataset_id)}
        >
          {busy ? labels.busy : paused ? labels.measure : labels.advance}
        </button>
        <button
          className={buttonClass}
          type="button"
          disabled={busy || paused}
          onClick={() => onCommand('pause')}
        >
          {labels.pause}
        </button>
      </div>
      <p className="app-muted text-xs leading-5">{labels.pauseDetail}</p>
      <ObservationAutomationControls
        observation={observation}
        busy={busy}
        readBusy={readBusy}
        readFailed={readFailed}
        onRefresh={onRefresh}
      />
      <ResearchObservationHealth observation={observation} />
      <ResearchObservationHistory observation={observation} />
      <details className="min-w-0 text-xs">
        <summary className="cursor-pointer text-[var(--app-text-secondary)]">
          {labels.sourceDataset}
        </summary>
        <p className="mt-2 break-all font-mono">
          {observation.source.dataset_id}
        </p>
      </details>
      <ResearchPaperBookPanel observation={observation} busy={busy} />
    </div>
  );
}
