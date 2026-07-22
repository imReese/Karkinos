import type { ReactNode } from 'react';

import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import { formatCurrency, formatPercent } from '../../../shared/format';
import { formatPublicNote } from '../../../shared/public-labels';
import {
  formatStrategyDisplayName,
  type StrategyNameMap,
} from '../../../shared/strategy-display';
import type {
  AfterCostEvidence,
  BacktestReport,
  OutOfSampleValidation,
} from '../api';

function afterCostFromReport(report: BacktestReport): AfterCostEvidence | null {
  const evidence = report.evidence_json ?? report.metrics_json?.evidence_bundle;
  return evidence && Object.keys(evidence).length > 0 ? evidence : null;
}

function oosFromReport(report: BacktestReport): OutOfSampleValidation | null {
  const evidence = report.metrics_json?.oos_validation;
  return evidence && Object.keys(evidence).length > 0 ? evidence : null;
}

function compactTimestamp(value?: string) {
  if (!value) {
    return '--';
  }
  return value.replace('T', ' ').slice(0, 16);
}

function validationTone(status?: string) {
  if (status === 'benchmark_passed') {
    return 'text-[var(--app-success-text)]';
  }
  if (status === 'benchmark_failed') {
    return 'text-[var(--app-danger-text)]';
  }
  return 'text-[var(--app-warning-text)]';
}

function translatedBenchmarkRole(
  role: string | null | undefined,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
  fallback: string,
) {
  if (!role) {
    return fallback;
  }
  return (labels.benchmarkRoleNames as Record<string, string>)[role] ?? role;
}

function strategyDisplayName(
  strategyId: string | null | undefined,
  strategyNames: StrategyNameMap,
  fallback: string,
) {
  if (!strategyId) {
    return fallback;
  }
  return formatStrategyDisplayName({ strategy_id: strategyId }, strategyNames);
}

function strategyAuditId(
  strategyId: string | null | undefined,
  strategyNames: StrategyNameMap,
) {
  const normalized = strategyId?.trim();
  if (!normalized) {
    return null;
  }
  const displayName = strategyDisplayName(
    normalized,
    strategyNames,
    normalized,
  );
  return displayName === normalized ? null : normalized;
}

export function ValidationEvidencePanel({
  report,
}: {
  report: BacktestReport;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.backtest.validationEvidence;
  const pageLabels = copy.backtest.page;
  const afterCost = afterCostFromReport(report);
  const oos = oosFromReport(report);
  const oosStrategyAuditId = strategyAuditId(
    oos?.strategy_id,
    pageLabels.strategyNames,
  );

  if (!afterCost && !oos) {
    return null;
  }

  const assumptions = [
    ...(afterCost?.assumptions ?? []),
    ...(oos?.assumptions ?? []),
  ];
  const limitations = [
    ...(afterCost?.limitations ?? []),
    ...(oos?.limitations ?? []),
  ];

  return (
    <section
      data-backtest-report-section="validation-evidence"
      className="app-workbench-section min-w-0 border-t border-[var(--app-divider)] pt-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <h3 className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {labels.title}
          </h3>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-[var(--app-text-secondary)]">
            {labels.subtitle}
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {afterCost ? (
          <EvidenceBlock title={labels.afterCostTitle}>
            <div className="grid grid-cols-2 gap-2">
              <EvidenceStat
                label={labels.netReturn}
                value={formatPercent(afterCost.net_return)}
              />
              <EvidenceStat
                label={labels.grossReturn}
                value={formatPercent(afterCost.gross_return_before_costs)}
              />
              <EvidenceStat
                label={labels.totalCost}
                value={formatCurrency(afterCost.total_cost)}
              />
              <EvidenceStat
                label={labels.costDrag}
                value={formatPercent(afterCost.cost_to_initial_cash)}
              />
              <EvidenceStat
                label={labels.fills}
                value={labels.fillCount(afterCost.fill_count ?? 0)}
              />
              <EvidenceStat
                label={labels.turnover}
                value={formatCurrency(afterCost.gross_turnover)}
              />
            </div>
          </EvidenceBlock>
        ) : null}

        {oos ? (
          <EvidenceBlock title={labels.oosTitle}>
            <div className="grid grid-cols-2 gap-2">
              <EvidenceStat
                label={labels.strategy}
                value={strategyDisplayName(
                  oos.strategy_id,
                  pageLabels.strategyNames,
                  labels.unknown,
                )}
              />
              {oosStrategyAuditId ? (
                <EvidenceStat
                  label={labels.strategyAuditId}
                  value={oosStrategyAuditId}
                />
              ) : null}
              <EvidenceStat
                label={labels.benchmarkRole}
                value={translatedBenchmarkRole(
                  oos.benchmark_role,
                  pageLabels,
                  labels.unknown,
                )}
              />
              <EvidenceStat
                label={labels.split}
                value={compactTimestamp(oos.split_timestamp)}
              />
              <EvidenceStat
                label={labels.status}
                value={labels.statusValue(
                  oos.validation_status,
                  oos.passed_benchmark,
                )}
                valueClassName={validationTone(oos.validation_status)}
              />
              <EvidenceStat
                label={labels.oosReturn}
                value={formatPercent(oos.out_of_sample?.net_return)}
              />
              <EvidenceStat
                label={labels.excessReturn}
                value={formatPercent(oos.excess_return)}
              />
              <EvidenceStat
                label={labels.benchmarkReturn}
                value={formatPercent(oos.benchmark_return)}
              />
              <EvidenceStat
                label={labels.oosFills}
                value={labels.fillCount(oos.out_of_sample?.fill_count ?? 0)}
              />
            </div>
          </EvidenceBlock>
        ) : null}
      </div>

      {assumptions.length ? (
        <EvidenceList
          title={labels.assumptions}
          items={assumptions}
          locale={locale}
        />
      ) : null}
      {afterCost?.cost_assumptions?.length ? (
        <EvidenceList
          title={labels.costAssumptions}
          items={afterCost.cost_assumptions}
          locale={locale}
        />
      ) : null}
      {afterCost?.slippage_assumptions?.length ? (
        <EvidenceList
          title={labels.slippageAssumptions}
          items={afterCost.slippage_assumptions}
          locale={locale}
        />
      ) : null}
      {limitations.length ? (
        <EvidenceList
          title={labels.limitations}
          items={limitations}
          locale={locale}
        />
      ) : null}
    </section>
  );
}

function EvidenceBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] pt-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {title}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function EvidenceStat({
  label,
  value,
  valueClassName = '',
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="min-w-0 border-l border-[var(--app-divider)] py-1 pl-3">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {label}
      </div>
      <div
        className={`mt-1 truncate text-sm font-semibold tabular-nums ${valueClassName}`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function EvidenceList({
  title,
  items,
  locale,
}: {
  title: string;
  items: string[];
  locale: Locale;
}) {
  return (
    <div className="mt-4 border-t border-[var(--app-divider)] pt-3">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {title}
      </div>
      <ul className="mt-2 space-y-1.5 text-sm leading-6 text-[var(--app-text-secondary)]">
        {items.map((item) => (
          <li key={item}>{formatPublicNote(item, locale)}</li>
        ))}
      </ul>
    </div>
  );
}
