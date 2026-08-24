import { useMemo } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPublicCode,
  formatPublicCodeList,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import type {
  BacktestStrategyInfo,
  StrategyPromotionReadiness,
  StrategyValidationMatrix,
  StrategyValidationRow,
} from '../api';
import { formatGateScore } from './backtest-page-model';

export function StrategyEvidenceGatePanel({
  strategyCatalog,
  validation,
  readiness,
  loading,
  error,
}: {
  strategyCatalog: BacktestStrategyInfo[];
  validation: StrategyValidationMatrix | null;
  readiness: StrategyPromotionReadiness | null;
  loading: boolean;
  error: boolean;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const validationRows = validation?.rows ?? [];
  const readinessRows = readiness?.rows ?? [];
  const visibleRows = useMemo(() => {
    const rowsByStrategy = new Map<string, StrategyValidationRow>();
    validationRows.forEach((row) => {
      rowsByStrategy.set(row.strategy_id, row);
    });
    readinessRows.forEach((row) => {
      if (rowsByStrategy.has(row.strategy_id)) {
        return;
      }

      rowsByStrategy.set(row.strategy_id, {
        strategy_id: row.strategy_id,
        benchmark_role: row.benchmark_role,
        requires_out_of_sample_validation: true,
        requires_after_cost_report: true,
        has_out_of_sample_validation: row.has_after_cost_and_oos_evidence,
        has_after_cost_report: row.has_after_cost_and_oos_evidence,
        validation_status: null,
        backtest_result_id: row.backtest_result_id,
        missing_requirements: [],
        is_ready: row.has_after_cost_and_oos_evidence,
      });
    });
    return Array.from(rowsByStrategy.values());
  }, [validationRows, readinessRows]);
  const strategyById = useMemo(
    () =>
      new Map(
        strategyCatalog.flatMap((strategy) => [
          [strategy.strategy_id, strategy],
          [strategy.name, strategy],
        ]),
      ),
    [strategyCatalog],
  );

  return (
    <section className="app-workbench-section min-w-0 overflow-hidden">
      <div className="min-w-0 p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.evidenceGate}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.evidenceGateTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl break-words text-sm leading-6">
              {labels.evidenceGateDetail}
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-2 text-right text-xs tabular-nums sm:min-w-72">
            <EvidenceCount
              label={labels.validationMatrix}
              value={
                validation
                  ? `${validation.ready_strategy_count}/${validation.required_strategy_count}`
                  : '--'
              }
            />
            <EvidenceCount
              label={labels.promotionReadiness}
              value={
                readiness
                  ? `${readiness.promotable_strategy_count}/${readiness.required_strategy_count}`
                  : '--'
              }
            />
          </div>
        </div>

        {loading ? (
          <div className="app-muted mt-4 text-sm">
            {labels.evidenceGateLoading}
          </div>
        ) : error ? (
          <div className="app-error-text mt-4 text-sm">
            {labels.evidenceGateFailed}
          </div>
        ) : visibleRows.length === 0 ? (
          <div className="app-muted mt-4 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] px-4 py-5 text-sm">
            {labels.noEvidenceRows}
          </div>
        ) : (
          <div className="mt-4 min-w-0 overflow-x-auto overscroll-x-contain">
            <table className="min-w-[1060px] table-fixed text-left text-sm">
              <thead>
                <tr className="app-kicker app-type-overline border-b border-[color-mix(in_srgb,var(--app-border)_28%,transparent)]">
                  <th className="w-[190px] px-3 py-3">{labels.strategy}</th>
                  <th className="w-[150px] px-3 py-3">
                    {labels.validationMatrix}
                  </th>
                  <th className="w-[170px] px-3 py-3">
                    {labels.promotionReadiness}
                  </th>
                  <th className="w-[170px] px-3 py-3">
                    {labels.accountTruthGate}
                  </th>
                  <th className="w-[170px] px-3 py-3">
                    {labels.strategyAttributionGate}
                  </th>
                  <th className="px-3 py-3">{labels.missingRequirements}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => {
                  const readinessRow = readinessRows.find(
                    (item) => item.strategy_id === row.strategy_id,
                  );
                  const strategyInfo = strategyById.get(row.strategy_id);
                  const displayName = strategyInfo
                    ? strategyDisplayName(strategyInfo, labels.strategyNames)
                    : strategyDisplayName(
                        { strategy_id: row.strategy_id, name: row.strategy_id },
                        labels.strategyNames,
                      );
                  const missing = [
                    ...row.missing_requirements,
                    ...(readinessRow?.missing_requirements ?? []),
                  ];
                  return (
                    <tr
                      key={row.strategy_id}
                      className="border-b border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] align-top"
                    >
                      <td className="px-3 py-3">
                        <div className="font-semibold text-[var(--app-text)]">
                          {displayName}
                        </div>
                        <div className="app-muted mt-1 break-all font-mono text-xs tabular-nums">
                          {row.strategy_id}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <EvidenceBadge complete={row.is_ready}>
                          {row.is_ready ? labels.complete : labels.incomplete}
                        </EvidenceBadge>
                      </td>
                      <td className="px-3 py-3">
                        <EvidenceBadge
                          complete={Boolean(readinessRow?.is_promotable)}
                        >
                          {readinessRow
                            ? formatPublicStatus(
                                readinessRow.promotion_status,
                                locale,
                              )
                            : labels.notDeclared}
                        </EvidenceBadge>
                      </td>
                      <td className="px-3 py-3 text-xs leading-5">
                        <div className="font-semibold text-[var(--app-text)]">
                          {readinessRow
                            ? formatPublicStatus(
                                readinessRow.account_truth_gate_status,
                                locale,
                              )
                            : labels.notDeclared}{' '}
                          ·{' '}
                          {formatGateScore(
                            readinessRow?.account_truth_score ?? null,
                          )}
                        </div>
                        <div className="app-muted mt-1">
                          {readinessRow?.has_account_truth_evidence
                            ? labels.accountTruthEvidencePresent
                            : labels.accountTruthEvidenceMissing}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs leading-5">
                        <div className="break-words font-semibold text-[var(--app-text)]">
                          {readinessRow
                            ? formatPublicCode(
                                readinessRow.strategy_attribution_status,
                                locale,
                              )
                            : labels.notDeclared}
                        </div>
                        <div className="app-muted mt-1">
                          {readinessRow?.has_strategy_attribution_evidence
                            ? labels.strategyAttributionReady
                            : labels.strategyAttributionPending}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs leading-5 text-[var(--app-muted)]">
                        {missing.length > 0
                          ? formatPublicCodeList(
                              Array.from(new Set(missing)),
                              locale,
                            ).join(' · ')
                          : labels.none}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

export function EvidenceCount({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2">
      <div className="app-muted app-type-micro">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}

export function EvidenceBadge({
  complete,
  children,
}: {
  complete: boolean;
  children: string;
}) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        complete
          ? 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]'
          : 'bg-[var(--app-warning-bg)] text-[var(--app-warning)] ring-1 ring-[var(--app-warning-border)]'
      }`}
    >
      {children}
    </span>
  );
}
