import {
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  ControlledActionZone,
  EvidenceState,
  StatusBadge as WorkbenchStatusBadge,
} from '../../../shared/ui/workbench';
import type { ManualOrder } from '../api';
import {
  instrumentDisplayLabel,
  parsePayload,
  statusLabel,
  type InstrumentNameLookup,
} from './trading-execution-format';

export function OrderQueue({
  orders,
  loading,
  error,
  busy,
  rejectReasons,
  confirmingRejectId,
  onConfirm,
  onReject,
  onExportTicket,
  exportingOrderId,
  onRejectReasonChange,
  instrumentNames,
}: {
  orders: ManualOrder[];
  loading: boolean;
  error: boolean;
  busy: boolean;
  rejectReasons: Record<string, string>;
  confirmingRejectId: string | null;
  onConfirm: (orderId: string) => Promise<void>;
  onReject: (orderId: string) => Promise<void>;
  onExportTicket: (orderId: string) => Promise<void>;
  exportingOrderId: string | null;
  onRejectReasonChange: (orderId: string, value: string) => void;
  instrumentNames: InstrumentNameLookup;
}) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const pageLabels = copy.trading.page;

  if (loading) {
    return (
      <EvidenceState
        className="mt-4"
        kind="loading"
        statusLabel={pageLabels.ordersTitle}
        title={labels.loading}
      />
    );
  }
  if (error) {
    return (
      <EvidenceState
        className="mt-4"
        kind="error"
        statusLabel={pageLabels.ordersTitle}
        title={labels.loadFailed}
      />
    );
  }
  if (orders.length === 0) {
    return (
      <EvidenceState
        className="mt-4"
        kind="empty"
        statusLabel={pageLabels.ordersTitle}
        title={labels.empty}
        description={labels.subtitle}
      />
    );
  }

  return (
    <div className="mt-5 min-w-0 max-w-full overflow-x-visible md:overflow-x-auto md:overscroll-x-contain">
      <table className="block w-full text-left text-sm md:table md:min-w-[1100px] md:table-fixed">
        <thead className="hidden md:table-header-group">
          <tr className="app-kicker app-type-overline border-b border-[var(--app-divider)]">
            <th className="w-[150px] px-3 py-3">{labels.symbol}</th>
            <th className="w-[80px] px-3 py-3">{labels.side}</th>
            <th className="w-[90px] px-3 py-3 text-right">{labels.quantity}</th>
            <th className="w-[100px] px-3 py-3 text-right">{labels.price}</th>
            <th className="w-[120px] px-3 py-3">{pageLabels.statusFilter}</th>
            <th className="w-[220px] px-3 py-3">{labels.riskHint}</th>
            <th className="w-[340px] px-3 py-3">{labels.actions}</th>
          </tr>
        </thead>
        <tbody className="block md:table-row-group">
          {orders.map((order) => (
            <OrderRow
              key={order.order_id}
              order={order}
              busy={busy}
              rejectReason={rejectReasons[order.order_id] ?? ''}
              confirmingReject={confirmingRejectId === order.order_id}
              onConfirm={() => onConfirm(order.order_id)}
              onReject={() => onReject(order.order_id)}
              onExportTicket={() => onExportTicket(order.order_id)}
              exportingTicket={exportingOrderId === order.order_id}
              onRejectReasonChange={(value) =>
                onRejectReasonChange(order.order_id, value)
              }
              instrumentNames={instrumentNames}
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
  onExportTicket,
  exportingTicket,
  onRejectReasonChange,
  instrumentNames,
}: {
  order: ManualOrder;
  busy: boolean;
  rejectReason: string;
  confirmingReject: boolean;
  onConfirm: () => Promise<void>;
  onReject: () => Promise<void>;
  onExportTicket: () => Promise<void>;
  exportingTicket: boolean;
  onRejectReasonChange: (value: string) => void;
  instrumentNames: InstrumentNameLookup;
}) {
  const copy = useCopy();
  const labels = copy.trading.orders;
  const pageLabels = copy.trading.page;
  const { locale } = usePreferences();
  const isPending = order.status === 'pending_confirm';
  const payload = parsePayload(order.payload_json);
  const decisionId =
    order.risk_decision_id ?? payload?.risk_decision_id ?? null;
  const intentId = order.intent_id ?? payload?.intent_id ?? null;
  const displayLabel = instrumentDisplayLabel(order, instrumentNames);
  const publicNote = formatPublicOperationalNote(order.note, locale);

  return (
    <tr
      className="grid grid-cols-2 gap-x-4 border-b border-[var(--app-divider)] px-1 py-3 align-top transition-colors hover:bg-[var(--app-surface-raised)] md:table-row md:px-0 md:py-0"
      data-testid={`trading-order-row-${order.order_id}`}
    >
      <td className="col-span-2 block py-2 md:table-cell md:px-3 md:py-4">
        <span className="app-kicker mb-1 block text-[length:var(--app-font-size-micro)] md:hidden">
          {labels.symbol}
        </span>
        <div className="font-semibold">{displayLabel}</div>
        <div className="app-muted mt-1 text-xs">
          {formatTimestamp(order.timestamp)}
        </div>
      </td>
      <td className="block py-2 md:table-cell md:px-3 md:py-4">
        <span className="app-kicker mb-1 block text-[length:var(--app-font-size-micro)] md:hidden">
          {labels.side}
        </span>
        <SideBadge side={order.side} />
      </td>
      <td className="block py-2 text-right tabular-nums md:table-cell md:px-3 md:py-4">
        <span className="app-kicker mb-1 block text-[length:var(--app-font-size-micro)] md:hidden">
          {labels.quantity}
        </span>
        {formatQuantity(order.quantity)}
      </td>
      <td className="block py-2 text-left tabular-nums md:table-cell md:px-3 md:py-4 md:text-right">
        <span className="app-kicker mb-1 block text-[length:var(--app-font-size-micro)] md:hidden">
          {labels.price}
        </span>
        {formatPrice(order.price)}
      </td>
      <td className="block py-2 text-right md:table-cell md:px-3 md:py-4 md:text-left">
        <span className="app-kicker mb-1 block text-[length:var(--app-font-size-micro)] md:hidden">
          {pageLabels.statusFilter}
        </span>
        <StatusBadge status={order.status} />
      </td>
      <td className="col-span-2 block border-t border-[var(--app-divider)] py-3 md:table-cell md:border-t-0 md:px-3 md:py-4">
        <span className="app-kicker mb-1 block text-[length:var(--app-font-size-micro)] md:hidden">
          {labels.riskHint}
        </span>
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
      </td>
      <td className="col-span-2 block pb-2 md:table-cell md:px-3 md:py-4">
        {isPending ? (
          <ControlledActionZone
            tone="info"
            layout="stack"
            title={pageLabels.manualReviewDecision}
            description={pageLabels.manualReviewDecisionDetail}
            evidence={`${labels.decisionId}: ${decisionId ?? '--'} · ${labels.intentId}: ${intentId ?? '--'}`}
          >
            <input
              name={`reject-reason-${order.order_id}`}
              autoComplete="off"
              value={rejectReason}
              onChange={(event) => onRejectReasonChange(event.target.value)}
              placeholder={labels.rejectReasonPlaceholder}
              className="app-field min-h-9 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-xs"
              aria-label={`${labels.rejectReason}: ${displayLabel}`}
            />
            <div className="grid w-full grid-cols-2 gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void onConfirm()}
                className="app-button-primary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
                aria-label={`${labels.confirm}: ${displayLabel}`}
              >
                {labels.confirm}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void onReject()}
                className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
                aria-label={`${labels.reject}: ${displayLabel}`}
              >
                {confirmingReject ? pageLabels.rejectConfirm : labels.reject}
              </button>
            </div>
          </ControlledActionZone>
        ) : order.status === 'confirmed' ? (
          <ControlledActionZone
            tone="info"
            layout="stack"
            title={pageLabels.manualTicketHandoff}
            description={pageLabels.manualTicketExportDetail}
          >
            <button
              type="button"
              disabled={exportingTicket}
              onClick={() => void onExportTicket()}
              className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-45"
              aria-label={`${labels.exportTicket}: ${displayLabel}`}
            >
              {exportingTicket ? labels.exportingTicket : labels.exportTicket}
            </button>
          </ControlledActionZone>
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
  const { locale } = usePreferences();
  const normalized = side.toLowerCase();
  const isBuy = normalized === 'buy';

  return (
    <WorkbenchStatusBadge tone={isBuy ? 'info' : 'neutral'}>
      {isBuy
        ? labels.buy
        : normalized === 'sell'
          ? labels.sell
          : formatPublicStatus(side, locale)}
    </WorkbenchStatusBadge>
  );
}

function StatusBadge({ status }: { status: string }) {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  const warning = status === 'pending_confirm';
  const danger = status === 'rejected' || status === 'canceled';
  return (
    <WorkbenchStatusBadge
      tone={warning ? 'warning' : danger ? 'danger' : 'success'}
    >
      {statusLabel(status, labels, locale)}
    </WorkbenchStatusBadge>
  );
}

export function AuditRow({
  order,
  instrumentNames,
}: {
  order: ManualOrder;
  instrumentNames: InstrumentNameLookup;
}) {
  const { locale } = usePreferences();
  const labels = useCopy().trading.page;
  const displayLabel = instrumentDisplayLabel(order, instrumentNames);
  const publicNote =
    formatPublicOperationalNote(order.note, locale) ?? labels.noPublicAuditNote;
  return (
    <div className="grid gap-2 px-1 py-3 text-sm sm:grid-cols-[140px_90px_minmax(0,1fr)_160px] sm:items-center">
      <div className="font-semibold">{displayLabel}</div>
      <SideBadge side={order.side} />
      <div className="app-muted min-w-0 truncate text-xs">{publicNote}</div>
      <div className="text-right text-xs tabular-nums text-[var(--app-muted)]">
        {formatTimestamp(order.updated_at)}
      </div>
    </div>
  );
}
