import { useState } from 'react';
import { useForm } from 'react-hook-form';

import { useCopy } from '../../../app/copy';
import { toDatetimeLocalInputValue } from '../datetime-local';

export type DividendFormValues = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  amount: number;
  note: string;
};

function assetClassOptions(copy: ReturnType<typeof useCopy>) {
  return [
    { value: 'stock', label: copy.common.assetClassStock },
    { value: 'etf', label: copy.common.assetClassEtf },
    { value: 'fund', label: copy.common.assetClassFund },
    { value: 'gold', label: copy.common.assetClassGold },
    { value: 'bond', label: copy.common.assetClassBond },
  ];
}

export function DividendForm({
  onSubmit,
  pending = false,
}: {
  onSubmit: (values: DividendFormValues) => Promise<void>;
  pending?: boolean;
}) {
  const copy = useCopy();
  const common = copy.common;
  const labels = copy.activity.forms.dividend;
  const assetOptions = assetClassOptions(copy);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const createDefaultValues = (): DividendFormValues => ({
    occurred_at: toDatetimeLocalInputValue(),
    symbol: '',
    asset_class: 'stock',
    amount: 0,
    note: '',
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<DividendFormValues>({
    defaultValues: createDefaultValues(),
  });

  return (
    <form
      onSubmit={handleSubmit(async (values) => {
        setSubmitError(null);
        try {
          await onSubmit(values);
          reset(createDefaultValues());
        } catch (error) {
          setSubmitError(
            error instanceof Error ? error.message : labels.genericSubmitError,
          );
        }
      })}
      className="min-w-0 space-y-3"
    >
      <input
        aria-label={labels.occurredAtLabel}
        type="datetime-local"
        className="app-field min-h-10 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
        {...register('occurred_at', { required: common.required })}
      />
      {errors.occurred_at ? (
        <FieldError message={errors.occurred_at.message} />
      ) : null}
      <input
        aria-label={labels.symbolLabel}
        placeholder={labels.symbolPlaceholder}
        className="app-field min-h-10 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
        {...register('symbol', { required: common.required })}
      />
      {errors.symbol ? <FieldError message={errors.symbol.message} /> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <select
          aria-label={labels.assetClassLabel}
          className="app-field min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          {...register('asset_class', { required: common.required })}
        >
          {assetOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <input
          aria-label={labels.amountLabel}
          type="number"
          step="any"
          className="app-field min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          {...register('amount', {
            required: common.required,
            valueAsNumber: true,
            min: { value: 0.000001, message: common.mustBePositive },
          })}
        />
      </div>
      {errors.amount ? <FieldError message={errors.amount.message} /> : null}
      <input
        aria-label={labels.noteLabel}
        placeholder={labels.notePlaceholder}
        className="app-field min-h-10 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
        {...register('note')}
      />
      {submitError ? <FieldError message={submitError} /> : null}
      <button
        type="submit"
        disabled={pending}
        className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 py-2 text-sm font-semibold disabled:opacity-50"
      >
        {pending ? labels.saving : labels.submit}
      </button>
    </form>
  );
}

function FieldError({ message }: { message?: string }) {
  return message ? (
    <div className="app-error-text text-sm">{message}</div>
  ) : null;
}
