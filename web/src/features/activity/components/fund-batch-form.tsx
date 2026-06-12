import { useEffect, useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';

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
    occurred_at: new Date().toISOString().slice(0, 16),
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
      className="app-panel space-y-4 rounded-2xl p-5"
    >
      <div>
        <div className="app-kicker text-xs uppercase tracking-[0.18em]">
          {labels.title}
        </div>
        <p className="app-muted mt-2 text-xs leading-5">{labels.helper}</p>
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
        className="app-field w-full rounded-2xl px-4 py-3 text-sm"
      />
      {loadingCandidates ? (
        <div className="app-panel-strong rounded-2xl p-3 text-sm app-muted">
          {labels.loadingCandidates}
        </div>
      ) : values.orders.length === 0 ? (
        <div className="app-panel-strong rounded-2xl p-3 text-sm app-muted">
          {labels.noCandidates}
        </div>
      ) : (
        <div className="space-y-2">
          {values.orders.map((order, index) => (
            <div
              key={order.symbol}
              className="app-panel-strong grid gap-2 rounded-2xl p-3 sm:grid-cols-[minmax(0,1fr)_150px]"
            >
              <div>
                <div className="text-sm font-semibold">
                  {order.display_name}
                </div>
                <div className="app-muted mt-1 text-xs">{order.symbol}</div>
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
                className="app-field rounded-2xl px-4 py-3 text-sm"
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
        className="app-field w-full rounded-2xl px-4 py-3 text-sm"
      />
      {submitError ? (
        <div className="app-error-text text-sm">{submitError}</div>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="app-button-primary rounded-2xl px-5 py-3 text-sm font-semibold disabled:opacity-50"
      >
        {pending ? labels.saving : labels.submit}
      </button>
    </form>
  );
}
