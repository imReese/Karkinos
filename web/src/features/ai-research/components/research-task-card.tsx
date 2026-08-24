import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  EvidenceIdentityDisclosure,
  StatusBadge,
} from '../../../shared/ui/workbench';
import {
  useResearchTaskAnalysisReviewsQuery,
  useReviewFixtureAnalysisMutation,
  type AnalysisReviewDecision,
  type HumanResearchTask,
  type ResearchTaskAnalysisReview,
  type ResearchTaskFixtureAnalysis,
} from '../api';
import type { ResearchTaskPanelCopy } from './research-task-copy';
import { newAuditKey } from './research-task-values';

export function ResearchTaskCard({
  analysis,
  analysisPending,
  copy,
  onReview,
  onStartAnalysis,
  reviewDisabled,
  task,
}: {
  analysis?: ResearchTaskFixtureAnalysis;
  analysisPending: boolean;
  copy: ResearchTaskPanelCopy;
  onReview: (
    decision:
      | 'context_accepted'
      | 'context_revision_requested'
      | 'closed_without_analysis',
  ) => void;
  onStartAnalysis: () => void;
  reviewDisabled: boolean;
  task: HumanResearchTask;
}) {
  const appCopy = useCopy();
  const reviewable =
    task.status === 'awaiting_human_review' ||
    task.status === 'blocked_by_evidence';
  return (
    <article className="rounded-2xl border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_62%,transparent)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-[var(--app-text)]">
            {task.title}
          </h3>
          <p className="app-muted mt-1 text-xs leading-5">
            {task.research_question}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <EvidenceIdentityDisclosure
            triggerLabel={appCopy.common.viewEvidenceIdentity}
            title={appCopy.common.evidenceIdentityTitle}
            description={appCopy.common.evidenceIdentityDescription}
            closeLabel={appCopy.common.closeEvidenceIdentity}
            copyLabel={appCopy.common.copyEvidenceValue}
            copiedLabel={appCopy.common.evidenceValueCopied}
            fields={[
              {
                label: appCopy.common.valuationSnapshot,
                value: task.valuation_snapshot_id,
                mono: true,
              },
              {
                label: appCopy.common.ledgerCutoff,
                value: task.ledger_cutoff_id,
                mono: true,
              },
              {
                label: appCopy.common.captureIdentity,
                value: task.capture_id,
                mono: true,
              },
              {
                label: appCopy.common.contextSnapshot,
                value: task.context_snapshot_id,
                mono: true,
              },
              {
                label: appCopy.common.contextFingerprint,
                value: task.context_fingerprint,
                mono: true,
              },
            ]}
          />
          <span className="rounded-full border border-[var(--app-border)] px-2.5 py-1 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-text)]">
            {copy.statuses[task.status]}
          </span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {task.evidence.map((evidence) => (
          <span
            className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[length:var(--app-font-size-micro)] text-[var(--app-muted)]"
            key={evidence.evidence_reference_id}
            title={evidence.evidence_reference_id}
          >
            {evidence.tool_name} · {evidence.status}
          </span>
        ))}
        <span className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[length:var(--app-font-size-micro)] text-[var(--app-muted)]">
          {copy.evidence}: {task.evidence.length}
        </span>
        <span className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[length:var(--app-font-size-micro)] text-[var(--app-muted)]">
          {task.all_evidence_authoritative
            ? copy.authoritative
            : `${copy.blocked}: ${task.blockers.length}`}
        </span>
      </div>
      {reviewable ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="app-button-secondary min-h-11 px-3 py-1.5 text-xs font-semibold"
            disabled={reviewDisabled || !task.all_evidence_authoritative}
            onClick={() => onReview('context_accepted')}
            title={
              task.all_evidence_authoritative ? undefined : copy.acceptBlocked
            }
            type="button"
          >
            {copy.accept}
          </button>
          <button
            className="app-button-secondary min-h-11 px-3 py-1.5 text-xs font-semibold"
            disabled={reviewDisabled}
            onClick={() => onReview('context_revision_requested')}
            type="button"
          >
            {copy.revise}
          </button>
          <button
            className="app-button-secondary min-h-11 px-3 py-1.5 text-xs font-semibold"
            disabled={reviewDisabled}
            onClick={() => onReview('closed_without_analysis')}
            type="button"
          >
            {copy.closeWithout}
          </button>
        </div>
      ) : null}
      {task.status === 'context_accepted' && !analysis ? (
        <div className="mt-4 border-t border-[var(--app-border)] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-1.5">
              <BoundaryBadge label={copy.fixtureOnly} />
              <BoundaryBadge label={copy.noNetwork} />
            </div>
            <button
              className="app-button-primary min-h-11 px-3 py-1.5 text-xs font-semibold"
              disabled={analysisPending}
              onClick={onStartAnalysis}
              type="button"
            >
              {analysisPending ? copy.runningFixture : copy.runFixture}
            </button>
          </div>
        </div>
      ) : null}
      {analysis ? (
        <FixtureAnalysisSummary analysis={analysis} copy={copy} />
      ) : null}
    </article>
  );
}

function FixtureAnalysisSummary({
  analysis,
  copy,
}: {
  analysis: ResearchTaskFixtureAnalysis;
  copy: ResearchTaskPanelCopy;
}) {
  const reportArtifact = analysis.artifacts.find(
    (artifact) => artifact.kind === 'report',
  );
  const reportSummary =
    typeof reportArtifact?.content.summary === 'string'
      ? reportArtifact.content.summary
      : null;
  const bindingValid = analysis.binding_validity === 'valid';
  const memoryValid =
    analysis.memory_validity === 'human_review_required_exact_context_only';

  return (
    <section
      aria-label={copy.report}
      className="mt-4 border-t border-[var(--app-border)] pt-3"
    >
      <div className="flex flex-wrap gap-1.5">
        <BoundaryBadge label={copy.fixtureOnly} />
        <BoundaryBadge label={copy.noNetwork} />
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <EvidenceIdentity
          label={copy.analysisStatus}
          value={analysis.workflow_status}
        />
        <EvidenceIdentity
          label={copy.bindingStatus}
          value={bindingValid ? copy.bindingValid : copy.bindingDrift}
        />
        <EvidenceIdentity
          label={copy.memoryStatus}
          value={memoryValid ? copy.memoryPending : copy.memoryInvalid}
        />
        <EvidenceIdentity
          label="Audit"
          value={
            analysis.audit_replay.valid ? copy.auditValid : copy.auditInvalid
          }
        />
      </dl>
      <div className="mt-3 flex flex-wrap gap-1.5" aria-label={copy.artifacts}>
        {analysis.artifacts.map((artifact) => (
          <span
            className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[length:var(--app-font-size-micro)] text-[var(--app-muted)]"
            key={artifact.artifact_id}
            title={artifact.artifact_id}
          >
            {artifact.kind} · {artifact.evidence_reference_ids.length}
          </span>
        ))}
      </div>
      {reportSummary ? (
        <div className="mt-3 rounded-xl border border-[var(--app-border)] p-3">
          <div className="app-type-overline text-[var(--app-muted)]">
            {copy.report}
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text)]">
            {reportSummary}
          </p>
        </div>
      ) : null}
      {!bindingValid && analysis.binding_errors.length ? (
        <ul className="mt-3 space-y-1 text-xs text-[var(--app-danger-text)]">
          {analysis.binding_errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      ) : null}
      <FixtureAnalysisReviewControl analysis={analysis} copy={copy} />
    </section>
  );
}

function FixtureAnalysisReviewControl({
  analysis,
  copy,
}: {
  analysis: ResearchTaskFixtureAnalysis;
  copy: ResearchTaskPanelCopy;
}) {
  const reviews = useResearchTaskAnalysisReviewsQuery(analysis.analysis_id);
  const recordReview = useReviewFixtureAnalysisMutation();
  const [reviewedBy, setReviewedBy] = useState(analysis.requested_by);
  const [note, setNote] = useState('');
  const [idempotencyKeys, setIdempotencyKeys] = useState<
    Partial<Record<AnalysisReviewDecision, string>>
  >({});
  const review = reviews.data?.reviews[0];
  const acceptanceEligible =
    analysis.workflow_status === 'completed' &&
    !analysis.partial_result &&
    analysis.binding_validity === 'valid' &&
    analysis.audit_replay.valid &&
    analysis.memory_validity === 'human_review_required_exact_context_only';
  const formReady = Boolean(reviewedBy.trim() && note.trim());

  const submitReview = async (decision: AnalysisReviewDecision) => {
    const idempotencyKey =
      idempotencyKeys[decision] ?? newAuditKey('ai-analysis-review');
    if (!idempotencyKeys[decision]) {
      setIdempotencyKeys((current) => ({
        ...current,
        [decision]: idempotencyKey,
      }));
    }
    try {
      await recordReview.mutateAsync({
        analysis_id: analysis.analysis_id,
        idempotency_key: idempotencyKey,
        reviewed_by: reviewedBy.trim(),
        decision,
        note: note.trim(),
      });
    } catch {
      // The mutation state renders the fail-closed response and keeps the key.
    }
  };

  return (
    <section
      aria-label={copy.analysisReview}
      className="mt-4 rounded-xl border border-[var(--app-border)] p-3"
    >
      <div className="app-type-overline text-[var(--app-muted)]">
        {copy.analysisReview}
      </div>
      <p className="app-muted mt-1 text-xs leading-5">
        {copy.analysisReviewBoundary}
      </p>
      {reviews.isLoading ? (
        <p className="app-muted mt-3 text-xs" role="status">
          {copy.analysisLoading}
        </p>
      ) : reviews.isError ? (
        <p className="mt-3 text-xs text-[var(--app-danger-text)]" role="alert">
          {copy.analysisReviewLoadError}
        </p>
      ) : review ? (
        <RecordedAnalysisReview copy={copy} review={review} />
      ) : (
        <div className="mt-3 space-y-3">
          <LabeledInput
            label={copy.reviewer}
            onChange={setReviewedBy}
            required
            value={reviewedBy}
          />
          <label className="block text-xs font-semibold text-[var(--app-muted)]">
            {copy.analysisReviewNote}
            <textarea
              className="app-input mt-1 min-h-20 w-full resize-y px-3 py-2 text-sm text-[var(--app-text)]"
              onChange={(event) => setNote(event.target.value)}
              required
              value={note}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              className="app-button-primary min-h-11 px-3 py-1.5 text-xs font-semibold"
              disabled={
                recordReview.isPending || !formReady || !acceptanceEligible
              }
              onClick={() => void submitReview('accept_as_reviewed_memory')}
              title={
                acceptanceEligible ? undefined : copy.acceptAnalysisBlocked
              }
              type="button"
            >
              {copy.acceptMemory}
            </button>
            <button
              className="app-button-secondary min-h-11 px-3 py-1.5 text-xs font-semibold"
              disabled={recordReview.isPending || !formReady}
              onClick={() => void submitReview('request_revision')}
              type="button"
            >
              {copy.requestAnalysisRevision}
            </button>
            <button
              className="app-button-secondary min-h-11 px-3 py-1.5 text-xs font-semibold"
              disabled={recordReview.isPending || !formReady}
              onClick={() => void submitReview('reject')}
              type="button"
            >
              {copy.rejectAnalysis}
            </button>
          </div>
          {!formReady ? (
            <p className="app-muted text-xs">{copy.analysisReviewRequired}</p>
          ) : null}
        </div>
      )}
      {recordReview.isPending ? (
        <p className="app-muted mt-3 text-xs" role="status">
          {copy.recordingAnalysisReview}
        </p>
      ) : null}
      {recordReview.isError ? (
        <p className="mt-3 text-xs text-[var(--app-danger-text)]" role="alert">
          {recordReview.error.message}
        </p>
      ) : null}
    </section>
  );
}

function RecordedAnalysisReview({
  copy,
  review,
}: {
  copy: ResearchTaskPanelCopy;
  review: ResearchTaskAnalysisReview;
}) {
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-[var(--app-border)] px-2.5 py-1 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-text)]">
          {copy.analysisReviewStatuses[review.effective_status]}
        </span>
        <span className="text-xs text-[var(--app-muted)]">
          {review.memory_recall_eligible
            ? copy.memoryRecallEligible
            : copy.memoryRecallIneligible}
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--app-text)]">
        {review.note}
      </p>
      <p className="app-muted mt-1 text-[length:var(--app-font-size-micro)]">
        {review.reviewed_by} · {review.created_at}
      </p>
      {review.invalidation_reasons.length ? (
        <ul className="mt-2 space-y-1 text-xs text-[var(--app-danger-text)]">
          {review.invalidation_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function LabeledInput({
  label,
  onChange,
  required,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  value: string;
}) {
  return (
    <label className="block text-xs font-semibold text-[var(--app-muted)]">
      {label}
      <input
        className="app-input mt-1 min-h-11 w-full px-3 py-2 text-sm text-[var(--app-text)]"
        onChange={(event) => onChange(event.target.value)}
        required={required}
        value={value}
      />
    </label>
  );
}

export function BoundaryBadge({ label }: { label: string }) {
  return <StatusBadge tone="neutral">{label}</StatusBadge>;
}

function EvidenceIdentity({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="app-type-overline text-[var(--app-muted)]">{label}</dt>
      <dd
        className="mt-1 truncate font-mono text-[var(--app-text)]"
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
