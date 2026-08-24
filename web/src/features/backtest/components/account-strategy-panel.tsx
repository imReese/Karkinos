import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { type InstrumentDisplayRecord } from '../../../shared/instrument-display';
import {
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
import { lookupLabel } from './backtest-page-model';
import {
  AccountStrategyEvidence,
  StatusTile,
} from './account-strategy-evidence';

export function AccountStrategyPanel({
  assignment,
  attribution,
  contribution,
  selectedStrategy,
  strategyCatalog,
  loading,
  error,
  scopedAssignmentsLoading,
  scopedAssignmentsError,
  attributionLoading,
  attributionError,
  contributionLoading,
  contributionError,
  instruments,
  scopedAssignments,
  targetSymbol,
  assigning,
  assigningScoped,
  assignError,
  assignScopedError,
  onAssignSelected,
  onAssignSelectedToSymbol,
}: {
  assignment: AccountStrategyAssignment | null;
  attribution: AccountStrategyAttributionSummary | null;
  contribution: AccountStrategyContributionReport | null;
  selectedStrategy: BacktestStrategyInfo;
  strategyCatalog: BacktestStrategyInfo[];
  loading: boolean;
  error: boolean;
  scopedAssignmentsLoading: boolean;
  scopedAssignmentsError: boolean;
  attributionLoading: boolean;
  attributionError: boolean;
  contributionLoading: boolean;
  contributionError: boolean;
  instruments: InstrumentDisplayRecord[];
  scopedAssignments: AccountStrategyAssignment[];
  targetSymbol: string;
  assigning: boolean;
  assigningScoped: boolean;
  assignError: boolean;
  assignScopedError: boolean;
  onAssignSelected: () => void;
  onAssignSelectedToSymbol: () => void;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const strategyInfo =
    strategyCatalog.find(
      (item) =>
        item.strategy_id === assignment?.strategy_id ||
        item.name === assignment?.strategy_id,
    ) ?? null;
  const strategyName = assignment
    ? strategyDisplayName(
        strategyInfo ?? {
          strategy_id: assignment.strategy_id,
          name: assignment.strategy_name,
        },
        labels.strategyNames,
      )
    : labels.notDeclared;
  const status = assignment
    ? lookupLabel(
        labels.accountStrategyStatus,
        assignment.status,
        formatPublicStatus(assignment.status, locale),
      )
    : labels.notDeclared;
  const assignmentAttributionStatus = assignment
    ? lookupLabel(
        labels.accountStrategyAttribution,
        assignment.attribution_status,
        formatPublicStatus(assignment.attribution_status, locale),
      )
    : labels.notDeclared;
  const scope = assignment
    ? lookupLabel(
        labels.accountStrategyScope,
        assignment.scope,
        formatPublicStatus(assignment.scope, locale),
      )
    : labels.notDeclared;
  const scopeValue =
    assignment?.symbol && assignment.scope === 'symbol'
      ? `${scope} · ${assignment.symbol}`
      : scope;
  const selectedStrategyName = strategyDisplayName(
    selectedStrategy,
    labels.strategyNames,
  );
  const selectedStrategyMatches = (
    currentAssignment: AccountStrategyAssignment | null | undefined,
  ) =>
    currentAssignment?.strategy_id === selectedStrategy.name ||
    currentAssignment?.strategy_id === selectedStrategy.strategy_id;
  const selectedAccountIsAssigned =
    selectedStrategyMatches(assignment) && assignment?.scope === 'account';
  const normalizedTargetSymbol = targetSymbol.trim();
  const targetSymbolAssignment = scopedAssignments.find(
    (item) =>
      item.scope === 'symbol' &&
      (item.symbol ?? '').trim().toLowerCase() ===
        normalizedTargetSymbol.toLowerCase(),
  );
  const selectedSymbolIsAssigned =
    Boolean(normalizedTargetSymbol) &&
    selectedStrategyMatches(targetSymbolAssignment);
  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {labels.accountStrategyKicker}
            </div>
            <h2 className="app-card-title mt-1.5">
              {labels.accountStrategyTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {labels.accountStrategyDetail}
            </p>
          </div>
          <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
            {labels.accountStrategyAutoTradeOff}
          </span>
        </div>

        <div className="mt-4 flex min-w-0 flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
          <p className="app-muted min-w-0 text-sm leading-6">
            {labels.accountStrategySelectedHint(selectedStrategyName)}
          </p>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button
              className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              disabled={
                loading || error || assigning || selectedAccountIsAssigned
              }
              onClick={onAssignSelected}
              type="button"
            >
              {selectedAccountIsAssigned
                ? labels.accountStrategyAssigned
                : assigning
                  ? labels.accountStrategyAssigning
                  : labels.accountStrategyAssignSelected}
            </button>
            <button
              className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
              disabled={
                !normalizedTargetSymbol ||
                scopedAssignmentsLoading ||
                scopedAssignmentsError ||
                assigningScoped ||
                selectedSymbolIsAssigned
              }
              onClick={onAssignSelectedToSymbol}
              type="button"
            >
              {!normalizedTargetSymbol
                ? labels.accountStrategySymbolNeedsInput
                : selectedSymbolIsAssigned
                  ? labels.accountStrategySymbolAssigned
                  : assigningScoped
                    ? labels.accountStrategyAssigning
                    : labels.accountStrategyAssignSelectedSymbol}
            </button>
          </div>
        </div>

        {loading ? (
          <p className="app-muted mt-4 text-sm">
            {labels.accountStrategyLoading}
          </p>
        ) : error ? (
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyUnavailable}
          </p>
        ) : (
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatusTile label={labels.strategy} value={strategyName} />
            <StatusTile label={labels.promotionReadiness} value={status} />
            <StatusTile label={labels.assetUniverse} value={scopeValue} />
            <StatusTile
              label={labels.totalReturn}
              value={assignmentAttributionStatus}
            />
          </div>
        )}

        {assignError ? (
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyAssignFailed}
          </p>
        ) : null}
        {assignScopedError ? (
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyScopedAssignFailed}
          </p>
        ) : null}

        <AccountStrategyEvidence
          attribution={attribution}
          attributionError={attributionError}
          attributionLoading={attributionLoading}
          contribution={contribution}
          contributionError={contributionError}
          contributionLoading={contributionLoading}
          instruments={instruments}
          scopedAssignments={scopedAssignments}
          scopedAssignmentsError={scopedAssignmentsError}
          scopedAssignmentsLoading={scopedAssignmentsLoading}
          strategyCatalog={strategyCatalog}
        />

        <div className="mt-4 grid gap-2">
          <p className="app-muted text-sm">
            {labels.accountStrategyPnlPending}
          </p>
          {assignment?.limitations?.map((limitation) => (
            <p
              className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
              key={limitation}
            >
              {formatPublicNote(limitation, locale)}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}
