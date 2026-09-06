import {
  LedgerCorrectionDetails,
  LedgerEntryTime,
} from '../../../shared/ledger-correction-details';
import { isLedgerCorrection } from '../../../shared/ledger-format-values';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import type { useCopy } from '../../../shared/i18n/context';
import type { usePreferences } from '../../../shared/preferences/context';
import type { LedgerEntry } from '../api';
import {
  formatLedgerActivitySummary,
  formatLedgerPublicNote,
  formatLedgerSourceLabel,
  formatLedgerExecutionDetailLines,
  formatLedgerInstrumentLabel,
  type LedgerActivitySummaryTone,
} from '../ledger-format';

export function ActivityInstrument({
  copy,
  entry,
  labels,
  locale,
}: {
  copy: ReturnType<typeof useCopy>;
  entry: LedgerEntry;
  labels: ReturnType<typeof useCopy>['activity']['feed'];
  locale: ReturnType<typeof usePreferences>['locale'];
}) {
  return (
    <div className="min-w-0">
      {entry.symbol ? (
        <a
          href={`/portfolio/${encodeURIComponent(entry.symbol)}`}
          className="break-words font-semibold text-[var(--app-text)] underline-offset-4 transition-colors hover:text-[var(--app-accent)] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
          aria-label={labels.openHoldingDetail(entry.symbol)}
        >
          {formatLedgerInstrumentLabel(entry, locale) || entry.symbol}
        </a>
      ) : (
        <div className="font-semibold">--</div>
      )}
      <div className="app-muted mt-1 flex items-center gap-2 text-xs">
        <span className="app-type-overline rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2 py-0.5">
          {formatAssetClass(entry.asset_class, copy)}
        </span>
      </div>
    </div>
  );
}

export function activityAmountClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'text-[var(--app-pnl-positive)]';
  }
  if (tone === 'debit') {
    return 'text-[var(--app-pnl-negative)]';
  }
  return 'text-[var(--app-pnl-neutral)]';
}

export function activityBadgeClass(tone: LedgerActivitySummaryTone) {
  if (tone === 'credit') {
    return 'bg-[color-mix(in_srgb,var(--app-pnl-positive)_10%,transparent)] text-[var(--app-pnl-positive)] ring-1 ring-[color-mix(in_srgb,var(--app-pnl-positive)_38%,transparent)]';
  }
  if (tone === 'debit') {
    return 'bg-[color-mix(in_srgb,var(--app-pnl-negative)_10%,transparent)] text-[var(--app-pnl-negative)] ring-1 ring-[color-mix(in_srgb,var(--app-pnl-negative)_38%,transparent)]';
  }
  return 'bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-soft)] ring-1 ring-[color-mix(in_srgb,var(--app-border)_34%,transparent)]';
}

export function LedgerExecutionDetails({
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
    return <div className="app-muted app-type-micro mt-1">--</div>;
  }

  return (
    <div className="app-muted app-type-label mt-1 ml-auto flex max-w-[240px] flex-wrap items-center justify-end gap-x-2 gap-y-0.5">
      {details.map((item) => (
        <span key={item.label} className="whitespace-nowrap">
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

export function ActivityLedgerRow({
  entry,
  copy,
  labels,
  locale,
}: {
  entry: LedgerEntry;
  copy: ReturnType<typeof useCopy>;
  labels: ReturnType<typeof useCopy>['activity']['feed'];
  locale: ReturnType<typeof usePreferences>['locale'];
}) {
  const correction = isLedgerCorrection(entry);
  const summary = formatLedgerActivitySummary(entry, locale);
  const publicNote = formatLedgerPublicNote(entry, locale) ?? labels.noDetail;
  return (
    <tr
      key={entry.id}
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-3 px-3 py-4 md:table-row md:p-0"
    >
      <td
        className={`col-start-2 ${correction ? 'row-start-3' : 'row-start-2'} block p-0 text-right align-top md:table-cell md:px-4 md:py-3 md:text-left`}
      >
        <div className="font-mono text-xs font-semibold text-[var(--app-soft)]">
          <LedgerEntryTime entry={entry} locale={locale} />
        </div>
        <div className="app-muted app-type-micro mt-1">
          {formatLedgerSourceLabel(entry.source, locale)}
        </div>
      </td>
      <td
        className={`col-start-1 row-start-1 ${correction ? 'col-span-2' : ''} block p-0 align-top md:table-cell md:px-4 md:py-3`}
      >
        <div className="flex items-center gap-2.5">
          <span
            className={`app-type-micro inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] font-bold ${activityBadgeClass(summary.tone)}`}
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
      <td
        className={`col-start-1 ${correction ? 'row-start-3' : 'row-start-2'} block min-w-0 p-0 align-top md:table-cell md:px-4 md:py-3`}
      >
        <ActivityInstrument
          copy={copy}
          entry={entry}
          labels={labels}
          locale={locale}
        />
      </td>
      <td
        className={`${correction ? 'col-span-2 row-start-2' : 'col-start-2 row-start-1'} block p-0 text-right align-top font-mono text-sm font-semibold tabular-nums md:table-cell md:px-4 md:py-3 ${activityAmountClass(summary.tone)}`}
      >
        {summary.amount}
        <LedgerExecutionDetails entry={entry} labels={labels} locale={locale} />
      </td>
      <td
        className={`col-span-2 ${correction ? 'row-start-4' : 'row-start-3'} block min-w-0 max-w-none p-0 align-top text-[var(--app-muted)] md:table-cell md:max-w-[280px] md:px-4 md:py-3`}
      >
        <span
          className="block break-words [overflow-wrap:anywhere]"
          data-testid="activity-note"
        >
          {publicNote}
        </span>
        <LedgerCorrectionDetails entry={entry} locale={locale} />
      </td>
    </tr>
  );
}
