import { useEffect, useState } from 'react';

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
    <section
      className="app-panel min-w-0 rounded-[22px] p-3 sm:p-4"
      data-layout="compact-control"
      data-testid="kill-switch-panel"
    >
      <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.78fr)] lg:items-center">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.kicker}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold">{labels.title}</h2>
            <KillSwitchBadge enabled={enabled} snapshot={snapshot} />
          </div>
          <p className="app-muted mt-1.5 max-w-2xl text-sm leading-5">
            {labels.subtitle}
          </p>
        </div>

        <div className="grid min-w-0 gap-2">
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
          <div className="app-muted text-xs leading-5">
            {labels.updatedAt}:{' '}
            {formatTimestamp(snapshot?.updated_at) ?? labels.neverUpdated}
          </div>
        </div>
      </div>
    </section>
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
      className={`rounded-full px-3 py-1 text-xs font-semibold ${
        enabled
          ? 'bg-red-500/15 text-red-300 ring-1 ring-red-500/35'
          : 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/35'
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
