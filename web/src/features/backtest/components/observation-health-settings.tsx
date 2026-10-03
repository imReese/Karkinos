import { usePreferences } from '../../../shared/preferences/context';
import { observationHealthCopy } from '../copy-observation-health';
import type { ObservationHealthPolicy } from '../observation-contracts';

export type ObservationHealthDraft = {
  enabled: boolean;
  mode: ObservationHealthPolicy['mode'];
  window: string;
  minimum: string;
  threshold: string;
};

export function configuredHealthPolicy(
  draft: ObservationHealthDraft,
): ObservationHealthPolicy | null | undefined {
  if (!draft.enabled) return null;
  const window = Number(draft.window);
  const minimum = Number(draft.minimum);
  const threshold = draft.threshold.trim();
  if (
    !Number.isSafeInteger(window) ||
    !Number.isSafeInteger(minimum) ||
    minimum < 1 ||
    minimum > window ||
    !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(threshold) ||
    !Number.isFinite(Number(threshold))
  )
    return undefined;
  return {
    mode: draft.mode,
    window_intervals: window,
    minimum_eligible_intervals: minimum,
    minimum_mean_relative_price_response: threshold,
  };
}

export function ObservationHealthSettings({
  value,
  onChange,
}: {
  value: ObservationHealthDraft;
  onChange: (value: ObservationHealthDraft) => void;
}) {
  const { locale } = usePreferences();
  const labels = observationHealthCopy[locale];
  const fieldClass = 'app-field min-h-11 w-full min-w-0 px-3 py-2';
  return (
    <div className="min-w-0 space-y-3">
      <label className="flex min-h-11 items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(event) =>
            onChange({ ...value, enabled: event.target.checked })
          }
        />
        {labels.enable}
      </label>
      {value.enabled ? (
        <>
          <p className="app-muted text-xs leading-5">{labels.metric}</p>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            <label className="grid min-w-0 gap-2 text-xs">
              {labels.mode}
              <select
                className={fieldClass}
                value={value.mode}
                onChange={(event) =>
                  onChange({
                    ...value,
                    mode: event.target.value as ObservationHealthPolicy['mode'],
                  })
                }
              >
                <option value="observe_only">{labels.observe_only}</option>
                <option value="pause_on_breach">
                  {labels.pause_on_breach}
                </option>
              </select>
            </label>
            <label className="grid min-w-0 gap-2 text-xs">
              {labels.window}
              <input
                className={fieldClass}
                type="number"
                min="1"
                step="1"
                value={value.window}
                onChange={(event) =>
                  onChange({ ...value, window: event.target.value })
                }
              />
            </label>
            <label className="grid min-w-0 gap-2 text-xs">
              {labels.minimum}
              <input
                className={fieldClass}
                type="number"
                min="1"
                step="1"
                value={value.minimum}
                onChange={(event) =>
                  onChange({ ...value, minimum: event.target.value })
                }
              />
            </label>
            <label className="grid min-w-0 gap-2 text-xs">
              {labels.threshold}
              <input
                className={fieldClass}
                type="text"
                inputMode="decimal"
                value={value.threshold}
                onChange={(event) =>
                  onChange({ ...value, threshold: event.target.value })
                }
              />
            </label>
          </div>
          <p className="app-muted text-xs leading-5">{labels.units}</p>
          <p className="app-muted text-xs leading-5">{labels.frozen}</p>
          {configuredHealthPolicy(value) === undefined ? (
            <p className="text-xs" role="alert">
              {labels.invalid}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
