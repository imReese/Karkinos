import { useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import {
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatLedgerEntryTypeLabel } from '../../../shared/ledger-format';
import { usePositionsQuery } from '../../portfolio/api';
import {
  useConfirmManualOrderMutation,
  usePendingManualOrdersQuery,
  useRejectManualOrderMutation,
  type ManualOrder,
} from '../api';

export function OrderApprovalTable() {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const orders = usePendingManualOrdersQuery();
  const positions = usePositionsQuery();
  const confirmOrder = useConfirmManualOrderMutation();
  const rejectOrder = useRejectManualOrderMutation();
  const [rejectReasons, setRejectReasons] = useState<Record<string, string>>(
    {},
  );
  const [rowError, setRowError] = useState<string | null>(null);

  const pendingOrders = useMemo(() => orders.data ?? [], [orders.data]);
  const instrumentNames = useMemo(
    () =>
      new Map(
        (positions.data ?? []).map((position) => [
          position.symbol,
          position.display_name ?? position.name ?? position.symbol,
        ]),
      ),
    [positions.data],
  );

  const handleConfirm = async (orderId: string) => {
    setRowError(null);
    await confirmOrder.mutateAsync({ orderId });
  };

  const handleReject = async (orderId: string) => {
    const reason = (rejectReasons[orderId] ?? '').trim();
    if (!reason) {
      setRowError(labels.rejectReasonRequired);
      return;
    }
    setRowError(null);
    await rejectOrder.mutateAsync({ orderId, reason });
    setRejectReasons((current) => {
      const next = { ...current };
      delete next[orderId];
      return next;
    });
  };

  return (
    <section className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.kicker}
          </div>
          <h2 className="mt-2 text-lg font-semibold">{labels.title}</h2>
          <p className="app-muted mt-2 text-sm">{labels.subtitle}</p>
        </div>
        <div className="app-panel-strong rounded-2xl px-3 py-2 text-sm font-semibold tabular-nums shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
          {labels.pendingCount(pendingOrders.length)}
        </div>
      </div>

      {orders.isLoading ? (
        <div className="app-muted mt-5 text-sm">{labels.loading}</div>
      ) : orders.isError ? (
        <div className="app-error-text mt-5 text-sm">{labels.loadFailed}</div>
      ) : pendingOrders.length === 0 ? (
        <div className="app-panel-strong mt-5 rounded-2xl px-4 py-4 text-sm shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
          {labels.empty}
        </div>
      ) : (
        <div className="mt-5 min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
          <table className="min-w-[920px] table-fixed text-left text-sm">
            <thead>
              <tr className="app-kicker border-b border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] text-[11px] uppercase tracking-[0.16em]">
                <th className="w-[180px] px-3 py-3">{labels.symbol}</th>
                <th className="w-[90px] px-3 py-3">{labels.side}</th>
                <th className="w-[110px] px-3 py-3">{labels.quantity}</th>
                <th className="w-[110px] px-3 py-3">{labels.price}</th>
                <th className="w-[220px] px-3 py-3">{labels.riskHint}</th>
                <th className="w-[180px] px-3 py-3">{labels.rejectReason}</th>
                <th className="w-[170px] px-3 py-3">{labels.actions}</th>
              </tr>
            </thead>
            <tbody>
              {pendingOrders.map((order) => {
                const busy = confirmOrder.isPending || rejectOrder.isPending;
                const displayLabel = formatInstrumentDisplayLabel({
                  symbol: order.symbol,
                  display_name:
                    order.display_name ??
                    order.name ??
                    instrumentNames.get(order.symbol) ??
                    null,
                });
                return (
                  <tr
                    key={order.order_id}
                    className="border-b border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] align-top"
                  >
                    <td className="px-3 py-4">
                      <div className="break-words font-semibold">
                        {displayLabel}
                      </div>
                      <div className="app-muted mt-1 text-xs">
                        {formatTimestamp(order.timestamp)}
                      </div>
                    </td>
                    <td className="px-3 py-4">
                      <SideBadge side={order.side} />
                    </td>
                    <td className="px-3 py-4 tabular-nums">
                      {formatQuantity(order.quantity)}
                    </td>
                    <td className="px-3 py-4 tabular-nums">
                      {formatPrice(order.price)}
                    </td>
                    <td className="px-3 py-4">
                      <RiskHint order={order} />
                    </td>
                    <td className="px-3 py-4">
                      <input
                        value={rejectReasons[order.order_id] ?? ''}
                        onChange={(event) =>
                          setRejectReasons((current) => ({
                            ...current,
                            [order.order_id]: event.target.value,
                          }))
                        }
                        placeholder={labels.rejectReasonPlaceholder}
                        className="app-field w-full rounded-2xl px-4 py-2.5 text-sm"
                        aria-label={`${labels.rejectReason}: ${displayLabel}`}
                      />
                    </td>
                    <td className="px-3 py-4">
                      <div className="grid gap-2">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleConfirm(order.order_id)}
                          className="app-button-primary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          {labels.confirm}
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void handleReject(order.order_id)}
                          className="app-button-secondary rounded-2xl px-3.5 py-2.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          {labels.reject}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {rowError ? (
        <div className="app-error-text mt-3 text-sm">{rowError}</div>
      ) : null}
      {confirmOrder.isError ? (
        <div className="app-error-text mt-3 text-sm">
          {getErrorMessage(confirmOrder.error)}
        </div>
      ) : null}
      {rejectOrder.isError ? (
        <div className="app-error-text mt-3 text-sm">
          {getErrorMessage(rejectOrder.error)}
        </div>
      ) : null}
    </section>
  );
}

function SideBadge({ side }: { side: string }) {
  const { locale } = usePreferences();
  const normalized = side.toLowerCase();
  const isBuy = normalized === 'buy';
  const isSell = normalized === 'sell';
  const toneClass = isBuy
    ? 'bg-red-500/15 text-red-300 ring-1 ring-red-500/35'
    : isSell
      ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/35'
      : 'bg-[var(--app-warning-bg)] text-[var(--app-warning)] ring-1 ring-[var(--app-warning-border)]';
  const label = isBuy
    ? formatLedgerEntryTypeLabel('trade_buy', locale)
    : isSell
      ? formatLedgerEntryTypeLabel('trade_sell', locale)
      : formatPublicStatus(side, locale);

  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${toneClass}`}
    >
      {label}
    </span>
  );
}

function RiskHint({ order }: { order: ManualOrder }) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const { locale } = usePreferences();
  const orderPayload = parsePayload(order.payload_json);
  const decisionId =
    order.risk_decision_id ?? orderPayload?.risk_decision_id ?? null;
  const intentId = order.intent_id ?? orderPayload?.intent_id ?? null;
  const publicNote = formatPublicOperationalNote(order.note, locale);

  return (
    <div className="space-y-1">
      <div className="font-medium">{labels.riskApproved}</div>
      <div className="app-muted break-all text-xs">
        {labels.decisionId}: {decisionId ?? '--'}
      </div>
      <div className="app-muted break-all text-xs">
        {labels.intentId}: {intentId ?? '--'}
      </div>
      {publicNote ? (
        <div className="app-muted text-xs">{publicNote}</div>
      ) : null}
    </div>
  );
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
