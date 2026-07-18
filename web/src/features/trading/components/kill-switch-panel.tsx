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

  return (
    <div
      className="min-w-0"
      data-layout="compact-control"
      data-testid="kill-switch-panel"
    >
      <ControlledActionZone
        title={labels.title}
        description={labels.subtitle}
        evidence={
          <span className="flex flex-wrap items-center gap-2">
            <KillSwitchBadge enabled={enabled} snapshot={snapshot} />
            <span>
              {labels.updatedAt}:{' '}
              {formatTimestamp(snapshot?.updated_at) ?? labels.neverUpdated}
            </span>
          </span>
        }
      >
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
                enabled
                  ? labels.currentReasonPlaceholder
                  : labels.reasonPlaceholder
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
      </ControlledActionZone>
    </div>
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
          : 'bg-[var(--app-success-bg)] text-[var(--app-success-text)] ring-1 ring-[var(--app-success-border)]'
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
