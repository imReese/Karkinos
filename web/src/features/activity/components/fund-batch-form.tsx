import { useState } from "react";

import { useCopy } from "../../../app/copy";

export type FundBatchOrder = {
  symbol: string;
  display_name: string;
  amount: number | null;
};

export type FundBatchFormValues = {
  occurred_at: string;
  note: string;
  orders: FundBatchOrder[];
};

const DEFAULT_FUNDS: Omit<FundBatchOrder, "amount">[] = [
  { symbol: "018125", display_name: "永赢先进制造智选混合C" },
  { symbol: "026539", display_name: "融通科技臻选混合C" },
  { symbol: "012710", display_name: "华夏核心成长混合C" },
];

function defaultValues(): FundBatchFormValues {
  return {
    occurred_at: new Date().toISOString().slice(0, 16),
    note: "",
    orders: DEFAULT_FUNDS.map((fund) => ({ ...fund, amount: null })),
  };
}

export function FundBatchForm({
  onSubmit,
  pending = false,
}: {
  onSubmit: (values: FundBatchFormValues) => Promise<void>;
  pending?: boolean;
}) {
  const copy = useCopy();
  const labels = copy.activity.forms.fundBatch;
  const [values, setValues] = useState(defaultValues);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const updateOrderAmount = (index: number, amount: number | null) => {
    setValues((current) => ({
      ...current,
      orders: current.orders.map((order, orderIndex) =>
        orderIndex === index ? { ...order, amount } : order,
      ),
    }));
  };

  const activeOrders = values.orders.filter(
    (order) => typeof order.amount === "number" && Number.isFinite(order.amount) && order.amount > 0,
  );

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        setSubmitError(null);
        if (activeOrders.length === 0) {
          setSubmitError(labels.emptyError);
          return;
        }
        try {
          await onSubmit({ ...values, orders: activeOrders });
          setValues(defaultValues());
        } catch (error) {
          setSubmitError(
            error instanceof Error ? error.message : labels.genericSubmitError,
          );
        }
      }}
      className="app-panel space-y-4 rounded-2xl p-5"
    >
      <div>
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {labels.title}
        </div>
        <p className="app-muted mt-2 text-xs leading-5">{labels.helper}</p>
      </div>
      <input
        aria-label="Batch Occurred At"
        type="datetime-local"
        value={values.occurred_at}
        onChange={(event) =>
          setValues((current) => ({ ...current, occurred_at: event.target.value }))
        }
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
      />
      <div className="space-y-2">
        {values.orders.map((order, index) => (
          <div
            key={order.symbol}
            className="grid gap-2 rounded-xl border border-[var(--app-border)] bg-[var(--app-surface-1)] p-3 sm:grid-cols-[minmax(0,1fr)_150px]"
          >
            <div>
              <div className="text-sm font-semibold">{order.display_name}</div>
              <div className="app-muted mt-1 text-xs">{order.symbol}</div>
            </div>
            <input
              aria-label={`${order.symbol} Amount`}
              type="number"
              step="any"
              min="0"
              placeholder={labels.amountPlaceholder}
              value={order.amount ?? ""}
              onChange={(event) => {
                const nextAmount = event.target.value === "" ? null : Number(event.target.value);
                updateOrderAmount(index, nextAmount);
              }}
              className="app-field rounded-xl px-3 py-2 text-sm"
            />
          </div>
        ))}
      </div>
      <input
        aria-label="Batch Fund Note"
        placeholder={labels.notePlaceholder}
        value={values.note}
        onChange={(event) =>
          setValues((current) => ({ ...current, note: event.target.value }))
        }
        className="app-field w-full rounded-xl px-3 py-2 text-sm"
      />
      {submitError ? <div className="app-error-text text-sm">{submitError}</div> : null}
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
