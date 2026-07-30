import { useEffect, useState } from 'react';

import { ControlledActionZone } from '../../../app/components/workbench';
import { useCopy } from '../../../app/copy';
import {
  useKillSwitchQuery,
  useSetKillSwitchMutation,
  type KillSwitchSnapshot,
} from '../api';

export function KillSwitchPanel() {
  const copy = useCopy();
  const labels = copy.trading.killSwitch;
  const pageLabels = copy.trading.page;
  const killSwitch = useKillSwitchQuery();
  const setKillSwitch = useSetKillSwitchMutation();
  const [reason, setReason] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const snapshot = killSwitch.data;
  const enabled = snapshot?.kill_switch_enabled ?? false;

  useEffect(() => {
    if (snapshot?.reason) {
      setReason(snapshot.reason);
    }
  }, [snapshot?.reason]);

  const updateKillSwitch = async (nextEnabled: boolean) => {
    const trimmedReason = reason.trim();
    if (nextEnabled && trimmedReason.length === 0) {
      setFormError(labels.reasonRequired);
      return;
    }

    setFormError(null);
    await setKillSwitch.mutateAsync({
      enabled: nextEnabled,
      reason: trimmedReason,
    });
  };

  const evidence = (
    <span className="flex flex-wrap items-center gap-2">
      <KillSwitchBadge enabled={enabled} snapshot={snapshot} />
      <span>
        {labels.updatedAt}:{' '}
        {formatTimestamp(snapshot?.updated_at) ?? labels.neverUpdated}
      </span>
    </span>
  );
  const controls = (
    <div className="grid w-full min-w-[280px] gap-2 sm:w-[360px]">
      <label className="grid min-w-0 gap-1.5">
        <span className="text-sm font-medium">{labels.reason}</span>
        <input
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
            if (formError) {
              setFormError(null);
            }
          }}
          placeholder={
            enabled ? labels.currentReasonPlaceholder : labels.reasonPlaceholder
          }
          className="app-field h-10 min-w-0 rounded-xl px-3 text-sm"
          aria-label={labels.reason}
        />
      </label>
      {formError ? (
        <div className="app-error-text text-sm">{formError}</div>
      ) : null}
      {setKillSwitch.isError ? (
        <div className="app-error-text text-sm">
          {getErrorMessage(setKillSwitch.error)}
        </div>
      ) : null}
      {killSwitch.isError ? (
        <div className="app-error-text text-sm">{labels.loadFailed}</div>
      ) : null}
      <div className="grid min-w-0 gap-2 sm:grid-cols-2">
        <button
          type="button"
          disabled={setKillSwitch.isPending || enabled}
          onClick={() => void updateKillSwitch(true)}
          className="app-button-danger min-h-10 rounded-xl px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-45"
        >
          {setKillSwitch.isPending && !enabled
            ? labels.submitting
            : labels.enable}
        </button>
        <button
          type="button"
          disabled={setKillSwitch.isPending || !enabled}
          onClick={() => void updateKillSwitch(false)}
          className="app-button-secondary min-h-10 rounded-xl px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-45"
        >
          {setKillSwitch.isPending && enabled
            ? labels.submitting
            : labels.disable}
        </button>
      </div>
    </div>
  );
  const controlledZone = (
    <ControlledActionZone
      title={enabled || killSwitch.isError ? labels.title : labels.enable}
      description={labels.subtitle}
      evidence={evidence}
    >
      {controls}
    </ControlledActionZone>
  );

  if (enabled || killSwitch.isError) {
    return (
      <div
        className="min-w-0"
        data-kill-switch-state={enabled ? 'active' : 'unavailable'}
        data-layout="compact-control"
        data-testid="kill-switch-panel"
      >
        {controlledZone}
      </div>
    );
  }

  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-kill-switch-state={snapshot ? 'inactive' : 'checking'}
      data-layout="compact-control"
      data-testid="kill-switch-panel"
    >
      <summary className="flex min-h-14 cursor-pointer list-none flex-col items-start justify-between gap-2 px-1 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:flex-row sm:items-center sm:gap-4 sm:px-3 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-[var(--app-text)]">
            {labels.title}
          </span>
          <span className="mt-0.5 hidden text-xs leading-5 text-[var(--app-text-secondary)] sm:block">
            {labels.subtitle}
          </span>
        </span>
        <span className="flex w-full shrink-0 items-center justify-between gap-2 text-right sm:w-auto sm:flex-col sm:items-end sm:gap-1">
          <span className="app-type-micro flex flex-wrap items-center justify-end gap-2 font-mono text-[var(--app-text-tertiary)]">
            <KillSwitchBadge enabled={enabled} snapshot={snapshot} />
            <span>
              {formatTimestamp(snapshot?.updated_at) ?? labels.neverUpdated}
            </span>
          </span>
          <span className="text-xs font-semibold text-[var(--app-text-secondary)]">
            {pageLabels.expandOnDemand}
          </span>
        </span>
      </summary>
      <div className="py-3">{controlledZone}</div>
    </details>
  );
}

function KillSwitchBadge({
  enabled,
  snapshot,
}: {
  enabled: boolean;
  snapshot?: KillSwitchSnapshot;
}) {
  const copy = useCopy();
  const labels = copy.trading.killSwitch;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${
        enabled
          ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger-text)] ring-1 ring-[var(--app-danger-border)]'
          : 'border border-[var(--app-divider)] bg-transparent text-[var(--app-text-secondary)]'
      }`}
    >
      {snapshot ? (enabled ? labels.enabled : labels.disabled) : labels.loading}
    </span>
  );
}

function formatTimestamp(value?: string | null) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
