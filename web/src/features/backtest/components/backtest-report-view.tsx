import { ChevronDown } from 'lucide-react';
import { type ReactNode, useEffect, useMemo, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  EvidenceState,
  FilterBar,
  MetricStrip,
  type MetricTone,
} from '../../../shared/ui/workbench';
import {
  formatAmount,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import { StrategyHypothesisPanel } from '../backtest-feature-boundary';
import { DatasetSnapshotPanel } from './dataset-snapshot-panel';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import { FillsTable } from './fills-table';
import { MetricsGrid } from './metrics-grid';
import { StrategyMetadataSnapshotPanel } from './strategy-metadata-snapshot-panel';
import { ValidationEvidencePanel } from './validation-evidence-panel';
import {
  useBacktestResultQuery,
  useBacktestResultsQuery,
  type BacktestSummary,
} from '../api';

function ResultSelector({
  results,
  selectedId,
  onSelect,
}: {
  results: BacktestSummary[];
  selectedId: number | null;
  onSelect: (value: number) => void;
}) {
  const labels = useCopy().backtest.selection;

  return (
    <FilterBar label={labels.kicker}>
      <div className="flex w-full min-w-0 items-center gap-3">
        <div className="shrink-0 text-sm font-semibold text-[var(--app-text)]">
          {labels.title}
        </div>
        <select
          className="app-field min-h-11 min-w-0 flex-1 rounded-[var(--app-radius-control)] px-3 py-2 text-sm sm:ml-auto sm:max-w-[320px]"
          value={selectedId ?? ''}
          onChange={(event) => onSelect(Number(event.target.value))}
          aria-label={labels.ariaLabel}
        >
          {results.map((result) => (
            <option key={result.id} value={result.id}>
              #{result.id} {result.strategy} ·{' '}
              {formatTimestamp(result.created_at)}
            </option>
          ))}
        </select>
      </div>
    </FilterBar>
  );
}

function ReportDisclosure({
  children,
  detail,
  kicker,
  testId,
  title,
}: {
  children: ReactNode;
  detail: string;
  kicker: string;
  testId: string;
  title: string;
}) {
  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid={testId}
    >
      <summary className="flex min-h-16 cursor-pointer list-none items-start justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-kicker app-type-overline block">{kicker}</span>
          <span className="mt-1 block text-sm font-semibold text-[var(--app-text)]">
            {title}
          </span>
          <span className="mt-0.5 block max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
            {detail}
          </span>
        </span>
        <span
          aria-hidden="true"
          className="mt-1 inline-flex size-6 shrink-0 items-center justify-center text-[var(--app-text-secondary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
        >
          <ChevronDown className="size-4" strokeWidth={1.75} />
        </span>
      </summary>
      <div className="border-t border-[var(--app-divider)] py-4 [&>[data-backtest-report-section]]:border-t-0 [&>[data-backtest-report-section]]:pt-0 [&>[data-backtest-report-section]>:first-child]:hidden">
        {children}
      </div>
    </details>
  );
}

function BacktestReportSkeleton({ title }: { title: string }) {
  return (
    <div
      aria-busy="true"
      className="min-w-0 space-y-4"
      data-testid="backtest-report-skeleton"
    >
      <EvidenceState kind="loading" title={title} />
      <section
        aria-hidden="true"
        className="min-w-0 border-y border-[var(--app-divider)] py-4"
        data-testid="backtest-report-skeleton-chart"
      >
        <div className="flex items-end justify-between gap-4">
          <div className="min-w-0 flex-1">
            <span className="block h-2 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
            <span className="mt-2 block h-4 w-40 max-w-[70%] rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
          </div>
          <span className="block h-2 w-14 shrink-0 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
        </div>
        <div className="mt-5 h-52 border-y border-[var(--app-divider)] bg-[linear-gradient(to_right,var(--app-divider)_1px,transparent_1px),linear-gradient(to_bottom,var(--app-divider)_1px,transparent_1px)] bg-[size:25%_100%,100%_25%] opacity-70 sm:h-[320px]" />
      </section>
      <div
        aria-hidden="true"
        className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
        data-testid="backtest-report-skeleton-disclosures"
      >
        {Array.from({ length: 4 }, (_, index) => (
          <div
            className="flex min-h-16 items-center justify-between gap-4 py-3"
            key={index}
          >
            <div className="min-w-0 flex-1">
              <span className="block h-2 w-20 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
              <span className="mt-2 block h-3 w-48 max-w-[72%] rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
            </div>
            <span className="block size-5 shrink-0 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function BacktestReportView() {
  const copy = useCopy();
  const labels = copy.backtest;
  const results = useBacktestResultsQuery();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  useEffect(() => {
    if (selectedId !== null || !results.data?.length) {
      return;
    }
    setSelectedId(results.data[0].id);
  }, [results.data, selectedId]);

  const report = useBacktestResultQuery(selectedId);
  const selectedSummary = useMemo(
    () => results.data?.find((item) => item.id === selectedId) ?? null,
    [results.data, selectedId],
  );

  if (results.isLoading) {
    return <BacktestReportSkeleton title={labels.selection.loading} />;
  }

  if (results.isError) {
    return <EvidenceState kind="error" title={labels.selection.loadFailed} />;
  }

  if (!results.data?.length) {
    return <EvidenceState kind="empty" title={labels.selection.empty} />;
  }

  const summaryReturnTone: MetricTone =
    (selectedSummary?.total_return ?? 0) > 0
      ? 'pnl-positive'
      : (selectedSummary?.total_return ?? 0) < 0
        ? 'pnl-negative'
        : 'neutral';

  return (
    <div data-backtest-report-workspace="saved-evidence" className="space-y-4">
      <ResultSelector
        results={results.data}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {selectedSummary && !report.data ? (
        <MetricStrip
          ariaLabel={labels.selection.kicker}
          className="app-backtest-evidence-strip"
          items={[
            {
              id: 'summary-return',
              label: labels.summary.return,
              value: formatPercent(selectedSummary.total_return),
              tone: summaryReturnTone,
            },
            {
              id: 'summary-sharpe',
              label: labels.summary.sharpe,
              value: formatAmount(selectedSummary.sharpe),
            },
            {
              id: 'summary-max-drawdown',
              label: labels.summary.maxDrawdown,
              value: formatPercent(selectedSummary.max_drawdown),
            },
          ]}
        />
      ) : null}

      {report.isLoading ? (
        <BacktestReportSkeleton title={labels.selection.selectedLoading} />
      ) : report.isError ? (
        <EvidenceState kind="error" title={labels.selection.selectedFailed} />
      ) : report.data ? (
        <>
          <EquityDrawdownChart
            fills={report.data.fills ?? []}
            points={report.data.equity_curve}
          />
          <MetricsGrid report={report.data} />
          <div className="space-y-3">
            <ReportDisclosure
              detail={labels.validationEvidence.subtitle}
              kicker={labels.validationEvidence.kicker}
              testId="backtest-validation-disclosure"
              title={labels.validationEvidence.title}
            >
              <ValidationEvidencePanel report={report.data} />
            </ReportDisclosure>
            <ReportDisclosure
              detail={labels.datasetSnapshot.subtitle}
              kicker={labels.datasetSnapshot.kicker}
              testId="backtest-dataset-disclosure"
              title={labels.datasetSnapshot.title}
            >
              <DatasetSnapshotPanel report={report.data} />
            </ReportDisclosure>
            <ReportDisclosure
              detail={labels.strategySnapshot.subtitle}
              kicker={labels.strategySnapshot.kicker}
              testId="backtest-strategy-evidence-disclosure"
              title={labels.strategySnapshot.title}
            >
              <div className="space-y-5 [&>[data-backtest-report-section]]:border-t-0 [&>[data-backtest-report-section]]:pt-0 [&>[data-backtest-report-section]>:first-child]:hidden">
                <StrategyMetadataSnapshotPanel report={report.data} />
                <StrategyHypothesisPanel report={report.data} />
              </div>
            </ReportDisclosure>
            <ReportDisclosure
              detail={labels.fills.rows(report.data.fills?.length ?? 0)}
              kicker={labels.fills.kicker}
              testId="backtest-fills-disclosure"
              title={labels.fills.title}
            >
              <FillsTable fills={report.data.fills ?? []} />
            </ReportDisclosure>
          </div>
        </>
      ) : null}
    </div>
  );
}
