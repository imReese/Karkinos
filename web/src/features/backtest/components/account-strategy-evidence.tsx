import { formatCurrency } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import {
  formatInstrumentDisplayLabelsBySymbol,
  type InstrumentDisplayRecord,
} from '../../../shared/instrument-display';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPublicCode,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import type {
  AccountStrategyAssignment,
  AccountStrategyAttributionSummary,
  AccountStrategyContributionReport,
  BacktestStrategyInfo,
} from '../api';
import {
  accountStrategyPnlAttributionTier,
  lookupLabel,
} from './backtest-page-model';

export function AccountStrategyEvidence({
  attribution,
  attributionError,
  attributionLoading,
  contribution,
  contributionError,
  contributionLoading,
  instruments,
  scopedAssignments,
  scopedAssignmentsError,
  scopedAssignmentsLoading,
  strategyCatalog,
}: {
  attribution: AccountStrategyAttributionSummary | null;
  attributionError: boolean;
  attributionLoading: boolean;
  contribution: AccountStrategyContributionReport | null;
  contributionError: boolean;
  contributionLoading: boolean;
  instruments: InstrumentDisplayRecord[];
  scopedAssignments: AccountStrategyAssignment[];
  scopedAssignmentsError: boolean;
  scopedAssignmentsLoading: boolean;
  strategyCatalog: BacktestStrategyInfo[];
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const visibleScopedAssignments = scopedAssignments
    .filter((item) => item.scope === 'symbol' && item.symbol)
    .slice(0, 4);
  const pnlAttributionTier = accountStrategyPnlAttributionTier(
    attribution,
    contribution,
  );
  const rawAttributionStatus = attribution?.attribution_status ?? 'not_started';
  const rawContributionStatus =
    contribution?.contribution_status ?? 'no_linked_fills';
  const rawAttributionLabel = lookupLabel(
    labels.accountStrategyAttribution,
    rawAttributionStatus,
    formatPublicStatus(rawAttributionStatus, locale),
  );
  const rawContributionLabel = lookupLabel(
    labels.accountStrategyContributionStatusMap,
    rawContributionStatus,
    formatPublicCode(rawContributionStatus, locale),
  );

  return (
    <>
      <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="app-kicker app-type-overline">
            {labels.accountStrategyScopedAssignmentsTitle}
          </div>
          {scopedAssignmentsLoading ? (
            <span className="app-muted text-xs">
              {labels.accountStrategyScopedAssignmentsLoading}
            </span>
          ) : null}
        </div>
        {scopedAssignmentsError ? (
          <p className="mt-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyScopedAssignmentsUnavailable}
          </p>
        ) : visibleScopedAssignments.length ? (
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {visibleScopedAssignments.map((item) => {
              const itemStrategy =
                strategyCatalog.find(
                  (strategyItem) =>
                    strategyItem.strategy_id === item.strategy_id ||
                    strategyItem.name === item.strategy_id,
                ) ?? null;
              return (
                <div
                  className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] px-4 py-3"
                  key={`${item.scope}:${item.symbol}`}
                >
                  <div className="text-sm font-semibold text-[var(--app-text)]">
                    {formatInstrumentDisplayLabelsBySymbol(
                      [item.symbol ?? ''],
                      instruments,
                    )}
                  </div>
                  <div className="app-muted mt-1 text-xs">
                    {strategyDisplayName(
                      itemStrategy ?? {
                        strategy_id: item.strategy_id,
                        name: item.strategy_name,
                      },
                      labels.strategyNames,
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="app-muted mt-3 text-sm">
            {labels.accountStrategyScopedAssignmentsEmpty}
          </p>
        )}
      </div>

      <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
        <div className="app-kicker app-type-overline">
          {labels.accountStrategyPnlAttributionStatus}
        </div>
        <div className="mt-2 text-lg font-semibold text-[var(--app-text)]">
          {lookupLabel(
            labels.accountStrategyPnlAttributionTier,
            pnlAttributionTier,
            pnlAttributionTier,
          )}
        </div>
        <p className="app-muted mt-1 text-sm leading-6">
          {lookupLabel(
            labels.accountStrategyPnlAttributionTierDetail,
            pnlAttributionTier,
            pnlAttributionTier,
          )}
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-1.5 text-[var(--app-muted)]">
            {labels.accountStrategyAttributionSourceStatus}:{' '}
            {rawAttributionLabel}
          </span>
          <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-1.5 text-[var(--app-muted)]">
            {labels.accountStrategyContributionSourceStatus}:{' '}
            {rawContributionLabel}
          </span>
          {rawContributionStatus === 'valuation_missing' ? (
            <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-[var(--app-warning)]">
              {labels.accountStrategyValuationStale}
            </span>
          ) : null}
          {rawAttributionStatus === 'blocked' ? (
            <span className="rounded-full border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-3 py-1.5 text-[var(--app-danger)]">
              {rawAttributionLabel}
            </span>
          ) : null}
        </div>
      </div>

      <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="app-kicker app-type-overline">
            {labels.accountStrategyAttributionEvidence}
          </div>
          {attributionLoading ? (
            <span className="app-muted text-xs">
              {labels.accountStrategyAttributionLoading}
            </span>
          ) : null}
        </div>
        {attributionError ? (
          <p className="mt-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyAttributionUnavailable}
          </p>
        ) : attribution ? (
          <>
            <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <StatusTile
                label={labels.accountStrategySignalActionRisk}
                value={`${attribution.signal_count} / ${attribution.action_count} / ${attribution.risk_decision_count}`}
              />
              <StatusTile
                label={labels.accountStrategyOrdersFills}
                value={`${attribution.order_count} / ${attribution.fill_count}`}
              />
              <StatusTile
                label={labels.accountStrategyPnlStatus}
                value={lookupLabel(
                  labels.accountStrategyAttribution,
                  attribution.attribution_status,
                  formatPublicStatus(attribution.attribution_status, locale),
                )}
              />
              <StatusTile
                label={labels.totalCost}
                value={formatCurrency(attribution.total_fees)}
              />
            </div>
            {attribution.limitations.length ? (
              <div className="mt-3 grid gap-2">
                {attribution.limitations.map((limitation) => (
                  <p
                    className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_14%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
                    key={limitation}
                  >
                    {formatPublicNote(limitation, locale)}
                  </p>
                ))}
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="app-kicker app-type-overline">
            {labels.accountStrategyContributionReport}
          </div>
          {contributionLoading ? (
            <span className="app-muted text-xs">
              {labels.accountStrategyContributionLoading}
            </span>
          ) : null}
        </div>
        {contributionError ? (
          <p className="mt-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyContributionUnavailable}
          </p>
        ) : contribution ? (
          <>
            <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <StatusTile
                label={labels.accountStrategyContributionStatus}
                value={lookupLabel(
                  labels.accountStrategyContributionStatusMap,
                  contribution.contribution_status,
                  formatPublicCode(contribution.contribution_status, locale),
                )}
              />
              <StatusTile
                label={labels.accountStrategyEvidenceBinding}
                value={lookupLabel(
                  labels.accountStrategyEvidenceBindingStatusMap,
                  contribution.evidence_binding_status ?? 'blocked',
                  formatPublicCode(
                    contribution.evidence_binding_status,
                    locale,
                  ),
                )}
              />
              <StatusTile
                label={labels.accountStrategyLedgerPostedFills}
                value={`${contribution.ledger_posted_fill_count ?? 0} / ${contribution.linked_fill_count}`}
              />
              <StatusTile
                label={labels.accountStrategyValuationSnapshot}
                value={contribution.valuation_snapshot_id ?? '--'}
              />
              {pnlAttributionTier === 'complete' ? (
                <>
                  <StatusTile
                    label={labels.accountStrategyGrossRealizedPnl}
                    value={formatCurrency(contribution.gross_realized_pnl)}
                  />
                  <StatusTile
                    label={labels.accountStrategyGrossUnrealizedPnl}
                    value={formatCurrency(contribution.gross_unrealized_pnl)}
                  />
                  <StatusTile
                    label={labels.accountStrategyCommissionSlippage}
                    value={`${formatCurrency(contribution.total_commission)} / ${formatCurrency(contribution.total_slippage)}`}
                  />
                  <StatusTile
                    label={labels.accountStrategyTax}
                    value={formatCurrency(contribution.total_tax)}
                  />
                  <StatusTile
                    label={labels.accountStrategyNetContribution}
                    value={formatCurrency(contribution.net_contribution)}
                  />
                  <StatusTile
                    label={labels.accountStrategyLedgerCutoff}
                    value={String(contribution.ledger_cutoff_id ?? '--')}
                  />
                </>
              ) : null}
            </div>
            {contribution.missing_valuation_symbols.length ? (
              <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                {labels.accountStrategyMissingValuation(
                  formatInstrumentDisplayLabelsBySymbol(
                    contribution.missing_valuation_symbols,
                    instruments,
                  ),
                )}
              </p>
            ) : null}
            {pnlAttributionTier === 'complete' ? null : (
              <div className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm leading-6 text-[var(--app-text)]">
                <div className="text-xs font-semibold text-[var(--app-warning)]">
                  {labels.accountStrategyNextManualAction}
                </div>
                <p className="mt-1">
                  {contribution.next_manual_action
                    ? lookupLabel(
                        labels.accountStrategyNextActionMap,
                        contribution.next_manual_action,
                        formatPublicCode(
                          contribution.next_manual_action,
                          locale,
                        ),
                      )
                    : labels.accountStrategyContributionHiddenUntilEvidence}
                </p>
              </div>
            )}
            {contribution.blockers?.length ? (
              <div className="mt-3 space-y-1 text-xs text-[var(--app-soft)]">
                <div className="font-semibold">
                  {labels.accountStrategyBlockers}
                </div>
                {contribution.blockers.map((blocker) => (
                  <div className="break-words" key={blocker}>
                    {formatPublicNote(blocker, locale)}
                  </div>
                ))}
              </div>
            ) : null}
            {contribution.limitations.length ? (
              <div className="mt-3 grid gap-2">
                {contribution.limitations.map((limitation) => (
                  <p
                    className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_14%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
                    key={limitation}
                  >
                    {formatPublicNote(limitation, locale)}
                  </p>
                ))}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </>
  );
}

export function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3">
      <div className="app-muted text-xs font-semibold">{label}</div>
      <div className="mt-1.5 truncate text-base font-semibold text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}
