import { formatDateTime } from '../../../shared/format';
import type { Locale } from '../../../shared/preferences/context';
import { StatusBadge } from '../../../shared/ui/workbench';
import { BrokerEvidenceImportWizard } from './account-truth-broker-evidence-import';
import { EvidenceReadinessChecklist } from './account-truth-evidence-readiness';
import { FEE_SCHEDULE_REVIEW_COPY } from './fee-schedule-review-copy';
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

const accountTruthEvidenceSectionCopy = {
  en: {
    reviewTitle: 'Review evidence',
    reviewDetail:
      'Open only the evidence domain needed for the current reconciliation or blocker.',
    maintenanceTitle: 'Evidence maintenance',
    maintenanceDetail:
      'Import history and staging tools are maintenance workflows, not account truth itself.',
  },
  zh: {
    reviewTitle: '复核证据',
    reviewDetail: '仅在需要处理当前对账或阻断项时展开对应证据域。',
    maintenanceTitle: '证据维护',
    maintenanceDetail: '导入历史与暂存工具属于维护流程，不等同于账户事实本身。',
  },
} as const;

export function AccountTruthEvidenceSections({
  locale,
  state,
}: {
  locale: Locale;
  state: AccountTruthReviewState;
}) {
  const text = labels[locale];
  const sectionText = accountTruthEvidenceSectionCopy[locale];
  const feeText = FEE_SCHEDULE_REVIEW_COPY[locale];
  const {
    collector,
    componentEntries,
    imported,
    importRuns,
    readiness,
    scoreData,
    scoreIsMissing,
    selectReport,
  } = state;

  return (
    <div className="grid min-w-0 gap-5">
      <section
        className="min-w-0 border-t border-[var(--app-divider)] pt-4"
        data-testid="account-truth-review-evidence-zone"
      >
        <div className="mb-3 min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {sectionText.reviewTitle}
          </h2>
          <p className="app-muted mt-1 text-xs leading-5">
            {sectionText.reviewDetail}
          </p>
        </div>

        <div className="grid min-w-0 gap-2">
          {readiness.data ? (
            <AccountTruthDisclosure
              defaultOpen={false}
              detail={feeText.detail}
              testId="account-truth-fee-schedule-disclosure"
              title={feeText.title}
            >
              <FeeScheduleReviewPanel
                locale={locale}
                readiness={readiness.data}
              />
            </AccountTruthDisclosure>
          ) : null}

          <AccountTruthDisclosure
            key={
              'readiness-' + (readiness.data?.evidence_fingerprint ?? 'missing')
            }
            defaultOpen={false}
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
            defaultOpen={false}
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
                <StatusBadge
                  tone={statusTone(scoreData?.gate_status ?? 'blocked')}
                >
                  {formatCode(
                    scoreData?.gate_status ?? 'blocked',
                    locale,
                    'status',
                  )}
                </StatusBadge>
              </div>
              {scoreIsMissing ? (
                <MissingEvidenceCallout locale={locale} />
              ) : null}
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
        </div>
      </section>

      <section
        className="min-w-0 border-t border-[var(--app-divider)] pt-4"
        data-testid="account-truth-maintenance-zone"
      >
        <div className="mb-3 min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {sectionText.maintenanceTitle}
          </h2>
          <p className="app-muted mt-1 text-xs leading-5">
            {sectionText.maintenanceDetail}
          </p>
        </div>

        <div className="grid min-w-0 gap-2">
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
            key={'ingest-' + String(scoreIsMissing)}
            defaultOpen={false}
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
      </section>
    </div>
  );
}
