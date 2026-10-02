import { formatTimestamp } from '../../../shared/format';
import type { Locale } from '../../../shared/locale';
import { StatusBadge } from '../../../shared/ui/workbench';
import type { CorporateActionEvidence } from '../api-contracts';
import { corporateActionCopy } from '../copy-corporate-actions';
import type { CorporateActionMode } from '../corporate-action-contracts';
import { cashDividendCopy } from '../copy-cash-dividends';

export function CorporateActionEvidencePanel({
  evidence,
  locale,
  returnMode = 'price_only',
}: {
  evidence?: CorporateActionEvidence | null;
  locale: Locale;
  returnMode?: CorporateActionMode | 'evidence_only';
}) {
  const labels = corporateActionCopy[locale];
  const observed =
    evidence?.schema_version === 'karkinos.corporate_action_evidence.v1' &&
    evidence.status === 'observed' &&
    evidence.coverage_status === 'provider_reported_only' &&
    evidence.returns_modeled === false &&
    [
      evidence.total_record_count,
      evidence.matched_event_count,
      evidence.undated_event_count,
    ].every((count) => Number.isInteger(count) && count >= 0);

  return (
    <section
      aria-label={labels.title}
      className="min-w-0 border-y border-[var(--app-divider)] py-3"
      data-testid="corporate-action-evidence"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h4 className="text-sm font-semibold">{labels.title}</h4>
        <StatusBadge tone="warning">
          {observed ? labels.observed : labels.notEvaluated}
        </StatusBadge>
      </div>
      {observed && evidence ? (
        <>
          <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
            {[
              [labels.total, evidence.total_record_count],
              [labels.matched, evidence.matched_event_count],
              [labels.undated, evidence.undated_event_count],
            ].map(([label, count]) => (
              <div
                key={label}
                className="border-l border-[var(--app-divider)] pl-3"
              >
                <dt className="text-[var(--app-text-secondary)]">{label}</dt>
                <dd className="mt-1 font-mono font-semibold tabular-nums">
                  {count}
                </dd>
              </div>
            ))}
          </dl>
          <p className="app-muted mt-3 text-xs leading-5">
            {labels.source}: Tushare · {labels.observedAt}:{' '}
            {formatTimestamp(evidence.available_at)}
          </p>
          <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
            {labels.coverage}
          </p>
          {evidence.matched_event_count === 0 ? (
            <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
              {labels.zeroMatches}
            </p>
          ) : null}
          <p className="app-muted mt-2 text-xs leading-5">
            {labels.availability}
          </p>
          <p className="mt-2 text-xs leading-5 text-[var(--app-warning-text)]">
            {returnMode === 'cash_dividends_gross'
              ? cashDividendCopy[locale].returns
              : returnMode === 'evidence_only'
                ? cashDividendCopy[locale].evidenceOnly
                : labels.returns}
          </p>
          {evidence.events.length > 0 ? (
            <CorporateActionEvents events={evidence.events} locale={locale} />
          ) : null}
        </>
      ) : (
        <p className="app-muted mt-2 text-xs leading-5">{labels.missing}</p>
      )}
    </section>
  );
}

function CorporateActionEvents({
  events,
  locale,
}: {
  events: CorporateActionEvidence['events'];
  locale: Locale;
}) {
  const labels = corporateActionCopy[locale];
  const columns: {
    key: keyof CorporateActionEvidence['events'][number];
    label: string;
  }[] = [
    { key: 'symbol', label: labels.symbol },
    { key: 'div_proc', label: labels.progress },
    { key: 'ann_date', label: labels.announcement },
    { key: 'imp_ann_date', label: labels.implementation },
    { key: 'record_date', label: labels.recordDate },
    { key: 'ex_date', label: labels.exDate },
    { key: 'pay_date', label: labels.payDate },
    { key: 'div_listdate', label: labels.listingDate },
    { key: 'cash_div_tax', label: labels.cashBeforeTax },
    { key: 'stk_div', label: labels.bonusTotal },
    { key: 'stk_bo_rate', label: labels.bonusShares },
    { key: 'stk_co_rate', label: labels.capitalizedShares },
  ];
  return (
    <details
      className="mt-3 min-w-0"
      data-testid="corporate-action-event-details"
    >
      <summary className="cursor-pointer text-xs font-semibold">
        {labels.details(events.length)}
      </summary>
      <p className="app-muted my-2 text-xs leading-5">{labels.eventBoundary}</p>
      <div
        className="w-full min-w-0 max-w-full overflow-x-auto overscroll-x-contain border-y border-[var(--app-divider)]"
        role="region"
        aria-label={labels.events}
        tabIndex={0}
        data-testid="corporate-action-events-scroll"
      >
        <table className="w-full min-w-[1280px] text-left text-xs">
          <caption className="sr-only">{labels.events}</caption>
          <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
            <tr>
              {columns.map(({ key, label }) => (
                <th key={key} scope="col" className="px-3 py-2 font-semibold">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map((event, index) => (
              <tr
                key={`${event.observation_id}-${event.source_revision_id}-${index}`}
                className="border-t border-[var(--app-divider)]"
              >
                {columns.map(({ key }) => (
                  <td
                    key={key}
                    className="whitespace-nowrap px-3 py-2 tabular-nums"
                  >
                    {event[key] ?? labels.unknown}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
