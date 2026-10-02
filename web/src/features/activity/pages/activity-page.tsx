import { useCallback, useMemo, useRef, useState } from 'react';
import { createLazyRoute } from '@tanstack/react-router';
import { Plus } from 'lucide-react';

import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import { ToastStack, type ToastItem } from '../../../shared/ui/toast-stack';
import {
  EvidenceDrawer,
  EvidenceState,
  StatusBadge,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { usePreferences } from '../../../shared/preferences/context';
import {
  createLedgerMutationIdentity,
  createTradeMutationIdentity,
  useCreateAdjustmentMutation,
  useCreateCashFlowMutation,
  useCreateDividendMutation,
  useCreateTradeMutation,
  useLedgerEntriesQuery,
  usePendingFundOrdersQuery,
  useTradePreviewMutation,
  type AdjustmentPayload,
  type CashFlowPayload,
  type DividendPayload,
  type TradeMutationPayload,
  type TradePayload,
} from '../api';
import { ActivityFeed, ActivityFeedLoading } from '../components/activity-feed';
import type { CashFlowFormValues } from '../components/cash-flow-form';
import type { DividendFormValues } from '../components/dividend-form';
import type {
  FundBatchCandidate,
  FundBatchFormValues,
} from '../components/fund-batch-form';
import type { ManualAdjustmentFormValues } from '../components/manual-adjustment-form';
import type { TradeFormValues } from '../components/trade-form';
import {
  ActivityEntryToolsPanel,
  type ActivityEntryDrafts,
  type ActivityEntryTool,
} from '../components/activity-entry-tools-panel';
import { usePositionsQuery } from '../activity-feature-boundary';
import { useSettingsQuery } from '../activity-feature-boundary';
import { getErrorMessage } from '../../../shared/error-message';
import { formatCurrency, formatTimestamp } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';

type RetainedSubmission<TPayload> = {
  inputKey: string;
  payload: TPayload;
};

type RetainedFundBatchSubmissions = {
  completedInputKeyByOrderKey: Map<string, string>;
  pendingByOrderKey: Map<string, RetainedSubmission<TradeMutationPayload>>;
};

function stableKey(input: unknown) {
  return JSON.stringify(input);
}

function prepareRetainedSubmission<TInput, TPayload>(
  current: RetainedSubmission<TPayload> | null,
  input: TInput,
  identify: (input: TInput) => TPayload,
) {
  const inputKey = stableKey(input);
  return current?.inputKey === inputKey
    ? current
    : { inputKey, payload: identify(input) };
}

async function submitRetainedFundBatch(
  inputs: TradePayload[],
  submissions: RetainedFundBatchSubmissions,
  submit: (payload: TradeMutationPayload) => Promise<unknown>,
) {
  const keyedInputs = inputs.map((input) => ({
    input,
    inputKey: stableKey(input),
    orderKey: stableKey([input.asset_class, input.direction, input.symbol]),
  }));
  for (const { input, inputKey, orderKey } of keyedInputs) {
    const completedInputKey =
      submissions.completedInputKeyByOrderKey.get(orderKey);
    if (completedInputKey !== undefined && completedInputKey !== inputKey) {
      throw new Error(`Saved fund order changed: ${input.symbol}`);
    }
  }
  for (const { input, inputKey, orderKey } of keyedInputs) {
    if (submissions.completedInputKeyByOrderKey.get(orderKey) === inputKey) {
      continue;
    }
    const submission = prepareRetainedSubmission(
      submissions.pendingByOrderKey.get(orderKey) ?? null,
      input,
      (payload) => ({ ...payload, ...createTradeMutationIdentity() }),
    );
    submissions.pendingByOrderKey.set(orderKey, submission);
    await submit(submission.payload);
    if (submissions.pendingByOrderKey.get(orderKey) === submission) {
      submissions.pendingByOrderKey.delete(orderKey);
      submissions.completedInputKeyByOrderKey.set(orderKey, inputKey);
    }
  }
}

function normalizeOptionalNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function tradeSubmissionInput(values: TradeFormValues): TradePayload {
  return {
    ...values,
    occurred_at: new Date(values.occurred_at).toISOString(),
    quantity: normalizeOptionalNumber(values.quantity),
    unit_price: normalizeOptionalNumber(values.unit_price),
    amount: normalizeOptionalNumber(values.amount),
    fee: normalizeOptionalNumber(values.fee),
    asset_class: values.asset_class.trim().toLowerCase(),
    symbol: values.symbol.trim(),
  };
}

function fundBatchSubmissionInputs(
  values: FundBatchFormValues,
  batchTitle: string,
): TradePayload[] {
  const occurredAt = new Date(values.occurred_at).toISOString();
  return values.orders.map((order) => ({
    occurred_at: occurredAt,
    symbol: order.symbol,
    asset_class: 'fund',
    direction: 'buy',
    quantity: null,
    unit_price: null,
    amount: order.amount,
    fee: 0,
    note: [values.note.trim(), order.display_name, batchTitle]
      .filter(Boolean)
      .join(' | '),
  }));
}

function ledgerSubmissionInput<TValues extends { occurred_at: string }>(
  values: TValues,
) {
  return {
    ...values,
    occurred_at: new Date(values.occurred_at).toISOString(),
  };
}

function adjustmentSubmissionInput(values: ManualAdjustmentFormValues) {
  return {
    ...values,
    symbol: values.symbol || null,
    amount: normalizeOptionalNumber(values.amount),
    quantity: normalizeOptionalNumber(values.quantity),
    price: normalizeOptionalNumber(values.price),
    occurred_at: new Date(values.occurred_at).toISOString(),
  };
}

export function ActivityPage() {
  const copy = useCopy();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [entryDrawerOpen, setEntryDrawerOpen] = useState(false);
  // Keep unfinished inputs only for this page visit, including tool switches.
  const entryDrafts = useRef<ActivityEntryDrafts>({});
  const [entryFormVersions, setEntryFormVersions] = useState<
    Partial<Record<ActivityEntryTool, number>>
  >({});
  const clearEntryDraft = (tool: ActivityEntryTool) => {
    delete entryDrafts.current[tool];
    setEntryFormVersions((current) => ({
      ...current,
      [tool]: (current[tool] ?? 0) + 1,
    }));
  };
  const [activeEntryTool, setActiveEntryTool] =
    useState<ActivityEntryTool>('trade');
  const entries = useLedgerEntriesQuery();
  const pendingFundOrders = usePendingFundOrdersQuery();
  const positions = usePositionsQuery(entryDrawerOpen);
  const settings = useSettingsQuery();
  const createTrade = useCreateTradeMutation();
  const submitTrade = createTrade.mutateAsync;
  const tradePreview = useTradePreviewMutation();
  const previewTrade = tradePreview.mutate;
  const resetTradePreview = tradePreview.reset;
  const createCashFlow = useCreateCashFlowMutation();
  const createDividend = useCreateDividendMutation();
  const createAdjustment = useCreateAdjustmentMutation();
  const tradeSubmissionRef =
    useRef<RetainedSubmission<TradeMutationPayload> | null>(null);
  const fundBatchSubmissionRef = useRef<RetainedFundBatchSubmissions | null>(
    null,
  );
  const cashFlowSubmissionRef =
    useRef<RetainedSubmission<CashFlowPayload> | null>(null);
  const dividendSubmissionRef =
    useRef<RetainedSubmission<DividendPayload> | null>(null);
  const adjustmentSubmissionRef =
    useRef<RetainedSubmission<AdjustmentPayload> | null>(null);
  const ledgerRows = entries.data ?? [];
  const latestEntry = ledgerRows[0] ?? null;
  const fundBatchCandidates = useMemo<FundBatchCandidate[]>(
    () =>
      (positions.data ?? [])
        .filter((position) => position.asset_class?.toLowerCase() === 'fund')
        .map((position) => ({
          symbol: position.symbol,
          display_name:
            position.display_name || position.name || position.symbol,
        })),
    [positions.data],
  );

  const pushToast = (
    tone: ToastItem['tone'],
    title: string,
    message: string,
  ) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, tone, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  };

  const handleTradeSubmit = async (values: TradeFormValues) => {
    const input = tradeSubmissionInput(values);
    const submission = prepareRetainedSubmission(
      tradeSubmissionRef.current,
      input,
      (payload) => ({ ...payload, ...createTradeMutationIdentity() }),
    );
    tradeSubmissionRef.current = submission;
    try {
      await createTrade.mutateAsync(submission.payload);
      clearEntryDraft('trade');
      if (tradeSubmissionRef.current === submission) {
        tradeSubmissionRef.current = null;
      }
      pushToast(
        'success',
        copy.activity.tradeSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.tradeFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleTradePreviewChange = useCallback(
    (values: TradeFormValues) => {
      const assetClass = values.asset_class.trim().toLowerCase();
      const symbol = values.symbol.trim();
      const quantity = normalizeOptionalNumber(values.quantity);
      const unitPrice = normalizeOptionalNumber(values.unit_price);
      const fee = normalizeOptionalNumber(values.fee);
      const occurredAt = new Date(values.occurred_at);
      const isPriceBasedTrade =
        symbol &&
        Number.isFinite(occurredAt.getTime()) &&
        quantity !== null &&
        quantity > 0 &&
        unitPrice !== null &&
        unitPrice > 0 &&
        !(assetClass === 'fund' && values.direction === 'buy');

      if (!isPriceBasedTrade) {
        resetTradePreview();
        return;
      }

      previewTrade({
        ...values,
        occurred_at: occurredAt.toISOString(),
        quantity,
        unit_price: unitPrice,
        amount: normalizeOptionalNumber(values.amount),
        fee,
        asset_class: assetClass,
        symbol,
      });
    },
    [previewTrade, resetTradePreview],
  );

  const handleFundBatchSubmit = async (values: FundBatchFormValues) => {
    const inputs = fundBatchSubmissionInputs(
      values,
      copy.activity.forms.fundBatch.title,
    );
    const submissions: RetainedFundBatchSubmissions =
      fundBatchSubmissionRef.current ?? {
        completedInputKeyByOrderKey: new Map(),
        pendingByOrderKey: new Map(),
      };
    fundBatchSubmissionRef.current = submissions;
    try {
      await submitRetainedFundBatch(inputs, submissions, submitTrade);
      clearEntryDraft('fundBatch');
      if (fundBatchSubmissionRef.current === submissions) {
        fundBatchSubmissionRef.current = null;
      }
      pushToast(
        'success',
        copy.activity.tradeSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.tradeFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleCashFlowSubmit = async (values: CashFlowFormValues) => {
    const input = ledgerSubmissionInput(values);
    const submission = prepareRetainedSubmission(
      cashFlowSubmissionRef.current,
      input,
      (payload) => ({ ...payload, ...createLedgerMutationIdentity() }),
    );
    cashFlowSubmissionRef.current = submission;
    try {
      await createCashFlow.mutateAsync(submission.payload);
      clearEntryDraft('cashFlow');
      if (cashFlowSubmissionRef.current === submission) {
        cashFlowSubmissionRef.current = null;
      }
      pushToast(
        'success',
        copy.activity.cashFlowSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.cashFlowFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleDividendSubmit = async (values: DividendFormValues) => {
    const input = ledgerSubmissionInput(values);
    const submission = prepareRetainedSubmission(
      dividendSubmissionRef.current,
      input,
      (payload) => ({ ...payload, ...createLedgerMutationIdentity() }),
    );
    dividendSubmissionRef.current = submission;
    try {
      await createDividend.mutateAsync(submission.payload);
      clearEntryDraft('dividend');
      if (dividendSubmissionRef.current === submission) {
        dividendSubmissionRef.current = null;
      }
      pushToast(
        'success',
        copy.activity.dividendSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast('error', copy.activity.dividendFailed, getErrorMessage(error));
      throw error;
    }
  };

  const handleAdjustmentSubmit = async (values: ManualAdjustmentFormValues) => {
    const input = adjustmentSubmissionInput(values);
    const submission = prepareRetainedSubmission(
      adjustmentSubmissionRef.current,
      input,
      (payload) => ({ ...payload, ...createLedgerMutationIdentity() }),
    );
    adjustmentSubmissionRef.current = submission;
    try {
      await createAdjustment.mutateAsync(submission.payload);
      clearEntryDraft('adjustment');
      if (adjustmentSubmissionRef.current === submission) {
        adjustmentSubmissionRef.current = null;
      }
      pushToast(
        'success',
        copy.activity.adjustmentSaved,
        copy.activity.feedRefreshed,
      );
    } catch (error) {
      pushToast(
        'error',
        copy.activity.adjustmentFailed,
        getErrorMessage(error),
      );
      throw error;
    }
  };

  return (
    <>
      <ToastStack toasts={toasts} />
      <section
        className="app-workbench-route min-w-0 space-y-4 sm:space-y-5"
        data-workbench-route="activity"
        data-workbench-width="wide"
      >
        <WorkspaceHeader
          eyebrow={copy.activity.kicker}
          title={copy.activity.title}
          description={copy.activity.subtitle}
          context={
            latestEntry ? formatTimestamp(latestEntry.timestamp) : undefined
          }
          actions={
            <button
              type="button"
              className="app-button-secondary inline-flex items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold shadow-xs"
              onClick={() => setEntryDrawerOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              {copy.activity.entryTools.openAction}
            </button>
          }
        />

        <div
          className="grid min-w-0 gap-x-4 gap-y-1 border-y border-[var(--app-divider)] px-1 py-2.5 sm:grid-cols-[10rem_9rem_minmax(0,1fr)] sm:items-baseline"
          data-testid="ledger-scope-register"
        >
          <span className="app-type-overline text-[var(--app-text-tertiary)]">
            {copy.activity.summary.netCashImpact}
          </span>
          <span className="font-mono text-sm font-semibold tabular-nums text-[var(--app-text)]">
            {copy.activity.summary.netCashImpactUnavailable}
          </span>
          <span className="text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.activity.summary.netCashImpactDetail}
          </span>
        </div>

        <div
          className="min-w-0 space-y-6"
          data-activity-surface="audit-history"
        >
          {entries.isLoading ? (
            <ActivityFeedLoading />
          ) : entries.isError ? (
            <EvidenceState
              kind="error"
              title={copy.states.error}
              description={copy.activity.error}
              action={
                <button
                  type="button"
                  className="app-button-secondary px-3 py-2 text-xs"
                  onClick={() => void entries.refetch()}
                >
                  {copy.states.retry}
                </button>
              }
            />
          ) : (
            <ActivityFeed entries={entries.data ?? []} />
          )}
          <PendingFundOrdersCard
            orders={pendingFundOrders.data ?? []}
            loading={pendingFundOrders.isLoading}
            error={pendingFundOrders.isError}
            onRetry={() => void pendingFundOrders.refetch()}
          />
        </div>
      </section>
      <EvidenceDrawer
        open={entryDrawerOpen}
        onClose={() => setEntryDrawerOpen(false)}
        title={copy.activity.entryTools.title}
        description={copy.activity.entryTools.detail}
        closeLabel={copy.activity.entryTools.closeAction}
        className="w-[min(96vw,640px)]"
      >
        <ActivityEntryToolsPanel
          activeEntryTool={activeEntryTool}
          entryDrafts={entryDrafts}
          entryFormVersions={entryFormVersions}
          candidates={fundBatchCandidates}
          commissionSettings={
            settings.data
              ? {
                  stock_rate: settings.data.account_commission_rate,
                  stock_min_commission: settings.data.account_min_commission,
                }
              : undefined
          }
          createAdjustmentPending={createAdjustment.isPending}
          createCashFlowPending={createCashFlow.isPending}
          createDividendPending={createDividend.isPending}
          createTradePending={createTrade.isPending}
          loadingCandidates={positions.isLoading}
          onAdjustmentSubmit={handleAdjustmentSubmit}
          onCashFlowSubmit={handleCashFlowSubmit}
          onDividendSubmit={handleDividendSubmit}
          onFundBatchSubmit={handleFundBatchSubmit}
          onSelectEntryTool={setActiveEntryTool}
          onTradePreviewChange={handleTradePreviewChange}
          onTradeSubmit={handleTradeSubmit}
          previewError={tradePreview.isError}
          previewLoading={tradePreview.isPending}
          tradePreview={tradePreview.data ?? null}
        />
      </EvidenceDrawer>
    </>
  );
}

function PendingFundOrdersCard({
  orders,
  loading,
  error,
  onRetry,
}: {
  orders: Array<{
    id: number;
    submitted_at: string;
    symbol: string;
    display_name: string;
    amount: number;
    target_trade_date: string;
    status: string;
  }>;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();

  if (loading) {
    return (
      <section
        aria-busy="true"
        aria-live="polite"
        className="min-w-0 overflow-hidden border-y border-[var(--app-divider)]"
        data-ledger-register="pending-fund-orders"
        data-testid="pending-fund-orders-loading"
      >
        <span className="sr-only">{copy.activity.pending.loading}</span>
        <div className="flex items-start justify-between gap-3 border-b border-[var(--app-divider)] px-4 py-3">
          <div>
            <div className="app-product-mark">
              {copy.activity.pending.kicker}
            </div>
            <h2 className="app-type-section-title mt-2">
              {copy.activity.pending.title}
            </h2>
          </div>
          <span
            aria-hidden="true"
            className="block h-6 w-8 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse"
          />
        </div>
        <div
          aria-hidden="true"
          className="divide-y divide-[var(--app-divider)]"
          data-testid="pending-fund-orders-loading-rows"
        >
          {Array.from({ length: 2 }, (_, index) => (
            <div
              key={index}
              className="grid min-h-16 grid-cols-[minmax(0,1fr)_7rem] items-center gap-4 px-4 py-3"
            >
              <span className="min-w-0">
                <span className="block h-3 w-40 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                <span className="mt-2 block h-2 w-56 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
              </span>
              <span className="min-w-0">
                <span className="ml-auto block h-3 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
                <span className="ml-auto mt-2 block h-2 w-14 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] motion-safe:animate-pulse" />
              </span>
            </div>
          ))}
        </div>
      </section>
    );
  }
  if (error) {
    return (
      <EvidenceState
        kind="error"
        title={copy.states.error}
        description={copy.activity.pending.error}
        action={
          <button
            type="button"
            className="app-button-secondary px-3 py-2 text-xs"
            onClick={onRetry}
          >
            {copy.states.retry}
          </button>
        }
      />
    );
  }
  if (orders.length === 0) {
    return null;
  }

  return (
    <section
      className="min-w-0 overflow-hidden border-y border-[var(--app-divider)]"
      data-ledger-register="pending-fund-orders"
    >
      <div className="flex items-start justify-between gap-3 border-b border-[var(--app-divider)] px-4 py-3">
        <div>
          <div className="app-product-mark">{copy.activity.pending.kicker}</div>
          <h2 className="app-type-section-title mt-2">
            {copy.activity.pending.title}
          </h2>
        </div>
        <StatusBadge tone="warning">{orders.length}</StatusBadge>
      </div>
      <div className="divide-y divide-[var(--app-divider)]">
        {orders.map((order) => (
          <div key={order.id} className="px-4 py-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">
                  {order.display_name}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {order.symbol} · {copy.activity.pending.submittedAt}{' '}
                  {formatTimestamp(order.submitted_at)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold">
                  {formatCurrency(order.amount)}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {formatPendingStatus(order.status, copy, locale)}
                </div>
              </div>
            </div>
            <div className="app-muted mt-3 text-xs">
              {copy.activity.pending.waitingFor} {order.target_trade_date}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatPendingStatus(
  status: string,
  copy: AppCopy,
  locale: 'en' | 'zh',
) {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'pending') {
    return copy.activity.pending.status.pending;
  }
  if (normalized === 'confirmed') {
    return copy.activity.pending.status.confirmed;
  }
  if (normalized === 'rejected') {
    return copy.activity.pending.status.rejected;
  }
  return formatPublicStatus(status, locale);
}

export const Route = createLazyRoute('/activity')({
  component: ActivityPage,
});
