import { useEffect, useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import { toDatetimeLocalInputValue } from '../datetime-local';

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

export type FundBatchCandidate = Omit<FundBatchOrder, 'amount'>;

const EMPTY_CANDIDATES: FundBatchCandidate[] = [];

function defaultValues(candidates: FundBatchCandidate[]): FundBatchFormValues {
  return {
    occurred_at: toDatetimeLocalInputValue(),
    note: '',
    orders: candidates.map((fund) => ({ ...fund, amount: null })),
  };
}

export function FundBatchForm({
  candidates = EMPTY_CANDIDATES,
  loadingCandidates = false,
  onSubmit,
  pending = false,
}: {
  candidates?: FundBatchCandidate[];
  loadingCandidates?: boolean;
  onSubmit: (values: FundBatchFormValues) => Promise<void>;
  pending?: boolean;
}) {
  const copy = useCopy();
  const labels = copy.activity.forms.fundBatch;
  const candidateKey = useMemo(
    () =>
      candidates.map((fund) => `${fund.symbol}:${fund.display_name}`).join('|'),
    [candidates],
  );
  const [values, setValues] = useState(() => defaultValues(candidates));
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    setValues((current) => ({
      ...current,
      orders: candidates.map((fund) => {
        const existing = current.orders.find(
          (order) => order.symbol === fund.symbol,
        );
        return { ...fund, amount: existing?.amount ?? null };
      }),
    }));
  }, [candidateKey, candidates]);

  const updateOrderAmount = (index: number, amount: number | null) => {
    setValues((current) => ({
      ...current,
      orders: current.orders.map((order, orderIndex) =>
        orderIndex === index ? { ...order, amount } : order,
      ),
    }));
  };

  const activeOrders = values.orders.filter(
    (order) =>
      typeof order.amount === 'number' &&
      Number.isFinite(order.amount) &&
      order.amount > 0,
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
          setValues(defaultValues(candidates));
        } catch (error) {
          setSubmitError(
            error instanceof Error ? error.message : labels.genericSubmitError,
          );
        }
      }}
      className="min-w-0 max-w-full space-y-4"
    >
      <div className="min-w-0">
        <p className="app-muted break-words text-xs leading-5">
          {labels.helper}
        </p>
      </div>
      <input
        aria-label={labels.occurredAtLabel}
        type="datetime-local"
        value={values.occurred_at}
        onChange={(event) =>
          setValues((current) => ({
            ...current,
            occurred_at: event.target.value,
          }))
        }
        className="app-field min-h-10 min-w-0 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
      />
      {loadingCandidates ? (
        <div className="app-muted border-y border-[var(--app-divider)] py-3 text-sm">
          {labels.loadingCandidates}
        </div>
      ) : values.orders.length === 0 ? (
        <div className="app-muted border-y border-[var(--app-divider)] py-3 text-sm">
          {labels.noCandidates}
        </div>
      ) : (
        <div className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {values.orders.map((order, index) => (
            <div
              key={order.symbol}
              className="grid min-w-0 gap-2 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(130px,150px)] sm:items-center"
            >
              <div className="min-w-0">
                <div className="break-words text-sm font-semibold">
                  {order.display_name}
                </div>
                <div className="app-muted mt-1 break-all text-xs">
                  {order.symbol}
                </div>
              </div>
              <input
                aria-label={labels.amountLabel(order.symbol)}
                type="number"
                step="any"
                min="0"
                placeholder={labels.amountPlaceholder}
                value={order.amount ?? ''}
                onChange={(event) => {
                  const nextAmount =
                    event.target.value === ''
                      ? null
                      : Number(event.target.value);
                  updateOrderAmount(index, nextAmount);
                }}
                className="app-field min-h-10 min-w-0 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
              />
            </div>
          ))}
        </div>
      )}
      <input
        aria-label={labels.noteLabel}
        placeholder={labels.notePlaceholder}
        value={values.note}
        onChange={(event) =>
          setValues((current) => ({ ...current, note: event.target.value }))
        }
        className="app-field min-h-10 min-w-0 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
      />
      {submitError ? (
        <div className="app-error-text text-sm">{submitError}</div>
      ) : null}
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
