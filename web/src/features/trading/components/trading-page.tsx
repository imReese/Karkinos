import { useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { KillSwitchPanel } from './kill-switch-panel';
import {
  useConfirmManualOrderMutation,
  useDailyShadowRunMutation,
  useFillFactsQuery,
  useManualOrdersQuery,
  useOrderFactsQuery,
  useRejectManualOrderMutation,
  type FillFact,
  type ManualOrder,
  type ManualOrderStatus,
  type OrderFact,
} from '../api';

type SideFilter = 'all' | 'buy' | 'sell';

const STATUS_OPTIONS: ManualOrderStatus[] = [
  'all',
  'pending_confirm',
  'confirmed',
  'rejected',
  'canceled',
];

function statusLabel(
  status: string,
  labels: ReturnType<typeof useCopy>['trading']['page'],
) {
  if (status === 'pending_confirm') {
    return labels.statusPendingConfirm;
  }
  if (status === 'confirmed') {
    return labels.statusConfirmed;
  }
  if (status === 'rejected') {
    return labels.statusRejected;
  }
  if (status === 'canceled') {
    return labels.statusCanceled;
  }
  return status;
}

function getLatestOrderTimestamp(orders: ManualOrder[]) {
  const latest = orders
    .map((order) => order.updated_at || order.created_at || order.timestamp)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => right - left)[0];

  return latest ? new Date(latest).toISOString() : null;
}

function parsePayload(value: string): Record<string, string | null> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === 'object'
      ? (parsed as Record<string, string | null>)
      : null;
  } catch {
    return null;
  }
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function TradingPage() {
  const copy = useCopy();
  const labels = copy.trading.page;
  const orderLabels = copy.trading.orders;
  const [status, setStatus] = useState<ManualOrderStatus>('pending_confirm');
  const [symbolFilter, setSymbolFilter] = useState('');
  const [sideFilter, setSideFilter] = useState<SideFilter>('all');
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>(
    {},
  );
  const [rowError, setRowError] = useState('');
  const [confirmingRejectId, setConfirmingRejectId] = useState<string | null>(
    null,
  );

  const orders = useManualOrdersQuery(status);
  const allOrders = useManualOrdersQuery('all');
  const orderFacts = useOrderFactsQuery();
  const fillFacts = useFillFactsQuery();
  const shadowRun = useDailyShadowRunMutation();
  const confirmOrder = useConfirmManualOrderMutation();
  const rejectOrder = useRejectManualOrderMutation();
  const allOrderRows = allOrders.data ?? [];
  const rows = useMemo(() => {
    const normalizedSymbol = symbolFilter.trim().toLowerCase();
    return (orders.data ?? []).filter((order) => {
      const symbolMatches = normalizedSymbol
        ? order.symbol.toLowerCase().includes(normalizedSymbol)
        : true;
      const sideMatches =
        sideFilter === 'all' ? true : order.side.toLowerCase() === sideFilter;
      return symbolMatches && sideMatches;
    });
  }, [orders.data, sideFilter, symbolFilter]);

  const completedOrders = useMemo(
    () =>
      allOrderRows.filter((order) =>
        ['confirmed', 'rejected', 'canceled'].includes(order.status),
      ),
    [allOrderRows],
  );
  const counts = useMemo(
    () => ({
      pending: allOrderRows.filter(
        (order) => order.status === 'pending_confirm',
      ).length,
      confirmed: allOrderRows.filter((order) => order.status === 'confirmed')
        .length,
      rejected: allOrderRows.filter((order) => order.status === 'rejected')
        .length,
      canceled: allOrderRows.filter((order) => order.status === 'canceled')
        .length,
    }),
    [allOrderRows],
  );
  const latestTimestamp = getLatestOrderTimestamp(allOrderRows);
  const busy = confirmOrder.isPending || rejectOrder.isPending;

  const handleConfirm = async (orderId: string) => {
    setRowError('');
    setConfirmingRejectId(null);
    try {
      await confirmOrder.mutateAsync({ orderId });
    } catch {
      // Mutation error state renders the inline alert.
    }
  };

  const handleReject = async (orderId: string) => {
    const reason = (rejectReasons[orderId] ?? '').trim();
    if (!reason) {
      setRowError(orderLabels.rejectReasonRequired);
      setConfirmingRejectId(orderId);
      return;
    }
    if (confirmingRejectId !== orderId) {
      setRowError('');
      setConfirmingRejectId(orderId);
      return;
    }
    setRowError('');
    try {
      await rejectOrder.mutateAsync({ orderId, reason });
      setConfirmingRejectId(null);
      setRejectReasons((current) => {
        const next = { ...current };
        delete next[orderId];
        return next;
      });
    } catch (error) {
      // Mutation error state renders the inline alert.
    }
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <header className="app-page-header pb-1">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.kicker}</div>
            <h1 className="app-page-title mt-2">{labels.title}</h1>
          </div>
          <p className="app-page-subtitle sm:max-w-xl sm:text-right">
            {labels.subtitle}
          </p>
        </div>
      </header>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <StatusTile label={labels.pending} value={String(counts.pending)} />
        <StatusTile label={labels.confirmed} value={String(counts.confirmed)} />
        <StatusTile label={labels.rejected} value={String(counts.rejected)} />
        <StatusTile label={labels.canceled} value={String(counts.canceled)} />
        <StatusTile
          label={labels.lastUpdated}
          value={formatTimestamp(latestTimestamp)}
        />
      </div>

      <KillSwitchPanel />

      <ExecutionAuditPanel
        orders={orderFacts.data ?? []}
        fills={fillFacts.data ?? []}
        loading={orderFacts.isLoading || fillFacts.isLoading}
        error={orderFacts.isError || fillFacts.isError}
        shadowRunPending={shadowRun.isPending}
        shadowRunResult={shadowRun.data ?? null}
        onRunShadowReview={() => void shadowRun.mutate()}
      />

      <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
        <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
          <div className="flex min-w-0 flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div className="min-w-0">
              <div className="app-product-mark">{labels.filterTitle}</div>
              <h2 className="app-card-title mt-1.5">{labels.ordersTitle}</h2>
              <p className="app-muted mt-2 break-words text-sm">
                {labels.filteredCount(rows.length)}
              </p>
            </div>
            <div className="grid min-w-0 w-full gap-3 sm:grid-cols-3 xl:max-w-[680px]">
              <label className="grid gap-2 text-sm font-medium">
                {labels.statusFilter}
                <select
                  className="app-field rounded-2xl px-4 py-3 text-sm"
                  value={status}
                  onChange={(event) =>
                    setStatus(event.target.value as ManualOrderStatus)
                  }
                  aria-label={labels.statusFilter}
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option === 'all'
                        ? labels.allStatuses
                        : statusLabel(option, labels)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium">
                {labels.symbolFilter}
                <input
                  name="trading-symbol-filter"
                  autoComplete="off"
                  className="app-field rounded-2xl px-4 py-3 text-sm"
                  value={symbolFilter}
                  onChange={(event) => setSymbolFilter(event.target.value)}
                  placeholder={labels.symbolPlaceholder}
                  aria-label={labels.symbolFilter}
                />
              </label>
              <label className="grid gap-2 text-sm font-medium">
                {labels.sideFilter}
                <select
                  className="app-field rounded-2xl px-4 py-3 text-sm"
                  value={sideFilter}
                  onChange={(event) =>
                    setSideFilter(event.target.value as SideFilter)
                  }
                  aria-label={labels.sideFilter}
                >
                  <option value="all">{labels.allSides}</option>
                  <option value="buy">{labels.buy}</option>
                  <option value="sell">{labels.sell}</option>
                </select>
              </label>
            </div>
          </div>

          <OrderQueue
            orders={rows}
            loading={orders.isLoading}
            error={orders.isError}
            busy={busy}
            rejectReasons={rejectReasons}
            confirmingRejectId={confirmingRejectId}
            onConfirm={handleConfirm}
            onReject={handleReject}
            onRejectReasonChange={(orderId, value) =>
              setRejectReasons((current) => ({ ...current, [orderId]: value }))
            }
          />

          {rowError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {rowError}
            </div>
          ) : null}
          {confirmOrder.isError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {getErrorMessage(confirmOrder.error)}
            </div>
          ) : null}
          {rejectOrder.isError ? (
            <div className="app-error-text mt-3 text-sm" role="alert">
              {getErrorMessage(rejectOrder.error)}
            </div>
          ) : null}
        </div>
      </section>

      <section className="app-terminal-panel rounded-[28px] p-[1px]">
        <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
          <div>
            <div className="app-product-mark">{labels.historyKicker}</div>
            <h2 className="app-card-title mt-1.5">{labels.historyTitle}</h2>
            <p className="app-muted mt-2 text-sm">{labels.historyDetail}</p>
          </div>
          {completedOrders.length === 0 ? (
            <div className="mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
              {labels.noHistory}
            </div>
          ) : (
            <div className="mt-5 grid gap-2">
              {completedOrders.slice(0, 8).map((order) => (
                <AuditRow key={order.order_id} order={order} />
              ))}
            </div>
          )}
        </div>
      </section>
    </section>
  );
}

function ExecutionAuditPanel({
  orders,
  fills,
  loading,
  error,
  shadowRunPending,
  shadowRunResult,
  onRunShadowReview,
}: {
  orders: OrderFact[];
  fills: FillFact[];
  loading: boolean;
  error: boolean;
  shadowRunPending: boolean;
  shadowRunResult: { processed_count: number; reused_count: number } | null;
  onRunShadowReview: () => void;
}) {
  const labels = useCopy().trading.page;
  const latestOrders = orders.slice(0, 4);
  const latestFills = fills.slice(0, 4);

  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.executionAudit}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.executionAuditTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl break-words text-sm leading-6">
              {labels.executionAuditDetail}
            </p>
          </div>
          <button
            type="button"
            className="app-button-secondary shrink-0 rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={shadowRunPending}
            onClick={onRunShadowReview}
          >
            {shadowRunPending
              ? labels.runningShadowReview
              : labels.runShadowReview}
          </button>
        </div>

        {shadowRunResult ? (
          <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] px-4 py-3 text-sm text-[var(--app-success)]">
            {labels.shadowRunResult(
              shadowRunResult.processed_count,
              shadowRunResult.reused_count,
            )}
          </div>
        ) : null}

        {loading ? (
          <div className="app-muted mt-4 text-sm">{labels.auditLoading}</div>
        ) : error ? (
          <div className="app-error-text mt-4 text-sm">
            {labels.auditLoadFailed}
          </div>
        ) : (
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
            <AuditFactList
              title={labels.orderFacts}
              empty={labels.noOrderFacts}
              rows={latestOrders.map((order) => ({
                id: order.order_id,
                title: `${order.symbol} · ${statusLabel(order.status, labels)}`,
                detail: `${order.side} ${formatQuantity(order.quantity)} @ ${
                  order.price == null ? '--' : formatPrice(order.price)
                }`,
                timestamp: order.timestamp,
              }))}
            />
            <AuditFactList
              title={labels.fills}
              empty={labels.noFills}
              rows={latestFills.map((fill) => ({
                id: fill.fill_id ?? fill.order_id,
                title: `${fill.symbol} · ${fill.side}`,
                detail: `${formatQuantity(fill.fill_quantity)} @ ${formatPrice(
                  fill.fill_price,
                )} · ${labels.commission} ${formatCurrency(fill.commission)}`,
                timestamp: fill.timestamp,
              }))}
            />
          </div>
        )}
      </div>
    </section>
  );
}

function AuditFactList({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: Array<{ id: string; title: string; detail: string; timestamp: string }>;
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-4">
      <div className="app-product-mark">{title}</div>
      {rows.length === 0 ? (
        <div className="app-muted mt-3 text-sm">{empty}</div>
      ) : (
        <div className="mt-3 grid gap-2">
          {rows.map((row) => (
            <div
              key={row.id}
              className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] px-3 py-2 text-sm"
            >
              <div className="font-semibold text-[var(--app-text)]">
                {row.title}
              </div>
              <div className="app-muted mt-1 break-words text-xs">
                {row.detail}
              </div>
              <div className="app-muted mt-1 font-mono text-xs tabular-nums">
                {formatTimestamp(row.timestamp)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-panel-strong rounded-2xl px-4 py-3 shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
      <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
        {label}
      </div>
      <div className="mt-1.5 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function OrderQueue({
  orders,
  loading,
  error,
  busy,
  rejectReasons,
  confirmingRejectId,
  onConfirm,
  onReject,
  onRejectReasonChange,
}: {
  orders: ManualOrder[];
  loading: boolean;
  error: boolean;
  busy: boolean;
  rejectReasons: Record<string, string>;
  confirmingRejectId: string | null;
  onConfirm: (orderId: string) => Promise<void>;
  onReject: (orderId: string) => Promise<void>;
  onRejectReasonChange: (orderId: string, value: string) => void;
}) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const pageLabels = copy.trading.page;

  if (loading) {
    return <div className="app-muted mt-5 text-sm">{labels.loading}</div>;
  }
  if (error) {
    return (
      <div className="app-error-text mt-5 text-sm">{labels.loadFailed}</div>
    );
  }
  if (orders.length === 0) {
    return (
      <div className="mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="mt-5 min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
      <table className="min-w-[1120px] table-fixed text-left text-sm">
        <thead>
          <tr className="app-kicker border-b border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] text-[11px] uppercase tracking-[0.16em]">
            <th className="w-[130px] px-3 py-3">{labels.symbol}</th>
            <th className="w-[90px] px-3 py-3">{labels.side}</th>
            <th className="w-[120px] px-3 py-3 text-right">
              {labels.quantity}
            </th>
            <th className="w-[120px] px-3 py-3 text-right">{labels.price}</th>
            <th className="w-[140px] px-3 py-3">{pageLabels.statusFilter}</th>
            <th className="w-[240px] px-3 py-3">{labels.riskHint}</th>
            <th className="w-[210px] px-3 py-3">{labels.rejectReason}</th>
            <th className="w-[180px] px-3 py-3">{labels.actions}</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.order_id}
              order={order}
              busy={busy}
              rejectReason={rejectReasons[order.order_id] ?? ''}
              confirmingReject={confirmingRejectId === order.order_id}
              onConfirm={() => onConfirm(order.order_id)}
              onReject={() => onReject(order.order_id)}
              onRejectReasonChange={(value) =>
                onRejectReasonChange(order.order_id, value)
              }
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrderRow({
  order,
  busy,
  rejectReason,
  confirmingReject,
  onConfirm,
  onReject,
  onRejectReasonChange,
}: {
  order: ManualOrder;
  busy: boolean;
  rejectReason: string;
  confirmingReject: boolean;
  onConfirm: () => Promise<void>;
  onReject: () => Promise<void>;
  onRejectReasonChange: (value: string) => void;
}) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const pageLabels = copy.trading.page;
  const isPending = order.status === 'pending_confirm';
  const payload = parsePayload(order.payload_json);
  const decisionId =
    order.risk_decision_id ?? payload?.risk_decision_id ?? null;
  const intentId = order.intent_id ?? payload?.intent_id ?? null;

  return (
    <tr className="border-b border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] align-top transition-colors hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)]">
      <td className="px-3 py-4">
        <div className="font-semibold">{order.symbol}</div>
        <div className="app-muted mt-1 text-xs">
          {formatTimestamp(order.timestamp)}
        </div>
      </td>
      <td className="px-3 py-4">
        <SideBadge side={order.side} />
      </td>
      <td className="px-3 py-4 text-right tabular-nums">
        {formatQuantity(order.quantity)}
      </td>
      <td className="px-3 py-4 text-right tabular-nums">
        {formatPrice(order.price)}
      </td>
      <td className="px-3 py-4">
        <StatusBadge status={order.status} />
      </td>
      <td className="px-3 py-4">
        <div className="space-y-1">
          <div className="font-medium">{labels.riskApproved}</div>
          <div className="app-muted break-all text-xs">
            {labels.decisionId}: {decisionId ?? '--'}
          </div>
          <div className="app-muted break-all text-xs">
            {labels.intentId}: {intentId ?? '--'}
          </div>
          {order.note ? (
            <div className="app-muted text-xs">{order.note}</div>
          ) : null}
        </div>
      </td>
      <td className="px-3 py-4">
        <input
          name={`reject-reason-${order.order_id}`}
          autoComplete="off"
          value={rejectReason}
          onChange={(event) => onRejectReasonChange(event.target.value)}
          placeholder={labels.rejectReasonPlaceholder}
          className="app-field w-full rounded-2xl px-4 py-2.5 text-sm"
          aria-label={`${labels.rejectReason}: ${order.symbol}`}
          disabled={!isPending}
        />
      </td>
      <td className="px-3 py-4">
        {isPending ? (
          <div className="grid gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void onConfirm()}
              className="app-button-primary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              aria-label={`${labels.confirm}: ${order.symbol}`}
            >
              {labels.confirm}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onReject()}
              className="app-button-secondary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              aria-label={`${labels.reject}: ${order.symbol}`}
            >
              {confirmingReject ? pageLabels.rejectConfirm : labels.reject}
            </button>
          </div>
        ) : (
          <div className="app-muted text-xs">{pageLabels.statusCheck}</div>
        )}
      </td>
    </tr>
  );
}

function SideBadge({ side }: { side: string }) {
  const copy = useCopy();
  const labels = copy.trading.page;
  const normalized = side.toLowerCase();
  const isBuy = normalized === 'buy';

  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        isBuy
          ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]'
          : 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]'
      }`}
    >
      {isBuy ? labels.buy : normalized === 'sell' ? labels.sell : side}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels = useCopy().trading.page;
  const warning = status === 'pending_confirm';
  const danger = status === 'rejected' || status === 'canceled';
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        warning
          ? 'bg-[var(--app-warning-bg)] text-[var(--app-warning)] ring-1 ring-[var(--app-warning-border)]'
          : danger
            ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]'
            : 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]'
      }`}
    >
      {statusLabel(status, labels)}
    </span>
  );
}

function AuditRow({ order }: { order: ManualOrder }) {
  return (
    <div className="grid gap-2 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 text-sm sm:grid-cols-[120px_90px_minmax(0,1fr)_160px] sm:items-center">
      <div className="font-semibold">{order.symbol}</div>
      <SideBadge side={order.side} />
      <div className="app-muted min-w-0 truncate text-xs">
        {order.note || order.order_id}
      </div>
      <div className="text-right text-xs tabular-nums text-[var(--app-muted)]">
        {formatTimestamp(order.updated_at)}
      </div>
    </div>
  );
}
