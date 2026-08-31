import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import type { AppCopy } from '../../../shared/i18n/context';
import { formatInstrumentDisplayLabelFromNameMap } from '../../../shared/instrument-display';
import {
  formatLedgerDashboardPresentation,
  formatLedgerOrderSideLabel,
} from '../../../shared/ledger-format';
import { usePreferences } from '../../../shared/preferences/context';
import { EvidenceState } from '../../../shared/ui/workbench';
import type {
  LedgerEntry,
  ManualOrder,
  MarketDataHealthResponse,
} from '../overview-feature-boundary';
import { OverviewMarketPulse } from './overview-market-pulse';

export function OverviewReviewStrip({
  marketHealth,
  marketHealthLoading,
  marketHealthError,
  orders,
  ordersLoading,
  ordersError,
  entries,
  entriesLoading,
  entriesError,
  copy,
}: {
  marketHealth?: MarketDataHealthResponse;
  marketHealthLoading: boolean;
  marketHealthError: boolean;
  orders: ManualOrder[];
  ordersLoading: boolean;
  ordersError: boolean;
  entries: LedgerEntry[];
  entriesLoading: boolean;
  entriesError: boolean;
  copy: AppCopy;
}) {
  return (
    <div
      className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]"
      data-testid="overview-review-strip"
    >
      <OverviewMarketPulse
        marketHealth={marketHealth}
        isLoading={marketHealthLoading}
        isError={marketHealthError}
      />
      <section className="min-w-0 border-y border-[var(--app-divider)] bg-transparent py-3 sm:py-4">
        <div className="mb-3 flex items-end justify-between gap-3">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.overview.dashboard.pendingApprovals}
          </h2>
          <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
            {copy.overview.dashboard.pendingCount(orders.length)}
          </span>
        </div>
        <DashboardPendingOrders
          orders={orders}
          isLoading={ordersLoading}
          isError={ordersError}
          copy={copy}
        />
        <DashboardLedger
          entries={entries}
          isLoading={entriesLoading}
          isError={entriesError}
          copy={copy}
        />
      </section>
    </div>
  );
}

function DashboardPendingOrders({
  orders,
  isLoading,
  isError,
  copy,
}: {
  orders: ManualOrder[];
  isLoading: boolean;
  isError: boolean;
  copy: AppCopy;
}) {
  const { locale } = usePreferences();
  if (isLoading) {
    return <EvidenceState kind="loading" title={copy.trading.orders.loading} />;
  }
  if (isError) {
    return (
      <EvidenceState kind="error" title={copy.trading.orders.loadFailed} />
    );
  }
  if (orders.length === 0) {
    return (
      <EvidenceState
        kind="empty"
        title={copy.overview.dashboard.pendingEmpty}
        description={copy.overview.dashboard.pendingEmptyDetail}
      />
    );
  }
  return (
    <div className="max-h-[270px] divide-y divide-[var(--app-divider)] overflow-y-auto border-y border-[var(--app-divider)]">
      {orders.map((order) => {
        const normalizedSide = order.side.toLowerCase();
        const sideToneClass =
          normalizedSide === 'buy'
            ? 'border-[color-mix(in_srgb,var(--app-chart-buy)_56%,transparent)] text-[var(--app-chart-buy)]'
            : normalizedSide === 'sell'
              ? 'border-[color-mix(in_srgb,var(--app-chart-sell)_56%,transparent)] text-[var(--app-chart-sell)]'
              : 'border-[var(--app-warning-border)] text-[var(--app-warning-text)]';
        const displayName = order.display_name ?? order.name ?? null;
        const instrumentNames = displayName
          ? new Map([[order.symbol.toLowerCase(), displayName]])
          : undefined;
        return (
          <div
            key={order.order_id}
            className="px-2 py-2.5 transition-colors hover:bg-[var(--app-accent-bg)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="app-type-subsection-title truncate">
                  {formatInstrumentDisplayLabelFromNameMap(
                    order.symbol,
                    instrumentNames,
                  )}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {formatTimestamp(order.timestamp)}
                </div>
              </div>
              <div
                className={`rounded-[var(--app-radius-control)] border bg-transparent px-2 py-1 text-xs font-semibold ${sideToneClass}`}
              >
                {formatLedgerOrderSideLabel(order.side, locale)}
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3 text-xs tabular-nums">
              <MetricLine
                label={copy.trading.orders.quantity}
                value={formatQuantity(order.quantity)}
              />
              <MetricLine
                label={copy.trading.orders.price}
                value={formatPrice(order.price)}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DashboardLedger({
  entries,
  isLoading,
  isError,
  copy,
}: {
  entries: LedgerEntry[];
  isLoading: boolean;
  isError: boolean;
  copy: AppCopy;
}) {
  const { locale } = usePreferences();
  return (
    <div className="mt-4 border-t border-[var(--app-divider)] pt-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {copy.overview.dashboard.ledgerPanel}
        </div>
        <div className="shrink-0 text-xs font-medium text-[var(--app-text-tertiary)] tabular-nums">
          {copy.overview.dashboard.ledgerCount(entries.length)}
        </div>
      </div>
      {isLoading ? (
        <EvidenceState kind="loading" title={copy.states.loading} />
      ) : isError ? (
        <EvidenceState kind="error" title={copy.states.error} />
      ) : entries.length === 0 ? (
        <EvidenceState
          kind="empty"
          title={copy.overview.dashboard.ledgerEmpty}
        />
      ) : (
        <div className="max-h-[340px] divide-y divide-[var(--app-divider)] overflow-y-auto border-y border-[var(--app-divider)]">
          {entries.map((entry) => {
            const presentation = formatLedgerDashboardPresentation(
              entry,
              copy.activity.feed.detailFields,
              locale,
              formatAssetClassLabel(entry.asset_class, copy.common),
            );
            return (
              <div
                key={entry.id}
                className="px-2 py-2.5 transition-colors hover:bg-[var(--app-accent-bg)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">
                      {presentation.title}
                    </div>
                    <div className="app-muted mt-1 text-xs">
                      {formatTimestamp(entry.timestamp)}
                    </div>
                    <div className="app-muted mt-2 flex flex-wrap gap-x-2 gap-y-1 text-xs">
                      {presentation.details.map((detail) => (
                        <span key={detail}>{detail}</span>
                      ))}
                    </div>
                    {presentation.publicNote ? (
                      <div className="app-muted mt-2 break-words text-xs leading-5">
                        {presentation.publicNote}
                      </div>
                    ) : null}
                  </div>
                  <div
                    className="shrink-0 whitespace-nowrap text-right font-mono text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]"
                    data-testid={`dashboard-ledger-amount-${entry.id}`}
                  >
                    {presentation.amount}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <dl className="min-w-0">
      <dt className="text-[length:var(--app-font-size-micro)] font-medium text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd className="mt-0.5 truncate font-mono font-semibold text-[var(--app-text)]">
        {value}
      </dd>
    </dl>
  );
}
