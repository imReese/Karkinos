import type { Locale } from '../../../shared/preferences/context';
import { formatDateTime } from '../../../shared/format';
import { StatusBadge } from '../../../shared/ui/workbench';
import { BrokerEvidenceImportWizard } from './account-truth-broker-evidence-import';
import { EvidenceReadinessChecklist } from './account-truth-evidence-readiness';
import { FeeScheduleReviewPanel } from './fee-schedule-review-panel';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode, statusTone } from './account-truth-review-format';
import {
  AccountTruthDisclosure,
  EmptyState,
  MissingEvidenceCallout,
  ReasonList,
} from './account-truth-reconciliation-review';
import type { AccountTruthReviewState } from './account-truth-review-state';

export function AccountTruthEvidenceSections({
  locale,
  state,
}: {
  locale: Locale;
  state: AccountTruthReviewState;
}) {
  const text = labels[locale];
  const {
    collector,
    componentEntries,
    imported,
    importRuns,
    readiness,
    scoreData,
    scoreIsMissing,
    scoreNeedsAttention,
    selectReport,
  } = state;

  return (
    <div className="grid min-w-0 gap-3">
      {readiness.data ? (
        <FeeScheduleReviewPanel locale={locale} readiness={readiness.data} />
      ) : null}

      <AccountTruthDisclosure
        key={`readiness-${readiness.data?.evidence_fingerprint ?? 'missing'}`}
        defaultOpen={readiness.data?.status !== 'ready'}
        detail={text.readinessDetail}
        id="account-truth-evidence-readiness-disclosure"
        testId="account-truth-evidence-readiness-disclosure"
        title={text.readinessTitle}
      >
        <EvidenceReadinessChecklist
          locale={locale}
          readiness={readiness.data}
        />
      </AccountTruthDisclosure>

      <AccountTruthDisclosure
        key={`score-${scoreNeedsAttention}`}
        defaultOpen={scoreNeedsAttention}
        detail={text.scoreEvidenceDetail}
        testId="account-truth-score-disclosure"
        title={text.scoreEvidenceTitle}
      >
        <section
          className="min-w-0 px-1 py-4 sm:px-4"
          data-testid="account-truth-score"
        >
          <div className="flex items-start justify-between gap-4">
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {text.components}
            </h2>
            <StatusBadge tone={statusTone(scoreData?.gate_status ?? 'blocked')}>
              {formatCode(
                scoreData?.gate_status ?? 'blocked',
                locale,
                'status',
              )}
            </StatusBadge>
          </div>
          {scoreIsMissing ? <MissingEvidenceCallout locale={locale} /> : null}
          <ul className="mt-4 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {componentEntries.map(([label, value]) => (
              <li
                key={label}
                className="flex items-center justify-between gap-3 py-2.5 text-xs font-medium text-[var(--app-text-secondary)]"
              >
                <span>{label}</span>
                <StatusBadge tone={statusTone(value ?? 'missing')}>
                  {formatCode(value ?? '--', locale, 'status')}
                </StatusBadge>
              </li>
            ))}
          </ul>
          <ReasonList
            title={text.blockingReasons}
            values={scoreData?.blocking_reasons ?? []}
            locale={locale}
          />
          <ReasonList
            title={text.requiredActions}
            values={scoreData?.required_actions ?? []}
            locale={locale}
          />
        </section>
      </AccountTruthDisclosure>

      <AccountTruthDisclosure
        detail={text.importHistoryDetail((importRuns.data ?? []).length)}
        testId="account-truth-import-history-disclosure"
        title={text.importHistoryTitle}
      >
        <div className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {(importRuns.data ?? []).length > 0 ? (
            importRuns.data?.map((run) => (
              <button
                key={run.import_run_id}
                type="button"
                className="grid min-h-12 w-full min-w-0 gap-1 py-2 text-left sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                onClick={() => selectReport(run.import_run_id)}
              >
                <span className="truncate text-sm font-semibold text-[var(--app-text)]">
                  {run.source_name}
                </span>
                <span className="text-xs text-[var(--app-text-secondary)]">
                  {text.rows} {run.row_count} · {text.duplicates}{' '}
                  {run.row_duplicate_count + run.file_duplicate_count}
                </span>
                <span className="app-type-micro flex items-center gap-2 text-[var(--app-text-tertiary)]">
                  <StatusBadge tone={statusTone(run.validation_status)}>
                    {formatCode(run.validation_status, locale, 'status')}
                  </StatusBadge>
                  {formatDateTime(run.created_at)}
                </span>
              </button>
            ))
          ) : (
            <EmptyState
              title={text.notReadyTitle}
              body={text.noImports}
              locale={locale}
            />
          )}
        </div>
      </AccountTruthDisclosure>

      <AccountTruthDisclosure
        key={`ingest-${scoreIsMissing}`}
        defaultOpen={scoreIsMissing}
        detail={text.importToolsDetail}
        id="account-truth-import-tools"
        testId="account-truth-import-tools-disclosure"
        title={text.importToolsTitle}
      >
        <BrokerEvidenceImportWizard
          locale={locale}
          collectorStatus={collector.data}
          collectorStatusIsError={collector.isError}
          onImported={imported}
        />
      </AccountTruthDisclosure>
    </div>
  );
}
