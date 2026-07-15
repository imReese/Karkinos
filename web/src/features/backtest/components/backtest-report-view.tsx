import { useEffect, useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
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
    <section className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <div className="app-card-title mt-1.5">{labels.title}</div>
        </div>
        <select
          className="app-field min-w-[260px] rounded-2xl px-4 py-3 text-sm"
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
    </section>
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
    return (
      <div className="app-panel rounded-2xl p-5">
        {labels.selection.loading}
      </div>
    );
  }

  if (results.isError) {
    return (
      <div className="app-panel-danger rounded-2xl p-5">
        {labels.selection.loadFailed}
      </div>
    );
  }

  if (!results.data?.length) {
    return (
      <div className="app-panel rounded-2xl p-5 text-sm text-[var(--app-muted)]">
        {labels.selection.empty}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <ResultSelector
        results={results.data}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />

      {selectedSummary ? (
        <div className="grid gap-3 md:grid-cols-3">
          <div className="app-panel-strong rounded-2xl px-4 py-3 shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
            <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
              {labels.summary.return}
            </div>
            <div className="mt-1.5 text-lg font-semibold tabular-nums">
              {formatPercent(selectedSummary.total_return)}
            </div>
          </div>
          <div className="app-panel-strong rounded-2xl px-4 py-3 shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
            <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
              {labels.summary.sharpe}
            </div>
            <div className="mt-1.5 text-lg font-semibold tabular-nums">
              {formatAmount(selectedSummary.sharpe)}
            </div>
          </div>
          <div className="app-panel-strong rounded-2xl px-4 py-3 shadow-[0_12px_32px_rgba(17,17,27,0.10)]">
            <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
              {labels.summary.maxDrawdown}
            </div>
            <div className="mt-1.5 text-lg font-semibold text-[var(--app-danger)] tabular-nums">
              {formatPercent(selectedSummary.max_drawdown)}
            </div>
          </div>
        </div>
      ) : null}

      {report.isLoading ? (
        <div className="app-panel rounded-2xl p-5">
          {labels.selection.selectedLoading}
        </div>
      ) : report.isError ? (
        <div className="app-panel-danger rounded-2xl p-5">
          {labels.selection.selectedFailed}
        </div>
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
