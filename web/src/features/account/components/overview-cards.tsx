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
  const evidenceIdentity = [
    overview.valuation_snapshot_id
      ? `snapshot ${overview.valuation_snapshot_id}`
      : 'snapshot --',
    `ledger ${overview.ledger_cutoff_id ?? '--'}`,
    formatDateTime(overview.valuation_as_of ?? overview.valuation_timestamp),
  ].join(' · ');

  return (
    <section
      data-testid="account-metrics-rail"
      className={variant === 'workbench' ? 'min-w-0 self-start' : 'min-w-0'}
    >
      <div data-testid="overview-total-assets-value" className="sr-only">
        {formatCurrency(overview.total_equity)}
      </div>
      <MetricStrip
        items={items}
        ariaLabel={copy.overview.cards.totalAssets}
        className="account-metric-strip font-mono tabular-nums sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-col lg:grid-cols-none"
      />
      <EvidenceState
        kind={evidenceKind}
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
      className="grid min-w-0 animate-pulse overflow-hidden rounded-[var(--app-radius-surface)] border border-[var(--app-border)] bg-[var(--app-surface)] sm:grid-cols-2 lg:grid-cols-6"
    >
      {Array.from({ length: 6 }).map((_, index) => (
        <div
          key={index}
          className="border-b border-[var(--app-divider)] px-3 py-2.5 sm:border-r lg:border-b-0"
        >
          <div className="h-3 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
          <div className="mt-2 h-5 w-28 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
        </div>
      ))}
    </div>
  );
}
