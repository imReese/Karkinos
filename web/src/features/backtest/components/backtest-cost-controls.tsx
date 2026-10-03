import { usePreferences } from '../../../shared/preferences/context';
import { backtestCostCopy } from '../copy-costs';
import {
  backtestCostFields,
  useBacktestCostInputs,
} from './backtest-cost-inputs';

export function BacktestCostControls({
  inputs,
  disabled,
}: {
  inputs: ReturnType<typeof useBacktestCostInputs>;
  disabled?: boolean;
}) {
  const { locale } = usePreferences();
  const labels = backtestCostCopy[locale];
  return (
    <details className="min-w-0 border-y border-[var(--app-divider)] py-3">
      <summary className="cursor-pointer text-sm font-semibold">
        {labels.settings}
      </summary>
      <p className="app-muted mt-2 text-xs leading-5">{labels.shared}</p>
      <label className="mt-3 grid gap-2 text-sm font-medium">
        {labels.mode}
        <select
          className="app-field min-h-11 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
          value={inputs.custom ? 'custom' : 'default'}
          disabled={disabled}
          onChange={(event) =>
            inputs.setCustom(event.target.value === 'custom')
          }
        >
          <option value="default">{labels.default}</option>
          <option value="custom">{labels.custom}</option>
        </select>
      </label>
      {inputs.custom ? (
        <>
          <p className="app-muted mt-2 text-xs leading-5">{labels.blank}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {backtestCostFields.map((field) => (
              <label
                key={field}
                className="grid min-w-0 gap-2 text-sm font-medium"
              >
                {labels.fields[field]}
                <input
                  className="app-field min-h-11 w-full min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm tabular-nums"
                  type="number"
                  min="0"
                  step="any"
                  max={field.endsWith('_rate') ? 10000 : undefined}
                  value={inputs.values[field] ?? ''}
                  disabled={disabled}
                  placeholder={labels.inherited}
                  onChange={(event) =>
                    inputs.setValues((current) => ({
                      ...current,
                      [field]: event.target.value,
                    }))
                  }
                />
              </label>
            ))}
          </div>
          {!inputs.valid ? (
            <p
              role="alert"
              className="mt-2 text-xs text-[var(--app-danger-text)]"
            >
              {labels.invalid}
            </p>
          ) : null}
          <p className="app-muted mt-2 text-xs leading-5">{labels.boundary}</p>
        </>
      ) : (
        <p className="app-muted mt-2 text-xs leading-5">
          {labels.defaultDetail}
        </p>
      )}
    </details>
  );
}
