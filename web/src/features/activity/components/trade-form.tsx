import { useState } from "react";
import { useForm } from "react-hook-form";

import { useCopy } from "../../../app/copy";

export type TradeFormValues = {
  occurred_at: string;
  symbol: string;
  asset_class: string;
  direction: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  fee: number;
  note: string;
};

export function TradeForm({
  onSubmit,
  pending = false,
}: {
  onSubmit: (values: TradeFormValues) => Promise<void>;
  pending?: boolean;
}) {
  const copy = useCopy();
  const common = copy.common;
  const labels = copy.activity.forms.trade;
  const [submitError, setSubmitError] = useState<string | null>(null);
  const createDefaultValues = (): TradeFormValues => ({
    occurred_at: new Date().toISOString().slice(0, 16),
    asset_class: "stock",
    direction: "buy",
    quantity: null,
    unit_price: null,
    amount: null,
    fee: 0,
    note: "",
    symbol: "",
  });

  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm<TradeFormValues>({
    defaultValues: createDefaultValues(),
  });
  const assetClass = watch("asset_class");
  const direction = watch("direction");
  const isFundBuy = assetClass.trim().toLowerCase() === "fund" && direction === "buy";

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
        aria-label="Occurred At"
        type="datetime-local"
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
        {...register("occurred_at", { required: common.required })}
      />
      {errors.occurred_at ? <FieldError message={errors.occurred_at.message} /> : null}
      <input
        aria-label="Symbol"
        placeholder={labels.symbolPlaceholder}
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
        {...register("symbol", { required: common.required })}
      />
      {errors.symbol ? <FieldError message={errors.symbol.message} /> : null}
      <div className="grid gap-3 md:grid-cols-2">
        <select
          aria-label="Direction"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("direction", { required: common.required })}
        >
          <option value="buy">{labels.buy}</option>
          <option value="sell">{labels.sell}</option>
        </select>
        <input
          aria-label="Asset Class"
          defaultValue="stock"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("asset_class", { required: common.required })}
        />
      </div>
      {errors.asset_class ? <FieldError message={errors.asset_class.message} /> : null}
      {isFundBuy ? (
        <>
          <input
            aria-label="Subscription Amount"
            type="number"
            step="any"
            placeholder={labels.amountPlaceholder}
            className="app-field w-full rounded-xl px-3 py-2 text-sm"
            {...register("amount", {
              valueAsNumber: true,
              validate: (value) =>
                typeof value === "number" && value > 0
                  ? true
                  : labels.amountRequired,
            })}
          />
          {errors.amount ? <FieldError message={errors.amount.message} /> : null}
          <div className="app-muted text-xs">{labels.fundAmountHelp}</div>
        </>
      ) : null}
      <div className="grid gap-3 md:grid-cols-3">
        <input
          aria-label="Quantity"
          type="number"
          step="any"
          placeholder={labels.quantityPlaceholder}
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("quantity", {
            valueAsNumber: true,
            validate: (value) =>
              isFundBuy ||
              (typeof value === "number" && value > 0) ||
              common.mustBePositive,
          })}
        />
        <input
          aria-label="Unit Price"
          type="number"
          step="any"
          placeholder={labels.pricePlaceholder}
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("unit_price", {
            valueAsNumber: true,
            validate: (value) =>
              isFundBuy ||
              (typeof value === "number" && value > 0) ||
              common.mustBePositive,
          })}
        />
        <input
          aria-label="Fee"
          type="number"
          step="any"
          className="app-field rounded-xl px-3 py-2 text-sm"
          {...register("fee", { valueAsNumber: true })}
        />
      </div>
      {errors.quantity ? <FieldError message={errors.quantity.message} /> : null}
      {errors.unit_price ? <FieldError message={errors.unit_price.message} /> : null}
      <input
        aria-label="Trade Note"
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
  if (!message) {
    return null;
  }
  return <div className="app-error-text text-sm">{message}</div>;
}
