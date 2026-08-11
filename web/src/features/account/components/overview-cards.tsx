import { useCopy } from '../../../app/copy';
import {
  EvidenceIdentityDisclosure,
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
import type { PortfolioSnapshot } from '../../portfolio/api';
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

export function OverviewSnapshotFallbackCards({
  snapshot,
  todayPnlLabel,
}: {
  snapshot: Pick<
    PortfolioSnapshot,
    | 'cash'
    | 'total_equity'
    | 'total_deposits'
    | 'realized_pnl_total'
    | 'valuation_snapshot_id'
    | 'valuation_as_of'
    | 'valuation_status'
    | 'ledger_cutoff_id'
  >;
  todayPnlLabel?: string;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const loadingValue = (
    <span className="inline-flex min-h-5 items-center">
      <span
        aria-hidden="true"
        className="block h-3 w-16 rounded-[var(--app-radius-control)] bg-[var(--app-divider)]"
      />
      <span className="sr-only">{copy.states.loading}</span>
    </span>
  );
  const supportingMetrics: MetricStripItem[] = [
    {
      id: 'today-pnl',
      label: todayPnlLabel ?? copy.overview.cards.todayPnl,
      value: loadingValue,
    },
    {
      id: 'unrealized-pnl',
      label: copy.overview.cards.unrealizedPnl,
      value: loadingValue,
    },
    {
      id: 'realized-pnl',
      label: copy.portfolio.table.realized,
      value: formatCurrency(snapshot.realized_pnl_total),
      tone: metricTone(snapshot.realized_pnl_total),
    },
    {
      id: 'cash',
      label: copy.overview.cards.availableCash,
      value: formatCurrency(snapshot.cash),
    },
    {
      id: 'drawdown',
      label: copy.overview.cards.currentDrawdown,
      value: loadingValue,
    },
  ];
  const evidenceAsOf = formatDateTime(snapshot.valuation_as_of);

  return (
    <section
      aria-busy="true"
      data-testid="overview-persisted-snapshot-summary"
      className="min-w-0 self-start"
    >
      <div className="account-overview-summary min-w-0">
        <dl
          className="account-primary-metric min-w-0 tabular-nums"
          aria-label={copy.overview.cards.totalAssets}
        >
          <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
            {copy.overview.cards.totalAssets}
          </dt>
          <dd className="account-primary-metric-value app-type-primary-metric mt-1 truncate text-[var(--app-text)]">
            {formatCurrency(snapshot.total_equity)}
          </dd>
          <div className="app-type-micro mt-1 truncate text-[var(--app-text-tertiary)]">
            {copy.overview.cards.netDeposits}{' '}
            {formatCurrency(snapshot.total_deposits)}
          </div>
        </dl>
        <MetricStrip
          items={supportingMetrics}
          ariaLabel={copy.overview.cards.supportingMetrics}
          className="account-metric-strip account-support-metric-strip tabular-nums [contain:layout] sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-row lg:grid-cols-5"
        />
      </div>
      <EvidenceState
        kind="loading"
        statusLabel={copy.states.loading}
        title={copy.portfolio.summary.loading}
        description={copy.portfolio.summary.loadingDetail}
        evidence={copy.overview.cards.evidenceIdentity(evidenceAsOf)}
        action={
          snapshot.valuation_snapshot_id ||
          snapshot.ledger_cutoff_id != null ? (
            <EvidenceIdentityDisclosure
              triggerLabel={copy.common.viewEvidenceIdentity}
              title={copy.common.evidenceIdentityTitle}
              description={copy.common.evidenceIdentityDescription}
              closeLabel={copy.common.closeEvidenceIdentity}
              copyLabel={copy.common.copyEvidenceValue}
              copiedLabel={copy.common.evidenceValueCopied}
              fields={[
                {
                  label: copy.common.valuationSnapshot,
                  value: snapshot.valuation_snapshot_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.ledgerCutoff,
                  value: snapshot.ledger_cutoff_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.valuationAsOf,
                  value: evidenceAsOf,
                  mono: true,
                },
                {
                  label: copy.common.valuationStatus,
                  value: formatPublicStatus(snapshot.valuation_status, locale),
                },
              ]}
            />
          ) : undefined
        }
        className="account-overview-evidence mt-2"
      />
    </section>
  );
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
  const evidenceIdentity = copy.overview.cards.evidenceIdentity(evidenceAsOf);
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
            <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
              {totalAssets.label}
            </dt>
            <dd
              data-testid="overview-total-assets-value"
              className="account-primary-metric-value app-type-primary-metric mt-1 truncate text-[var(--app-text)]"
            >
              {totalAssets.value}
            </dd>
            {totalAssets.detail ? (
              <div className="app-type-micro mt-1 truncate text-[var(--app-text-tertiary)]">
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
        action={
          overview.valuation_snapshot_id ||
          overview.ledger_cutoff_id != null ? (
            <EvidenceIdentityDisclosure
              triggerLabel={copy.common.viewEvidenceIdentity}
              title={copy.common.evidenceIdentityTitle}
              description={copy.common.evidenceIdentityDescription}
              closeLabel={copy.common.closeEvidenceIdentity}
              copyLabel={copy.common.copyEvidenceValue}
              copiedLabel={copy.common.evidenceValueCopied}
              fields={[
                {
                  label: copy.common.valuationSnapshot,
                  value: overview.valuation_snapshot_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.ledgerCutoff,
                  value: overview.ledger_cutoff_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.valuationAsOf,
                  value: evidenceAsOf,
                  mono: true,
                },
                {
                  label: copy.common.valuationStatus,
                  value: valuationStatusLabel,
                },
              ]}
            />
          ) : undefined
        }
        className="account-overview-evidence mt-2"
      />
    </section>
  );
}
