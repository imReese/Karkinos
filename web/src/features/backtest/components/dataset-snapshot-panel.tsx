import { ShieldCheck } from 'lucide-react';

import { useCopy } from '../../../app/copy';
import { EvidenceState } from '../../../app/components/workbench';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatTimestamp } from '../../../shared/format';
import {
  isUnconfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
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
    ? 'text-[var(--app-success-text)]'
    : 'text-[var(--app-warning-text)]';
}

function datasetStatusNeedsReview(status?: string | null) {
  const normalized = normalizeMarketDataStatus(status);
  return (
    Boolean(normalized) &&
    normalized !== 'ok' &&
    isUnconfirmedMarketDataStatus(normalized)
  );
}

export function DatasetSnapshotPanel({ report }: { report: BacktestReport }) {
  const copy = useCopy();
  const labels = copy.backtest.datasetSnapshot;
  const common = copy.common;
  const snapshot = snapshotFromReport(report);

  if (!snapshot) {
    return null;
  }

  const firstIssue = snapshot.data_quality.issues[0];
  const hasUnconfirmedData = snapshot.symbol_universe.some((row) =>
    datasetStatusNeedsReview(row.data_quality?.status),
  );
  const datasetIssue = firstIssue
    ? `${firstIssue.symbol ? `${firstIssue.symbol}: ` : ''}${
        firstIssue.message ?? firstIssue.code
      }`
    : hasUnconfirmedData
      ? labels.unconfirmedDataNotice
      : null;

  return (
    <section
      data-backtest-report-section="dataset-snapshot"
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

      <div className="mt-4 grid grid-cols-2 gap-2 xl:grid-cols-5">
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

      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
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

      {datasetIssue ? (
        <EvidenceState kind="partial" title={datasetIssue} className="mt-4" />
      ) : null}

      <div className="mt-4 max-w-full overflow-x-auto overscroll-x-contain border-y border-[var(--app-divider)]">
        <table className="min-w-[860px] w-full text-left text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--app-surface-raised)] text-xs uppercase tracking-[0.12em] text-[var(--app-text-secondary)] shadow-[var(--app-shadow-sticky)]">
            <tr>
              <th className="px-4 py-3 font-semibold">{labels.symbol}</th>
              <th className="px-4 py-3 font-semibold">{labels.assetClass}</th>
              <th className="px-4 py-3 font-semibold">{labels.frequency}</th>
              <th className="px-4 py-3 font-semibold">{labels.rows}</th>
              <th className="px-4 py-3 font-semibold">{labels.dataStatus}</th>
              <th className="px-4 py-3 font-semibold">{labels.providerName}</th>
              <th className="px-4 py-3 font-semibold">{labels.coverage}</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.symbol_universe.map((row) => {
              const rowStatus =
                row.data_quality?.status ?? snapshot.data_quality.status;
              return (
                <tr
                  key={`${row.symbol}-${row.frequency ?? ''}`}
                  className="border-t border-[var(--app-divider)]"
                >
                  <td className="px-4 py-3 font-semibold">{row.symbol}</td>
                  <td className="px-4 py-3">
                    {row.asset_class
                      ? formatAssetClassLabel(row.asset_class, common)
                      : labels.unknown}
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {row.frequency ?? labels.unknown}
                  </td>
                  <td className="px-4 py-3 tabular-nums">{row.row_count}</td>
                  <td
                    className={`px-4 py-3 font-semibold ${qualityTone(
                      normalizeMarketDataStatus(rowStatus),
                    )}`}
                  >
                    {labels.qualityValue(normalizeMarketDataStatus(rowStatus))}
                  </td>
                  <td className="px-4 py-3">
                    {row.provider_name ?? row.data_source ?? labels.unknown}
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {formatTimestamp(row.first_timestamp) ?? labels.unknown}
                    {' -> '}
                    {formatTimestamp(row.last_timestamp) ?? labels.unknown}
                  </td>
                </tr>
              );
            })}
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
    <div className="min-w-0 border-l border-[var(--app-divider)] py-1 pl-3">
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
    <div className="flex min-w-0 items-center justify-between gap-3 border-t border-[var(--app-divider)] py-2">
      <span className="min-w-0 truncate text-xs text-[var(--app-text-secondary)]">
        {label}
      </span>
      <span className="inline-flex items-center gap-1 text-sm font-semibold">
        <ShieldCheck
          className="h-3.5 w-3.5 text-[var(--app-success-indicator)]"
          aria-hidden="true"
        />
        {value}
      </span>
    </div>
  );
}
