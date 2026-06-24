import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import { formatTimestamp } from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import type { LedgerEntry } from '../api';
import {
  formatLedgerActivitySummary,
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  formatLedgerPublicNote,
  formatLedgerSourceLabel,
  type LedgerActivitySummaryTone,
} from '../ledger-format';

export function ActivityFeed({ entries }: { entries: LedgerEntry[] }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.activity.feed;

  if (entries.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-5 text-sm app-muted">
        {labels.empty}
      </div>
    );
  }

  return (
    <div className="app-panel min-w-0 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div>
          <div className="app-product-mark">{labels.kicker}</div>
          <h2 className="mt-2 text-base font-semibold">{labels.title}</h2>
        </div>
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-soft)]">
          {labels.count(entries.length)}
        </span>
      </div>
      <div className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
        <table className="app-data-table w-full min-w-[820px] text-left text-sm">
          <thead>
            <tr>
              <th className="px-5 py-3">{labels.columns.time}</th>
              <th className="px-5 py-3">{labels.columns.activity}</th>
              <th className="px-5 py-3">{labels.columns.instrument}</th>
              <th className="px-5 py-3 text-right">{labels.columns.amount}</th>
              <th className="px-5 py-3">{labels.columns.detail}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const summary = formatLedgerActivitySummary(entry, locale);
              return (
                <tr key={entry.id}>
                  <td className="px-5 py-4 align-top">
                    <div className="font-mono text-xs font-semibold text-[var(--app-soft)]">
                      {formatTimestamp(entry.timestamp)}
                    </div>
                    <div className="app-muted mt-1 text-[11px]">
                      {formatLedgerSourceLabel(entry.source, locale)}
                    </div>
                  </td>
                  <td className="px-5 py-4 align-top">
                    <div className="flex items-center gap-3">
                      <span
                        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold ${activityBadgeClass(summary.tone)}`}
                      >
                        {summary.shortLabel}
                      </span>
                      <div>
                        <div className="font-semibold">{summary.label}</div>
                        <div className="app-muted mt-1 text-xs">
                          {summary.cashImpactLabel}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4 align-top">
                    <div className="font-semibold">
                      {formatLedgerInstrumentLabel(entry) || '--'}
                    </div>
                    <div className="app-muted mt-1 flex items-center gap-2 text-xs">
                      <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]">
                        {formatAssetClass(entry.asset_class, copy)}
                      </span>
                    </div>
                  </td>
                  <td
                    className={`px-5 py-4 text-right align-top font-mono text-sm font-semibold tabular-nums ${activityAmountClass(summary.tone)}`}
                  >
                    {summary.amount}
                    <LedgerExecutionDetails
                      entry={entry}
                      labels={labels}
                      locale={locale}
                    />
                  </td>
                  <td className="max-w-[280px] px-5 py-4 align-top text-[var(--app-muted)]">
                    <span className="line-clamp-2 break-words">
                      {formatLedgerPublicNote(entry, locale) ?? labels.noDetail}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function activityAmountClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'text-[var(--app-success)]';
  }
  if (tone === 'debit') {
    return 'text-[var(--app-danger)]';
  }
  return 'text-[var(--app-soft)]';
}

function activityBadgeClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]';
  }
  if (tone === 'debit') {
    return 'bg-[var(--app-danger-bg)] text-[var(--app-danger)] ring-1 ring-[var(--app-danger-border)]';
  }
  return 'bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-soft)] ring-1 ring-[color-mix(in_srgb,var(--app-border)_34%,transparent)]';
}

function LedgerExecutionDetails({
  entry,
  labels,
  locale,
}: {
  entry: LedgerEntry;
  labels: ReturnType<typeof useCopy>['activity']['feed'];
  locale: ReturnType<typeof usePreferences>['locale'];
}) {
  const details = formatLedgerExecutionDetailLines(
    entry,
    labels.detailFields,
    locale,
  );

  if (details.length === 0) {
    return <div className="app-muted mt-1 text-xs">--</div>;
  }

  return (
    <div className="app-muted mt-1 flex flex-col items-end gap-0.5 text-xs">
      {details.map((item) => (
        <span key={item.label}>
          {item.label} {item.value}
        </span>
      ))}
    </div>
  );
}

function formatAssetClass(
  assetClass: string,
  copy: ReturnType<typeof useCopy>,
) {
  return formatAssetClassLabel(assetClass, copy.common);
}
