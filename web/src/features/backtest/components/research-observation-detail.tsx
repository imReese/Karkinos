import { useState } from 'react';
import { formatPercent, formatTimestamp } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { usePreferences } from '../../../shared/preferences/context';
import { observationCopy, observationError } from '../copy-observations';
import { observationHealthCopy } from '../copy-observation-health';
import {
  automationBlocker,
  observationAutomationCopy,
} from '../copy-observation-automation';
import { usePublishedDatasets } from '../dataset-api';
import type { ResearchObservation } from '../observation-contracts';
import { ResearchObservationHistory } from './research-observation-history';
import { ResearchObservationHealth } from './research-observation-health';
import { ObservationAutomationControls } from './observation-automation';
import { ResearchPaperBookPanel } from './research-paper-book-panel';

const fieldClass = 'app-field min-h-11 w-full min-w-0 px-3 py-2';
const buttonClass =
  'app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-4 py-2 text-xs disabled:opacity-50';

export function ResearchObservationDetail({
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
  const healthLabels = observationHealthCopy[locale];
  const datasets = usePublishedDatasets(true);
  const [datasetId, setDatasetId] = useState('');
  const matching =
    datasets.data?.datasets.filter(
      (item) =>
        item.cross_source_verified === true &&
        /^sha256:[0-9a-f]{64}$/.test(item.dataset_id) &&
        item.start_date ===
          (observation.source.forward_input?.start_date ??
            observation.source.start_date) &&
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
      {observation.last_blocker &&
      !(
        observation.last_blocker.code === 'observation_health_rule_paused' &&
        observation.health_decision?.action === 'pause_observation'
      ) ? (
        <p role="status" className="text-xs leading-5">
          {observationError(observation.last_blocker.code, locale)}
        </p>
      ) : null}
      {observation.health_decision ? (
        <div
          role="status"
          data-testid="observation-health-summary"
          className="space-y-1 border-l-2 border-[var(--app-divider)] pl-4 text-xs leading-5"
        >
          <p className="font-semibold">
            {healthLabels.title}:{' '}
            {healthLabels[observation.health_decision.status]}
          </p>
          {observation.health_decision.action === 'pause_observation' ? (
            <p>
              {observation.lifecycle === 'paused'
                ? healthLabels.paused
                : healthLabels.pauseDecision}
            </p>
          ) : null}
        </div>
      ) : null}
      <ObservationAutomationSummary
        observation={observation}
        readFailed={readFailed}
      />
      <ResearchPaperBookPanel
        observation={observation}
        busy={busy}
        defaultOpen
      />
      {!observation.source.source_code_verified ? (
        <p className="app-muted text-xs leading-5">{labels.sourceUnknown}</p>
      ) : null}
      {!observation.source.source_historical_pit_verified ? (
        <p className="app-muted text-xs leading-5">{labels.pitUnknown}</p>
      ) : null}
      <details
        className="border-t border-[var(--app-divider)] py-4"
        data-testid="observation-health-disclosure"
      >
        <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
          {healthLabels.title}
        </summary>
        <ResearchObservationHealth observation={observation} />
      </details>
      <details
        className="border-t border-[var(--app-divider)] py-4"
        data-testid="observation-history-disclosure"
      >
        <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
          {locale === 'zh'
            ? '目标发布与价格响应记录'
            : 'Target publications and price response history'}
        </summary>
        <ResearchObservationHistory observation={observation} />
      </details>
      <details
        className="border-t border-[var(--app-divider)] py-4"
        data-testid="observation-maintenance-disclosure"
      >
        <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
          {locale === 'zh'
            ? '续接数据、目标发布与自动运行'
            : 'Continue data, publish targets and manage automation'}
        </summary>
        <div className="mt-4 space-y-4">
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
        </div>
      </details>
      <details
        className="min-w-0 border-t border-[var(--app-divider)] py-4 text-xs"
        data-testid="observation-source-disclosure"
      >
        <summary className="min-h-11 cursor-pointer py-2 font-semibold">
          {locale === 'zh' ? '观察范围与来源' : 'Observation scope and source'}
        </summary>
        <div className="mt-4 space-y-2">
          <p className="app-muted text-xs leading-5">
            {labels.horizon}: {observation.policy.horizon_sessions} ·{' '}
            {labels.symbolCap}:{' '}
            {formatPercent(Number(observation.policy.max_symbol_weight))} ·{' '}
            {labels.grossCap}:{' '}
            {formatPercent(Number(observation.policy.max_gross_weight))}
          </p>
          {observation.source.forward_input ? (
            <p className="app-muted break-all text-xs leading-5">
              {locale === 'zh'
                ? '本次观察的预热区间'
                : 'Warmup history for this observation'}
              : {observation.source.forward_input.start_date} →{' '}
              {observation.source.forward_input.end_date}
              {' · '}
              {observation.source.forward_input.dataset_id}
            </p>
          ) : null}
          <details className="min-w-0 text-xs">
            <summary className="cursor-pointer text-[var(--app-text-secondary)]">
              {labels.sourceDataset}
            </summary>
            <p className="mt-2 break-all font-mono">
              {observation.source.dataset_id}
            </p>
          </details>
        </div>
      </details>
    </div>
  );
}

function ObservationAutomationSummary({
  observation,
  readFailed,
}: {
  observation: ResearchObservation;
  readFailed: boolean;
}) {
  const { locale } = usePreferences();
  const automationLabels = observationAutomationCopy[locale];
  const automation =
    observation.automation?.observation_id === observation.id
      ? observation.automation
      : null;
  if (
    !automation ||
    !(
      readFailed ||
      automation.status === 'blocked' ||
      automation.last_blocker ||
      automation.dataset_preparation?.status === 'blocked' ||
      automation.dataset_preparation?.last_blocker ||
      automation.paper_settlement?.status === 'blocked' ||
      automation.paper_settlement?.last_blocker
    )
  )
    return null;
  return (
    <section
      data-testid="observation-automation-summary"
      className="min-w-0 space-y-2 border-y border-[var(--app-divider)] py-4 text-xs"
    >
      {readFailed ? <p role="alert">{automationLabels.readFailed}</p> : null}
      <dl className="grid min-w-0 gap-4 sm:grid-cols-3">
        {[
          {
            label: automationLabels.title,
            status: automationLabels[automation.status],
            blocker: automation.last_blocker,
          },
          {
            label:
              locale === 'zh'
                ? '核验数据自动准备'
                : 'Verified data preparation',
            status: automation.dataset_preparation
              ? formatPublicStatus(
                  automation.dataset_preparation.status,
                  locale,
                )
              : '—',
            blocker: automation.dataset_preparation?.last_blocker,
          },
          {
            label:
              locale === 'zh' ? 'Paper 自动结算' : 'Automatic paper settlement',
            status: automation.paper_settlement
              ? formatPublicStatus(automation.paper_settlement.status, locale)
              : '—',
            blocker: automation.paper_settlement?.last_blocker,
          },
        ].map((item) => (
          <div className="min-w-0" key={item.label}>
            <dt className="text-[var(--app-text-secondary)]">{item.label}</dt>
            <dd className="mt-1 font-semibold" role="status">
              {item.status}
            </dd>
            {item.blocker ? (
              <dd
                className="mt-2 break-words leading-5"
                title={item.blocker.code}
              >
                {automationBlocker(item.blocker.code, locale)}
              </dd>
            ) : null}
          </div>
        ))}
      </dl>
    </section>
  );
}
