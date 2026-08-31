import { EvidenceState, StatusBadge } from '../../../shared/ui/workbench';
import type { CiticHistoryXlsPreview, CiticSourceReviewStatus } from '../api';
import {
  type CiticHistoryXlsPreviewResult,
  type CiticSourceReviewIntent,
} from './account-truth-citic-types';
import { CiticPreviewResultRow } from './account-truth-citic-preview-result';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode, statusTone } from './account-truth-review-format';

export function CiticHistoryXlsPreviewPanel({
  intakePending,
  locale,
  reviewIntent,
  results,
  onCancelReview,
  onConfirmReview,
  onStartReview,
  onUpdateReviewIntent,
}: {
  intakePending: boolean;
  locale: 'en' | 'zh';
  reviewIntent: CiticSourceReviewIntent | null;
  results: CiticHistoryXlsPreviewResult[];
  onCancelReview: () => void;
  onConfirmReview: () => void;
  onStartReview: (
    resultId: string,
    reviewStatus: CiticSourceReviewStatus,
  ) => void;
  onUpdateReviewIntent: (
    updates: Partial<
      Omit<CiticSourceReviewIntent, 'resultId' | 'reviewStatus'>
    >,
  ) => void;
}) {
  const text = labels[locale];
  const seenFingerprints = new Set<string>();
  const duplicateResultIds = new Set<string>();
  const uniquePreviews: CiticHistoryXlsPreview[] = [];
  for (const result of results) {
    if (!result.preview) {
      continue;
    }
    if (seenFingerprints.has(result.preview.file_fingerprint)) {
      duplicateResultIds.add(result.id);
      continue;
    }
    seenFingerprints.add(result.preview.file_fingerprint);
    uniquePreviews.push(result.preview);
  }
  const completedCount = results.filter(
    (result) => result.status !== 'pending',
  ).length;
  const failedCount = results.filter(
    (result) => result.status === 'error',
  ).length;
  const isPending = completedCount < results.length;
  const totals = uniquePreviews.reduce(
    (current, preview) => ({
      validRows: current.validRows + preview.valid_row_count,
      invalidRows: current.invalidRows + preview.invalid_row_count,
      recognizedEvents: current.recognizedEvents + preview.total_event_count,
      nonFinancialActivities:
        current.nonFinancialActivities +
        preview.recognized_non_financial_activity_count,
    }),
    {
      validRows: 0,
      invalidRows: 0,
      recognizedEvents: 0,
      nonFinancialActivities: 0,
    },
  );
  const brokerSoakCandidate = uniquePreviews[0]?.broker_soak_candidate ?? null;

  return (
    <div className="mt-4 border-y border-[var(--app-divider)] py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {isPending
            ? text.citicPreviewProgress(completedCount, results.length)
            : text.citicPreviewComplete}
        </div>
        <StatusBadge tone={statusTone(isPending ? 'checking' : 'blocked')}>
          {formatCode(isPending ? 'checking' : 'blocked', locale, 'status')}
        </StatusBadge>
      </div>
      <div className="mt-3 grid grid-cols-2 divide-x divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] sm:grid-cols-4 sm:divide-y-0">
        <Metric label={text.citicFiles} value={String(results.length)} />
        <Metric label={text.validRows} value={String(totals.validRows)} />
        <Metric label={text.invalidRows} value={String(totals.invalidRows)} />
        <Metric
          label={text.citicRecognizedEvents}
          value={String(totals.recognizedEvents)}
        />
      </div>
      <div
        className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
        data-testid="citic-preview-results"
      >
        {results.map((result) => (
          <CiticPreviewResultRow
            intakePending={intakePending}
            isDuplicate={duplicateResultIds.has(result.id)}
            key={result.id}
            locale={locale}
            result={result}
            reviewIntent={reviewIntent}
            onCancelReview={onCancelReview}
            onConfirmReview={onConfirmReview}
            onStartReview={onStartReview}
            onUpdateReviewIntent={onUpdateReviewIntent}
          />
        ))}
      </div>
      {!isPending && failedCount > 0 ? (
        <EvidenceState
          className="mt-3"
          kind="error"
          title={`${text.citicPreviewFailed}: ${text.citicFailedFileCount(failedCount)}`}
        />
      ) : null}
      {!isPending && totals.invalidRows > 0 ? (
        <EvidenceState
          className="mt-3"
          kind="partial"
          title={text.citicInvalidRows(totals.invalidRows)}
        />
      ) : null}
      {!isPending && totals.nonFinancialActivities > 0 ? (
        <EvidenceState
          className="mt-3"
          kind="partial"
          title={text.citicNonFinancialActivityNotice(
            totals.nonFinancialActivities,
          )}
        />
      ) : null}
      {!isPending ? (
        <>
          <EvidenceState
            className="mt-3"
            kind="partial"
            statusLabel={formatCode('blocked', locale, 'status')}
            title={text.citicEvidenceBlocked}
            description={
              <>
                <p>{text.citicEvidenceBlockedBody}</p>
                <div className="app-type-overline mt-3 text-[var(--app-text-tertiary)]">
                  {text.citicNextStepTitle}
                </div>
                <ol className="mt-2 grid gap-1.5">
                  {text.citicNextSteps.map((step, index) => (
                    <li
                      key={step}
                      className="grid grid-cols-[auto_minmax(0,1fr)] gap-2"
                    >
                      <span className="font-semibold tabular-nums">
                        {index + 1}.
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </>
            }
            evidence={`${uniquePreviews.length} unique SHA-256 fingerprints`}
          />
          {brokerSoakCandidate ? (
            <EvidenceState
              className="mt-3"
              kind="partial"
              statusLabel={formatCode('blocked', locale, 'status')}
              title={text.citicSoakBlocked}
              description={
                <>
                  <p>{text.citicSoakBlockedBody}</p>
                  <details className="mt-2 border-y border-[var(--app-divider)] py-2">
                    <summary className="cursor-pointer text-xs font-semibold text-[var(--app-text-secondary)]">
                      {text.citicSoakRequiredEvidence}
                    </summary>
                    <ul className="mt-2 grid gap-1 text-xs text-[var(--app-text-secondary)] sm:grid-cols-2">
                      {brokerSoakCandidate.required_source_evidence.map(
                        (evidenceCode) => (
                          <li key={evidenceCode}>
                            {formatCode(evidenceCode, locale, 'code')}
                          </li>
                        ),
                      )}
                    </ul>
                  </details>
                  <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
                    {text.citicSoakProhibited}
                  </p>
                </>
              }
              evidence={brokerSoakCandidate.assessment_fingerprint}
            />
          ) : null}
          <p className="app-type-micro mt-3 text-[var(--app-text-tertiary)]">
            {text.citicPrivacyResponse}
          </p>
        </>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="app-type-micro truncate font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div className="mt-0.5 text-base font-semibold text-[var(--app-text)] tabular-nums">
        {value}
      </div>
    </div>
  );
}
