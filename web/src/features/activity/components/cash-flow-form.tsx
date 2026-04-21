import { useState } from "react";
import { useForm } from "react-hook-form";

import { useCopy } from "../../../app/copy";

export type CashFlowFormValues = {
  occurred_at: string;
  amount: number;
  flow_type: string;
  note: string;
};

export function CashFlowForm({
  onSubmit,
  pending = false,
}: {
  onSubmit: (values: CashFlowFormValues) => Promise<void>;
  pending?: boolean;
}) {
  const copy = useCopy();
  const common = copy.common;
  const labels = copy.activity.forms.cashFlow;
  const [submitError, setSubmitError] = useState<string | null>(null);
  const createDefaultValues = (): CashFlowFormValues => ({
    occurred_at: new Date().toISOString().slice(0, 16),
    amount: 0,
    flow_type: "deposit",
    note: "",
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CashFlowFormValues>({
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
        aria-label="Cash Flow Occurred At"
        type="datetime-local"
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
        {...register("occurred_at", { required: common.required })}
      />
      {errors.occurred_at ? <FieldError message={errors.occurred_at.message} /> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <input
          aria-label="Amount"
          type="number"
          step="any"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("amount", {
            required: common.required,
            valueAsNumber: true,
            min: { value: 0.000001, message: common.mustBePositive },
          })}
        />
        <select
          aria-label="Flow Type"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("flow_type", { required: common.required })}
        >
          <option value="deposit">{labels.deposit}</option>
          <option value="withdrawal">{labels.withdrawal}</option>
        </select>
      </div>
      {errors.amount ? <FieldError message={errors.amount.message} /> : null}
      <input
        aria-label="Cash Flow Note"
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
  return message ? <div className="app-error-text text-sm">{message}</div> : null;
}
