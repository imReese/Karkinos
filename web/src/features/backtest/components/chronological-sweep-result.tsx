import { usePreferences } from '../../../shared/preferences/context';
import { useBacktestResultQuery, type BacktestSweepResponse } from '../api';
import { chronologicalCopy } from '../copy-chronological';
import { MetricsGrid } from './metrics-grid';

export function ChronologicalSweepResult({
  response,
}: {
  response: BacktestSweepResponse;
}) {
  const { locale } = usePreferences();
  const labels = chronologicalCopy[locale];
  const resultId = response.selected_test_result_id ?? null;
  const report = useBacktestResultQuery(resultId);
  const chronology = response.chronological_validation;
  if (!chronology || resultId === null) return null;
  return (
    <section
      aria-label={labels.testTitle}
      className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-4"
    >
      <h4 className="text-base font-semibold">{labels.testTitle}</h4>
      <p className="app-muted text-xs leading-5">
        {labels.selectedTraining}: #
        {chronology.selected_training_result_id ?? '—'} · {labels.savedTest}: #
        {resultId} · {labels.testStart}: {chronology.test_start_date}
      </p>
      {report.isLoading ? (
        <p role="status" className="app-muted text-xs">
          {labels.loading}
        </p>
      ) : report.isError ? (
        <div className="space-y-2 text-xs">
          <p role="alert">{labels.failed}</p>
          <button
            type="button"
            className="app-button-secondary min-h-11 px-3 py-2"
            onClick={() => void report.refetch()}
          >
            {labels.refresh}
          </button>
        </div>
      ) : report.data ? (
        <MetricsGrid report={report.data} compact />
      ) : null}
    </section>
  );
}
