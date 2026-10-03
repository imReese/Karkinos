import { useState } from 'react';

import { formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { useConfigureObservationAutomation } from '../observation-api';
import type { ResearchObservation } from '../observation-contracts';
import {
  automationBlocker,
  observationAutomationCopy,
} from '../copy-observation-automation';

export function ObservationAutomationControls({
  observation,
  busy,
  readBusy,
  readFailed,
  onRefresh,
}: {
  observation: ResearchObservation;
  busy: boolean;
  readBusy: boolean;
  readFailed: boolean;
  onRefresh: () => Promise<boolean>;
}) {
  const { locale } = usePreferences();
  const labels = observationAutomationCopy[locale];
  const mutation = useConfigureObservationAutomation();
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const automation =
    observation.automation?.observation_id === observation.id
      ? observation.automation
      : null;
  const paused = observation.lifecycle === 'paused';
  const blocked = busy || readBusy || refreshing || mutation.isPending;
  const conflict =
    mutation.error?.message.includes('conflict') ||
    mutation.error?.message.includes('409');

  async function refresh() {
    setRefreshing(true);
    try {
      const success = await onRefresh();
      setRefreshFailed(!success);
      if (success) mutation.reset();
    } catch {
      setRefreshFailed(true);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <section
      className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-4 text-xs leading-5"
      aria-label={labels.title}
    >
      <h4 className="text-sm font-semibold">{labels.title}</h4>
      <p className="app-muted">{labels.scope}</p>
      <p className="app-muted">{labels.window}</p>
      <p className="app-muted">{labels.data}</p>
      <p className="app-muted">{labels.separate}</p>
      <p className="font-semibold" role="status">
        {automation ? labels[automation.status] : labels.unknown}
      </p>
      {paused ? <p>{labels.pausedDetail}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button
          className="app-button-secondary min-h-11 px-3 py-2 text-xs disabled:opacity-50"
          disabled={
            blocked ||
            readFailed ||
            !automation ||
            mutation.isError ||
            refreshFailed ||
            (paused && !automation.enabled)
          }
          onClick={() => {
            if (!automation) return;
            mutation.mutate({
              observationId: observation.id,
              sourceResultId: observation.source_backtest_result_id,
              enabled: !automation.enabled,
              expectedGeneration: automation.generation,
            });
          }}
          type="button"
        >
          {mutation.isPending
            ? labels.saving
            : automation?.enabled
              ? labels.disable
              : labels.enable}
        </button>
        <button
          className="app-button-secondary min-h-11 px-3 py-2 text-xs disabled:opacity-50"
          disabled={blocked}
          onClick={() => void refresh()}
          type="button"
        >
          {labels.refresh}
        </button>
      </div>
      {mutation.isError ? (
        <p role="alert">{conflict ? labels.conflict : labels.failed}</p>
      ) : mutation.isSuccess ? (
        <p>{labels.saved}</p>
      ) : null}
      {readFailed || refreshFailed ? (
        <p role="alert">{labels.readFailed}</p>
      ) : null}
      {automation ? (
        <>
          <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
            {[
              [labels.checked, formatTimestamp(automation.last_checked_at)],
              [labels.attempted, formatTimestamp(automation.last_attempt_at)],
              [labels.decision, automation.decision_session ?? '—'],
              [labels.dataset, automation.dataset_id ?? '—'],
            ].map(([label, value]) => (
              <div className="min-w-0" key={label}>
                <dt className="app-muted">{label}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          </dl>
          {automation.last_blocker ? (
            <p>{automationBlocker(automation.last_blocker.code, locale)}</p>
          ) : null}
          {automation.dataset_discovery_complete === false ? (
            <p>{labels.incomplete}</p>
          ) : null}
          {automation.last_blocker ||
          typeof automation.dataset_discovery_complete === 'boolean' ||
          automation.unreadable_candidate_dataset_ids?.length ? (
            <details className="min-w-0">
              <summary className="cursor-pointer text-[var(--app-text-secondary)]">
                {labels.diagnostics}
              </summary>
              <div className="mt-2 space-y-2">
                {automation.last_blocker ? (
                  <p className="break-all">
                    {labels.blocker}: {automation.last_blocker.code}
                  </p>
                ) : null}
                {automation.dataset_discovery_complete === true ? (
                  <p>{labels.complete}</p>
                ) : null}
                {automation.unreadable_candidate_dataset_ids?.map((id) => (
                  <p className="break-all font-mono" key={id}>
                    {id}
                  </p>
                ))}
              </div>
            </details>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
