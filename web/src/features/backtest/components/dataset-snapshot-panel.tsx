import { Database, ShieldCheck } from 'lucide-react';

import { useCopy } from '../../../app/copy';
import { formatTimestamp } from '../../../shared/format';
import type { BacktestReport, DatasetSnapshot } from '../api';

function boolLabel(
  value: boolean,
  labels: ReturnType<typeof useCopy>['backtest']['datasetSnapshot'],
) {
  return value ? labels.yes : labels.no;
}

function snapshotFromReport(report: BacktestReport): DatasetSnapshot | null {
  return report.metrics_json?.dataset_snapshot ?? null;
}

function qualityTone(status: string) {
  return status === 'ok'
    ? 'text-[#a6e3a1]'
    : 'text-[color-mix(in_srgb,#f9e2af_90%,white)]';
}

export function DatasetSnapshotPanel({ report }: { report: BacktestReport }) {
  const copy = useCopy();
  const labels = copy.backtest.datasetSnapshot;
  const snapshot = snapshotFromReport(report);

  if (!snapshot) {
    return null;
  }

  const firstIssue = snapshot.data_quality.issues[0];

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
          <Database className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <SnapshotStat
          label={labels.snapshotId}
          value={snapshot.snapshot_id}
          mono
        />
        <SnapshotStat
          label={labels.dataSource}
          value={snapshot.provider.configured_source ?? labels.unknown}
        />
        <SnapshotStat
          label={labels.dateRange}
          value={`${snapshot.date_range.start} -> ${snapshot.date_range.end}`}
        />
        <SnapshotStat
          label={labels.rows}
          value={labels.rowsValue(snapshot.row_count)}
        />
        <SnapshotStat
          label={labels.quality}
          value={labels.qualityValue(snapshot.data_quality.status)}
          valueClassName={qualityTone(snapshot.data_quality.status)}
        />
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <BoundaryChip
          label={labels.cacheStore}
          value={boolLabel(snapshot.cache.store_available, labels)}
        />
        <BoundaryChip
          label={labels.cacheMetadata}
          value={boolLabel(snapshot.cache.metadata_available, labels)}
        />
        <BoundaryChip
          label={labels.adjustmentMode}
          value={snapshot.adjustment_mode ?? labels.notAvailable}
        />
      </div>

      {firstIssue ? (
        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,#f9e2af_35%,var(--app-border))] bg-[color-mix(in_srgb,#f9e2af_8%,transparent)] px-4 py-3 text-sm text-[color-mix(in_srgb,#f9e2af_88%,white)]">
          {firstIssue.symbol ? `${firstIssue.symbol}: ` : ''}
          {firstIssue.message ?? firstIssue.code}
        </div>
      ) : null}

      <div className="mt-4 overflow-x-auto rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)]">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] text-xs uppercase tracking-[0.12em] text-[var(--app-muted)]">
            <tr>
              <th className="px-4 py-3 font-semibold">{labels.symbol}</th>
              <th className="px-4 py-3 font-semibold">{labels.assetClass}</th>
              <th className="px-4 py-3 font-semibold">{labels.frequency}</th>
              <th className="px-4 py-3 font-semibold">{labels.rows}</th>
              <th className="px-4 py-3 font-semibold">{labels.providerName}</th>
              <th className="px-4 py-3 font-semibold">{labels.coverage}</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.symbol_universe.map((row) => (
              <tr
                key={`${row.symbol}-${row.frequency ?? ''}`}
                className="border-t border-[color-mix(in_srgb,var(--app-border)_18%,transparent)]"
              >
                <td className="px-4 py-3 font-semibold">{row.symbol}</td>
                <td className="px-4 py-3">
                  {row.asset_class ?? labels.unknown}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {row.frequency ?? labels.unknown}
                </td>
                <td className="px-4 py-3 tabular-nums">{row.row_count}</td>
                <td className="px-4 py-3">
                  {row.provider_name ?? row.data_source ?? labels.unknown}
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {formatTimestamp(row.first_timestamp) ?? labels.unknown}
                  {' -> '}
                  {formatTimestamp(row.last_timestamp) ?? labels.unknown}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SnapshotStat({
  label,
  value,
  mono = false,
  valueClassName = '',
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-3">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {label}
      </div>
      <div
        className={`mt-1.5 truncate text-sm font-semibold ${mono ? 'font-mono' : ''} ${valueClassName}`}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function BoundaryChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2">
      <span className="app-muted min-w-0 truncate text-xs">{label}</span>
      <span className="inline-flex items-center gap-1 text-sm font-semibold">
        <ShieldCheck
          className="h-3.5 w-3.5 text-[#a6e3a1]"
          aria-hidden="true"
        />
        {value}
      </span>
    </div>
  );
}
