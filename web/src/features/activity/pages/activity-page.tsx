import { useCallback, useMemo, useState } from 'react';
import { createLazyRoute } from '@tanstack/react-router';

import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import { ToastStack, type ToastItem } from '../../../shared/ui/toast-stack';
import {
  ControlledActionZone,
  EvidenceDrawer,
  EvidenceState,
  MetricStrip,
  StatusBadge,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useCreateAdjustmentMutation,
  useCreateCashFlowMutation,
  useCreateDividendMutation,
  useCreateTradeMutation,
  useLedgerEntriesQuery,
  usePendingFundOrdersQuery,
  useTradePreviewMutation,
} from '../api';
import { ActivityFeed, ActivityFeedLoading } from '../components/activity-feed';
import {
  CashFlowForm,
  type CashFlowFormValues,
} from '../components/cash-flow-form';
import {
  DividendForm,
  type DividendFormValues,
} from '../components/dividend-form';
import {
  FundBatchForm,
  type FundBatchCandidate,
  type FundBatchFormValues,
} from '../components/fund-batch-form';
import {
  ManualAdjustmentForm,
  type ManualAdjustmentFormValues,
} from '../components/manual-adjustment-form';
import { TradeForm, type TradeFormValues } from '../components/trade-form';
import { usePositionsQuery } from '../activity-feature-boundary';
import { useSettingsQuery } from '../activity-feature-boundary';
import { getErrorMessage } from '../../../shared/error-message';
import { formatCurrency, formatTimestamp } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';

export function ActivityPage() {
  const copy = useCopy();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [entryDrawerOpen, setEntryDrawerOpen] = useState(false);
  const [activeEntryTool, setActiveEntryTool] =
    useState<ActivityEntryTool>('trade');
  const entries = useLedgerEntriesQuery();
  const pendingFundOrders = usePendingFundOrdersQuery();
  const positions = usePositionsQuery(entryDrawerOpen);
  const settings = useSettingsQuery();
  const createTrade = useCreateTradeMutation();
  const tradePreview = useTradePreviewMutation();
  const previewTrade = tradePreview.mutate;
  const resetTradePreview = tradePreview.reset;
  const createCashFlow = useCreateCashFlowMutation();
  const createDividend = useCreateDividendMutation();
  const createAdjustment = useCreateAdjustmentMutation();
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
    const normalizeNumber = (value: number | null | undefined) =>
      typeof value === 'number' && Number.isFinite(value) ? value : null;
    try {
      await createTrade.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
        quantity: normalizeNumber(values.quantity),
        unit_price: normalizeNumber(values.unit_price),
        amount: normalizeNumber(values.amount),
        fee: normalizeNumber(values.fee),
        asset_class: values.asset_class.trim().toLowerCase(),
        symbol: values.symbol.trim(),
      });
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
      const normalizeNumber = (value: number | null | undefined) =>
        typeof value === 'number' && Number.isFinite(value) ? value : null;
      const assetClass = values.asset_class.trim().toLowerCase();
      const symbol = values.symbol.trim();
      const quantity = normalizeNumber(values.quantity);
      const unitPrice = normalizeNumber(values.unit_price);
      const fee = normalizeNumber(values.fee);
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
        amount: normalizeNumber(values.amount),
        fee,
        asset_class: assetClass,
        symbol,
      });
    },
    [previewTrade, resetTradePreview],
  );

  const handleFundBatchSubmit = async (values: FundBatchFormValues) => {
    try {
      for (const order of values.orders) {
        await createTrade.mutateAsync({
          occurred_at: new Date(values.occurred_at).toISOString(),
          symbol: order.symbol,
          asset_class: 'fund',
          direction: 'buy',
          quantity: null,
          unit_price: null,
          amount: order.amount,
          fee: 0,
          note: [
            values.note.trim(),
            order.display_name,
            copy.activity.forms.fundBatch.title,
          ]
            .filter(Boolean)
            .join(' | '),
        });
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
    try {
      await createCashFlow.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
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
    try {
      await createDividend.mutateAsync({
        ...values,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
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
    try {
      await createAdjustment.mutateAsync({
        ...values,
        symbol: values.symbol || null,
        amount:
          values.amount === null || Number.isNaN(values.amount)
            ? null
            : values.amount,
        quantity:
          values.quantity === null || Number.isNaN(values.quantity)
            ? null
            : values.quantity,
        price:
          values.price === null || Number.isNaN(values.price)
            ? null
            : values.price,
        occurred_at: new Date(values.occurred_at).toISOString(),
      });
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
        className="app-workbench-route min-w-0 space-y-5 sm:space-y-6"
        data-workbench-route="activity"
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
              className="app-button-secondary px-3 py-2 text-xs"
              onClick={() => setEntryDrawerOpen(true)}
            >
              {copy.activity.entryTools.openAction}
            </button>
          }
        />

        <MetricStrip
          ariaLabel={copy.activity.title}
          className="activity-summary-strip"
          items={[
            {
              id: 'pending-orders',
              label: copy.activity.summary.pendingOrders,
              value: pendingFundOrders.isLoading
                ? '--'
                : String(pendingFundOrders.data?.length ?? 0),
              detail: copy.activity.summary.pendingOrdersDetail,
              tone:
                (pendingFundOrders.data?.length ?? 0) > 0
                  ? 'warning'
                  : 'neutral',
            },
            {
              id: 'net-cash-impact',
              label: copy.activity.summary.netCashImpact,
              value: copy.activity.summary.netCashImpactUnavailable,
              detail: copy.activity.summary.netCashImpactDetail,
            },
          ]}
        />

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

type ActivityEntryTool =
  'trade' | 'fundBatch' | 'cashFlow' | 'dividend' | 'adjustment';

function ActivityEntryToolsPanel({
  activeEntryTool,
  candidates,
  commissionSettings,
  createAdjustmentPending,
  createCashFlowPending,
  createDividendPending,
  createTradePending,
  loadingCandidates,
  onAdjustmentSubmit,
  onCashFlowSubmit,
  onDividendSubmit,
  onFundBatchSubmit,
  onSelectEntryTool,
  onTradePreviewChange,
  onTradeSubmit,
  previewError,
  previewLoading,
  tradePreview,
}: {
  activeEntryTool: ActivityEntryTool;
  candidates: FundBatchCandidate[];
  commissionSettings?: {
    stock_rate: number;
    stock_min_commission: number;
  };
  createAdjustmentPending: boolean;
  createCashFlowPending: boolean;
  createDividendPending: boolean;
  createTradePending: boolean;
  loadingCandidates: boolean;
  onAdjustmentSubmit: (values: ManualAdjustmentFormValues) => Promise<void>;
  onCashFlowSubmit: (values: CashFlowFormValues) => Promise<void>;
  onDividendSubmit: (values: DividendFormValues) => Promise<void>;
  onFundBatchSubmit: (values: FundBatchFormValues) => Promise<void>;
  onSelectEntryTool: (tool: ActivityEntryTool) => void;
  onTradePreviewChange: (values: TradeFormValues) => void;
  onTradeSubmit: (values: TradeFormValues) => Promise<void>;
  previewError: boolean;
  previewLoading: boolean;
  tradePreview: ReturnType<typeof useTradePreviewMutation>['data'] | null;
}) {
  const copy = useCopy();
  const tools: Array<{ key: ActivityEntryTool; label: string }> = [
    { key: 'trade', label: copy.activity.forms.trade.title },
    { key: 'cashFlow', label: copy.activity.forms.cashFlow.title },
    { key: 'dividend', label: copy.activity.forms.dividend.title },
    { key: 'adjustment', label: copy.activity.forms.adjustment.title },
    { key: 'fundBatch', label: copy.activity.forms.fundBatch.title },
  ];

  return (
    <ControlledActionZone
      title={copy.activity.entryTools.boundaryTitle}
      description={copy.activity.entryTools.boundary}
      layout="stack"
      tone="info"
      className="min-w-0"
    >
      <div className="min-w-0 w-full">
        <div
          aria-label={copy.activity.entryTools.ariaLabel}
          className="grid min-w-0 grid-cols-2 gap-1"
          role="group"
        >
          {tools.map((tool) => {
            const isSelected = activeEntryTool === tool.key;
            return (
              <button
                key={tool.key}
                aria-pressed={isSelected}
                className={`min-h-10 min-w-0 rounded-[var(--app-radius-control)] border px-2.5 py-1.5 text-left text-xs font-semibold transition-colors xl:min-h-8 ${
                  isSelected
                    ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-hover)]'
                    : 'border-transparent bg-transparent text-[var(--app-text-tertiary)] hover:border-[var(--app-border)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)]'
                }`}
                onClick={() => onSelectEntryTool(tool.key)}
                type="button"
              >
                {tool.label}
              </button>
            );
          })}
        </div>
        <div className="mt-4 min-w-0 border-t border-[var(--app-divider)] pt-4">
          {activeEntryTool === 'trade' ? (
            <TradeForm
              onSubmit={onTradeSubmit}
              pending={createTradePending}
              tradePreview={tradePreview}
              previewLoading={previewLoading}
              previewError={previewError}
              onPreviewChange={onTradePreviewChange}
              commissionSettings={commissionSettings}
            />
          ) : null}
          {activeEntryTool === 'fundBatch' ? (
            <FundBatchForm
              candidates={candidates}
              loadingCandidates={loadingCandidates}
              onSubmit={onFundBatchSubmit}
              pending={createTradePending}
            />
          ) : null}
          {activeEntryTool === 'cashFlow' ? (
            <CashFlowForm
              onSubmit={onCashFlowSubmit}
              pending={createCashFlowPending}
            />
          ) : null}
          {activeEntryTool === 'dividend' ? (
            <DividendForm
              onSubmit={onDividendSubmit}
              pending={createDividendPending}
            />
          ) : null}
          {activeEntryTool === 'adjustment' ? (
            <ManualAdjustmentForm
              onSubmit={onAdjustmentSubmit}
              pending={createAdjustmentPending}
            />
          ) : null}
        </div>
      </div>
    </ControlledActionZone>
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
        className="app-workbench-section min-w-0 overflow-hidden"
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
    <section className="app-workbench-section min-w-0 overflow-hidden">
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
