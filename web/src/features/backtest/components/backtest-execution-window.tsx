import { usePreferences } from '../../../shared/preferences/context';
import type { BacktestReport } from '../api';
import { chronologicalCopy } from '../copy-chronological';

export function BacktestExecutionWindowPanel({
  report,
}: {
  report: BacktestReport;
}) {
  const { locale } = usePreferences();
  const labels = chronologicalCopy[locale];
  const window = report.metrics_json?.execution_window;
  const chronology = report.metrics_json?.chronological_validation;
  if (!window) return null;
  return (
    <section
      aria-label={labels.performance}
      className="min-w-0 space-y-2 py-3 text-xs leading-5"
    >
      <h4 className="font-semibold">
        {labels.performance}
        {chronology?.role ? ` · ${labels[chronology.role]}` : ''}
      </h4>
      <p className="font-medium tabular-nums">
        {labels.metricDates}:{' '}
        {window.metric_start_date && window.metric_end_date
          ? `${window.metric_start_date} → ${window.metric_end_date}`
          : labels.noDates}
      </p>
      <p className="app-muted">{labels.warmup}</p>
      <p className="app-muted">{labels.boundary}</p>
      <details className="min-w-0">
        <summary className="cursor-pointer text-[var(--app-text-secondary)]">
          {labels.evidence}
        </summary>
        <dl className="mt-2 space-y-2">
          {[
            [
              labels.evaluationDates,
              `${window.evaluation_start_date} → ${window.evaluation_end_date}`,
            ],
            [
              labels.datasetDates,
              `${window.source_start_date} → ${window.source_end_date}`,
            ],
            [labels.historyEnd, window.history_end_date],
            [labels.source, window.source_dataset_id],
            [labels.snapshot, window.source_snapshot_id],
            [labels.experiment, chronology?.experiment_id],
            [labels.fingerprint, window.fingerprint],
          ].map(([label, value]) =>
            value ? (
              <div key={label}>
                <dt className="app-muted">{label}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ) : null,
          )}
        </dl>
      </details>
    </section>
  );
}
