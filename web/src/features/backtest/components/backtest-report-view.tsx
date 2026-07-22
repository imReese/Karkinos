import { useEffect, useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import {
  EvidenceState,
  FilterBar,
  MetricStrip,
  type MetricTone,
} from '../../../app/components/workbench';
import {
  formatAmount,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import { StrategyHypothesisPanel } from '../../ai-research/components/strategy-hypothesis-panel';
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
      <div className="flex w-full min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <div className="app-card-title mt-1.5">{labels.title}</div>
        </div>
        <select
          className="app-field min-h-10 w-full rounded-[var(--app-radius-control)] px-3 py-2 text-sm sm:w-auto sm:min-w-[260px]"
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
    return <EvidenceState kind="loading" title={labels.selection.loading} />;
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

      {selectedSummary ? (
        <MetricStrip
          ariaLabel={labels.selection.kicker}
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
        <EvidenceState
          kind="loading"
          title={labels.selection.selectedLoading}
        />
      ) : report.isError ? (
        <EvidenceState kind="error" title={labels.selection.selectedFailed} />
      ) : report.data ? (
        <>
          <StrategyHypothesisPanel report={report.data} />
          <MetricsGrid report={report.data} />
          <ValidationEvidencePanel report={report.data} />
          <StrategyMetadataSnapshotPanel report={report.data} />
          <DatasetSnapshotPanel report={report.data} />
          <EquityDrawdownChart
            fills={report.data.fills ?? []}
            points={report.data.equity_curve}
          />
          <FillsTable fills={report.data.fills ?? []} />
        </>
      ) : null}
    </div>
  );
}
