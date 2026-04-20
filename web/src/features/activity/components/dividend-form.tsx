import { useState } from "react";
import { useForm } from "react-hook-form";

import { useCopy } from "../../../app/copy";

export type DividendFormValues = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  amount: number;
  note: string;
};

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
  const [submitError, setSubmitError] = useState<string | null>(null);
  const createDefaultValues = (): DividendFormValues => ({
    occurred_at: new Date().toISOString().slice(0, 16),
    symbol: "",
    asset_class: "stock",
    amount: 0,
    note: "",
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
      className="app-panel space-y-3 rounded-2xl p-5"
    >
      <div className="app-kicker text-xs uppercase tracking-[0.18em]">{labels.title}</div>
      <input
        aria-label="Dividend Occurred At"
        type="datetime-local"
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
        {...register("occurred_at", { required: common.required })}
      />
      {errors.occurred_at ? <FieldError message={errors.occurred_at.message} /> : null}
      <input
        aria-label="Dividend Symbol"
        placeholder={labels.symbolPlaceholder}
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
        {...register("symbol", { required: common.required })}
      />
      {errors.symbol ? <FieldError message={errors.symbol.message} /> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <input
          aria-label="Dividend Asset Class"
          defaultValue="stock"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("asset_class", { required: common.required })}
        />
        <input
          aria-label="Dividend Amount"
          type="number"
          step="any"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("amount", {
            required: common.required,
            valueAsNumber: true,
            min: { value: 0.000001, message: common.mustBePositive },
          })}
        />
      </div>
      {errors.amount ? <FieldError message={errors.amount.message} /> : null}
      <input
        aria-label="Dividend Note"
        placeholder={labels.notePlaceholder}
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
        {...register("note")}
      />
      {submitError ? <FieldError message={submitError} /> : null}
      <button
        type="submit"
        disabled={pending}
        className="app-button-primary rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        {pending ? labels.saving : labels.submit}
      </button>
    </form>
  );
}

function FieldError({ message }: { message?: string }) {
  return message ? <div className="text-sm text-red-400">{message}</div> : null;
}
