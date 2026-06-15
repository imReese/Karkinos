import { BadgeCheck, FlaskConical } from 'lucide-react';
import type { ReactNode } from 'react';

import { useCopy } from '../../../app/copy';
import { formatCurrency, formatPercent } from '../../../shared/format';
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
    return 'text-[#a6e3a1]';
  }
  if (status === 'benchmark_failed') {
    return 'text-[var(--app-danger)]';
  }
  return 'text-[#f9e2af]';
}

export function ValidationEvidencePanel({
  report,
}: {
  report: BacktestReport;
}) {
  const labels = useCopy().backtest.validationEvidence;
  const afterCost = afterCostFromReport(report);
  const oos = oosFromReport(report);

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
    <section className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <h3 className="app-card-title mt-1.5">{labels.title}</h3>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {labels.subtitle}
          </p>
        </div>
        <span className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_30%,transparent)] p-2 text-[var(--app-muted)]">
          <FlaskConical className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {afterCost ? (
          <EvidenceBlock title={labels.afterCostTitle}>
            <div className="grid gap-3 sm:grid-cols-2">
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
            <div className="grid gap-3 sm:grid-cols-2">
              <EvidenceStat
                label={labels.strategy}
                value={oos.strategy_id ?? labels.unknown}
              />
              <EvidenceStat
                label={labels.benchmarkRole}
                value={oos.benchmark_role ?? labels.unknown}
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
        <EvidenceList title={labels.assumptions} items={assumptions} />
      ) : null}
      {limitations.length ? (
        <EvidenceList title={labels.limitations} items={limitations} />
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
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <BadgeCheck className="h-4 w-4 text-[#a6e3a1]" aria-hidden="true" />
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
    <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-2">
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

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-3">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {title}
      </div>
      <ul className="mt-2 space-y-1.5 text-sm leading-6 text-[var(--app-muted)]">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
