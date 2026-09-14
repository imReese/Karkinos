import {
  formatCurrency,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { AccountStateResponse } from '../overview-feature-boundary';
import {
  overviewPresentation,
  shortDate,
} from '../model/overview-presentation';

export function OverviewDataStatus({ state }: { state: AccountStateResponse }) {
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];
  const { overview } = state;
  const usability = overview.valuation_usability;
  const closeBasis =
    state.snapshot.positions.length > 0 &&
    state.snapshot.positions.every(
      (position) => position.pricing_kind === 'session_close',
    );
  return (
    <div
      data-testid="overview-data-status"
      role="status"
      className={`text-xs leading-6 ${usability === 'usable' ? 'text-[var(--app-text-secondary)]' : 'border-l-2 border-[var(--app-warning)] pl-3 text-[var(--app-warning-text)]'}`}
    >
      {labels.asOf} {shortDate(overview.pricing_as_of)}
      {closeBasis ? ` ${labels.closeBasis}` : ''} ·{' '}
      {labels[overview.market_session.status]} · {labels[usability]}
    </div>
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
  return (
    <div className="border-t border-[var(--app-divider)]">
      <details className="group py-4" data-testid="overview-data-details">
        <summary className="cursor-pointer text-sm font-semibold text-[var(--app-text)]">
          {labels.details}
        </summary>
        <dl className="mt-4 space-y-3 text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-[var(--app-text-tertiary)]">{label}</dt>
              <dd className="mt-1 break-all tabular-nums text-[var(--app-text-secondary)]">
                {value ?? '--'}
              </dd>
            </div>
          ))}
        </dl>
        {refreshFailed ? (
          <p className="mt-3 text-xs leading-5 text-[var(--app-warning-text)]">
            {labels.stateRefreshFailed}
          </p>
        ) : null}
        {[
          ...overview.refresh_health.blockers,
          ...overview.market_session.blockers,
          ...(snapshot.valuation_blockers ?? []),
        ].length > 0 ? (
          <ul className="mt-3 space-y-1 break-words text-xs text-[var(--app-text-secondary)]">
            {[
              ...new Set([
                ...overview.refresh_health.blockers,
                ...overview.market_session.blockers,
                ...(snapshot.valuation_blockers ?? []),
              ]),
            ].map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        ) : null}
        <a
          className="mt-4 inline-block text-xs text-[var(--app-accent)] hover:underline"
          href="/market"
        >
          {copy.overview.dashboard.viewData}
        </a>
      </details>
      <details className="border-t border-[var(--app-divider)] py-4">
        <summary className="cursor-pointer text-sm font-semibold text-[var(--app-text)]">
          {labels.financialDetails}
        </summary>
        <dl className="mt-3 space-y-2 text-xs">
          {[
            [
              copy.overview.cards.unrealizedPnl,
              formatCurrency(summary.unrealized_pnl),
            ],
            [
              copy.portfolio.table.realized,
              formatCurrency(summary.realized_pnl),
            ],
            [
              copy.overview.cards.netDeposits,
              formatCurrency(summary.total_deposits),
            ],
            ...(summary.current_drawdown == null
              ? []
              : [
                  [
                    copy.overview.cards.currentDrawdown,
                    formatPercent(summary.current_drawdown),
                  ],
                ]),
          ].map(([label, value]) => (
            <div className="flex justify-between gap-3" key={label}>
              <dt className="text-[var(--app-text-secondary)]">{label}</dt>
              <dd className="tabular-nums text-[var(--app-text)]">{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}
