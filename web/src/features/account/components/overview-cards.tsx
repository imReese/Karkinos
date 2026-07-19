import { useCopy } from '../../../app/copy';
import {
  EvidenceState,
  MetricStrip,
  type EvidenceStateKind,
  type MetricStripItem,
} from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import {
  formatCurrency,
  formatDateTime,
  formatPercent,
  formatReturnPercent,
} from '../../../shared/format';
import {
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
import { formatPublicStatus } from '../../../shared/public-labels';
import type { AccountOverview } from '../api';

type OverviewCardMetrics = AccountOverview & {
  today_pnl?: number | null;
  today_pnl_breakdown?: {
    stocks?: number | null;
    funds?: number | null;
    total?: number | null;
  } | null;
  current_drawdown?: number | null;
};

export type TodayPnlContributor = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  today_change: number | null;
};

function metricTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return 'neutral' as const;
  }
  return value > 0 ? ('pnl-positive' as const) : ('pnl-negative' as const);
}

function formatDrawdownPercent(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '--';
  }
  return value === 0
    ? formatReturnPercent(0)
    : `-${formatReturnPercent(value)}`;
}

function valuationEvidenceKind(
  overview: OverviewCardMetrics,
): EvidenceStateKind {
  const valuationStatus = overview.valuation_status ?? overview.quote_status;
  const normalized = normalizeMarketDataStatus(valuationStatus);
  if (!overview.valuation_snapshot_id || normalized === 'missing') {
    return 'missing';
  }
  if (normalized === 'error' || normalized === 'degraded') {
    return 'error';
  }
  if (normalized === 'complete') {
    return 'ready';
  }
  if (isCacheLikeMarketDataStatus(normalized)) {
    return 'stale';
  }
  if (normalized === 'partial' || !isConfirmedMarketDataStatus(normalized)) {
    return 'partial';
  }
  return 'ready';
}

export function OverviewCards({
  overview,
  variant = 'rail',
  todayPnlLabel,
  todayPnlContext,
}: {
  overview: OverviewCardMetrics;
  variant?: 'rail' | 'workbench';
  todayPnlLabel?: string;
  todayPnlContext?: string | null;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const todayPnl =
    overview.today_pnl_breakdown?.total ?? overview.today_pnl ?? null;
  const drawdownPeak =
    typeof overview.drawdown_peak_equity === 'number' &&
    Number.isFinite(overview.drawdown_peak_equity)
      ? formatCurrency(overview.drawdown_peak_equity)
      : '--';
  const items: MetricStripItem[] = [
    {
      id: 'total-assets',
      label: copy.overview.cards.totalAssets,
      value: formatCurrency(overview.total_equity),
      detail: `${copy.overview.cards.netDeposits} ${formatCurrency(
        overview.total_deposits,
      )}`,
    },
    {
      id: 'today-pnl',
      label: todayPnlLabel ?? copy.overview.cards.todayPnl,
      value: formatCurrency(todayPnl),
      detail: todayPnlContext,
      tone: metricTone(todayPnl),
    },
    {
      id: 'unrealized-pnl',
      label: copy.overview.cards.unrealizedPnl,
      value: formatCurrency(overview.unrealized_pnl),
      tone: metricTone(overview.unrealized_pnl),
    },
    {
      id: 'realized-pnl',
      label: copy.portfolio.table.realized,
      value: formatCurrency(overview.realized_pnl),
      tone: metricTone(overview.realized_pnl),
    },
    {
      id: 'cash',
      label: copy.overview.cards.availableCash,
      value: formatCurrency(overview.available_cash),
      detail: `${copy.overview.cards.cashRatio} ${formatPercent(
        overview.cash_ratio,
      )}`,
    },
    {
      id: 'drawdown',
      label: copy.overview.cards.currentDrawdown,
      value: formatDrawdownPercent(overview.current_drawdown),
      detail: `${copy.overview.cards.drawdownPeak} ${drawdownPeak}`,
      tone:
        typeof overview.current_drawdown === 'number' &&
        overview.current_drawdown > 0
          ? 'pnl-negative'
          : 'neutral',
    },
  ];
  const valuationStatus =
    normalizeMarketDataStatus(
      overview.valuation_status ?? overview.quote_status,
    ) ?? 'missing';
  const evidenceKind = valuationEvidenceKind(overview);
  const valuationStatusLabel = formatPublicStatus(valuationStatus, locale);
  const evidenceDescription =
    evidenceKind === 'ready'
      ? copy.overview.cards.valuationStatus(valuationStatusLabel)
      : isCacheLikeMarketDataStatus(valuationStatus)
        ? copy.overview.cards.cachedValuation
        : copy.overview.cards.valuationStatus(valuationStatusLabel);
  const evidenceAsOf = formatDateTime(
    overview.valuation_as_of ?? overview.valuation_timestamp,
  );
  const evidenceIdentity = copy.overview.cards.evidenceIdentity(
    evidenceAsOf,
    overview.ledger_cutoff_id ?? '--',
  );
  const totalAssets = items[0];
  const supportingMetrics = items.slice(1);

  return (
    <section
      data-testid="account-metrics-rail"
      className={variant === 'workbench' ? 'min-w-0 self-start' : 'min-w-0'}
    >
      {variant === 'workbench' ? (
        <div className="account-overview-summary min-w-0">
          <dl
            className="account-primary-metric min-w-0 tabular-nums"
            aria-label={copy.overview.cards.totalAssets}
          >
            <dt className="text-[11px] leading-4 font-medium text-[var(--app-text-secondary)]">
              {totalAssets.label}
            </dt>
            <dd
              data-testid="overview-total-assets-value"
              className="account-primary-metric-value mt-1 truncate text-[1.75rem] leading-8 font-semibold tracking-[-0.035em] text-[var(--app-text)]"
            >
              {totalAssets.value}
            </dd>
            {totalAssets.detail ? (
              <div className="mt-1 truncate text-[11px] leading-4 text-[var(--app-text-tertiary)]">
                {totalAssets.detail}
              </div>
            ) : null}
          </dl>
          <MetricStrip
            items={supportingMetrics}
            ariaLabel={copy.overview.cards.supportingMetrics}
            className="account-metric-strip account-support-metric-strip tabular-nums sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-row lg:grid-cols-5"
          />
        </div>
      ) : (
        <>
          <div data-testid="overview-total-assets-value" className="sr-only">
            {formatCurrency(overview.total_equity)}
          </div>
          <MetricStrip
            items={items}
            ariaLabel={copy.overview.cards.totalAssets}
            className="account-metric-strip tabular-nums sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-col lg:grid-cols-none"
          />
        </>
      )}
      <EvidenceState
        kind={evidenceKind}
        statusLabel={
          evidenceKind === 'ready'
            ? copy.overview.cards.evidenceReady
            : valuationStatusLabel
        }
        title={evidenceDescription}
        description={todayPnlContext}
        evidence={evidenceIdentity}
        className="mt-2"
      />
    </section>
  );
}

export function OverviewCardsSkeleton() {
  return (
    <div
      data-testid="account-metrics-skeleton"
      aria-hidden="true"
      className="account-overview-summary min-w-0 animate-pulse overflow-hidden"
    >
      <div className="account-primary-metric px-3 py-3 sm:px-4">
        <div className="h-3 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
        <div className="mt-2 h-8 w-36 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
        <div className="mt-2 h-3 w-28 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
      </div>
      <div className="account-support-metric-strip grid min-w-0 grid-cols-2 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="app-metric-strip-item px-3 py-2.5">
            <div className="h-3 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
            <div className="mt-2 h-5 w-28 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
          </div>
        ))}
      </div>
    </div>
  );
}
