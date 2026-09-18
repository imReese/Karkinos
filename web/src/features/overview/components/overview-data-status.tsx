import {
  formatCurrency,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  Disclosure,
  Register,
  RegisterRow,
  SectionHeader,
} from '../../../shared/ui/workbench';
import type { AccountStateResponse } from '../overview-feature-boundary';
import {
  overviewPresentation,
  shortDate,
} from '../model/overview-presentation';

function latestPricingDate(
  positions: AccountStateResponse['snapshot']['positions'],
  assetClass: string,
) {
  const dates = positions
    .filter((position) => position.asset_class === assetClass)
    .map((position) => position.pricing_as_of)
    .filter((value): value is string => Boolean(value))
    .sort();
  return dates.length > 0 ? dates[dates.length - 1] : null;
}

export function OverviewDataStatus({ state }: { state: AccountStateResponse }) {
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const { overview, snapshot } = state;
  const usability = overview.valuation_usability;
  const fundDate = latestPricingDate(snapshot.positions, 'fund');
  const stockDate = latestPricingDate(snapshot.positions, 'stock');
  const pendingCount = snapshot.positions.filter(
    (position) => position.market_value == null,
  ).length;
  const closeBasis =
    snapshot.positions.length > 0 &&
    snapshot.positions.every(
      (position) => position.pricing_kind === 'session_close',
    );

  return (
    <div
      data-testid="overview-data-status"
      role="status"
      className="app-type-label flex min-h-9 flex-wrap items-center gap-x-4 gap-y-1 border-b border-[var(--app-divider)] py-2 text-[var(--app-text-secondary)]"
    >
      <span>
        {labels.asOf} {shortDate(overview.pricing_as_of)}
        {closeBasis ? ` ${labels.closeBasis}` : ''} ·{' '}
        {labels[overview.market_session.status]} ·{' '}
        <strong
          className={`font-semibold ${usability === 'usable' ? 'text-[var(--app-text)]' : 'text-[var(--app-warning-text)]'}`}
        >
          {labels[usability]}
        </strong>
      </span>
      {fundDate ? (
        <span className="tabular-nums text-[var(--app-text-tertiary)]">
          {labels.fundsEvidence} {shortDate(fundDate)}
        </span>
      ) : null}
      {stockDate ? (
        <span className="tabular-nums text-[var(--app-text-tertiary)]">
          {labels.stocksEvidence} {shortDate(stockDate)}
        </span>
      ) : null}
      {pendingCount > 0 ? (
        <span className="font-medium tabular-nums text-[var(--app-warning-text)]">
          {labels.pendingHoldingsLabel} {pendingCount}
        </span>
      ) : null}
    </div>
  );
}

export function OverviewMarketStatus({
  state,
}: {
  state: AccountStateResponse;
}) {
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const { overview } = state;
  const refreshLabels = {
    healthy: labels.healthy,
    degraded: labels.refreshDegraded,
    running: labels.running,
    unknown: labels.unknownHealth,
  };
  const rows = [
    [
      labels.latestSession,
      shortDate(overview.market_session.latest_completed_trade_date),
    ],
    [labels.nextSession, shortDate(overview.market_session.next_trading_date)],
    [labels.refreshHealth, refreshLabels[overview.refresh_health.status]],
    [labels.valuationStatus, labels[overview.valuation_usability]],
    [
      labels.decisionReadiness,
      overview.decision_readiness === 'ready'
        ? labels.ready
        : overview.decision_readiness === 'blocked'
          ? labels.blocked
          : labels.unknownHealth,
    ],
  ];

  return (
    <section
      className="min-w-0 py-4"
      data-testid="overview-market-status"
      aria-label={labels.marketAndData}
    >
      <SectionHeader title={labels.marketAndData} className="mb-2" />
      <Register ariaLabel={labels.marketAndData}>
        {rows.map(([label, value]) => (
          <RegisterRow key={label} label={label} value={value ?? '--'} />
        ))}
      </Register>
    </section>
  );
}

export function OverviewDataDetails({
  state,
  refreshFailed,
}: {
  state: AccountStateResponse;
  refreshFailed: boolean;
}) {
  const { locale } = usePreferences();
  const copy = useCopy();
  const labels = overviewPresentation[locale];
  const { overview, snapshot, summary } = state;
  const refreshLabels = {
    healthy: labels.healthy,
    degraded: labels.refreshDegraded,
    running: labels.running,
    unknown: labels.unknownHealth,
  };
  const rows = [
    [
      labels.latestSession,
      shortDate(overview.market_session.latest_completed_trade_date),
    ],
    [labels.nextSession, shortDate(overview.market_session.next_trading_date)],
    [labels.refreshHealth, refreshLabels[overview.refresh_health.status]],
    [
      labels.refreshAttempt,
      formatTimestamp(overview.refresh_health.latest_attempt?.updated_at),
    ],
    [
      labels.decisionReadiness,
      overview.decision_readiness === 'ready'
        ? labels.ready
        : overview.decision_readiness === 'blocked'
          ? labels.blocked
          : labels.unknownHealth,
    ],
    [labels.snapshot, snapshot.valuation_snapshot_id],
    [labels.ledgerCutoff, snapshot.ledger_cutoff_id],
    [labels.ledgerFingerprint, snapshot.ledger_fingerprint],
    [labels.quoteFingerprint, snapshot.quote_set_fingerprint],
    [labels.policy, snapshot.valuation_policy],
  ];
  const blockers = [
    ...new Set([
      ...overview.refresh_health.blockers,
      ...overview.market_session.blockers,
      ...(snapshot.valuation_blockers ?? []),
    ]),
  ];

  return (
    <div className="min-w-0 border-b border-[var(--app-divider)]">
      <Disclosure title={labels.details} testId="overview-data-details">
        <Register ariaLabel={labels.details}>
          {rows.map(([label, value]) => (
            <RegisterRow
              key={String(label)}
              label={label}
              value={value ?? '--'}
              mono={String(label) === labels.snapshot}
            />
          ))}
        </Register>
        {refreshFailed ? (
          <p className="app-type-compact mt-3 text-[var(--app-warning-text)]">
            {labels.stateRefreshFailed}
          </p>
        ) : null}
        {blockers.length > 0 ? (
          <ul className="app-type-compact mt-3 space-y-1 text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        ) : null}
        <a
          className="app-type-compact mt-3 inline-block font-semibold text-[var(--app-accent)] hover:underline"
          href="/market"
        >
          {copy.overview.dashboard.viewData}
        </a>
      </Disclosure>

      <Disclosure title={labels.financialDetails}>
        <Register ariaLabel={labels.financialDetails}>
          <RegisterRow
            label={copy.overview.cards.unrealizedPnl}
            value={formatCurrency(summary.unrealized_pnl)}
          />
          <RegisterRow
            label={copy.overview.breakdown.realizedPnl}
            value={formatCurrency(summary.realized_pnl)}
          />
          <RegisterRow
            label={copy.overview.cards.netDeposits}
            value={formatCurrency(summary.total_deposits)}
          />
          {summary.current_drawdown == null ? null : (
            <RegisterRow
              label={copy.overview.cards.currentDrawdown}
              value={formatPercent(summary.current_drawdown)}
            />
          )}
        </Register>
      </Disclosure>
    </div>
  );
}
