import { useState } from 'react';

import { formatPublicStatus } from '../../../shared/public-labels';
import type { Locale } from '../../../shared/preferences/context';
import type {
  ShadowResearchAutomationStatus,
  ShadowResearchQualificationCandidate,
  ShadowResearchQualificationRun,
} from '../api';
import type { ShadowResearchCopy } from './shadow-research-copy';

type QualificationView = {
  run: ShadowResearchQualificationRun | undefined;
  attempt: ShadowResearchAutomationStatus['latest_qualification_attempt'];
  winner: ShadowResearchQualificationCandidate | undefined;
  sourceCandidateBound: boolean;
  approved: boolean;
  approvalEligible: boolean;
};

function qualificationView(
  status: ShadowResearchAutomationStatus | undefined,
): QualificationView {
  const runs = status?.qualification_runs ?? [];
  const candidates = status?.qualification_candidates ?? [];
  const outcome = status?.research_outcome;
  const run =
    outcome?.qualification_run_id == null
      ? undefined
      : runs.find(
          (item) => item.qualification_run_id === outcome.qualification_run_id,
        );
  const currentSelection = status?.daily_selections?.[0];
  const currentBackup = status?.daily_backups?.find(
    (item) => item.run_id === currentSelection?.run_id,
  );
  const currentAttempt = status?.latest_qualification_attempt;
  const attempt =
    !run &&
    currentSelection?.integrity_status === 'verified' &&
    currentBackup?.verification_status === 'verified' &&
    currentAttempt?.source_run_id === currentSelection.run_id &&
    currentAttempt.market_date === currentSelection.market_date
      ? currentAttempt
      : null;
  const winner = run?.winner_qualification_candidate_id
    ? candidates.find(
        (item) =>
          item.qualification_run_id === run.qualification_run_id &&
          item.qualification_candidate_id ===
            run.winner_qualification_candidate_id,
      )
    : undefined;
  const sourceCandidate = winner
    ? status?.candidates.find(
        (item) =>
          item.candidate_id === winner.source_candidate_id &&
          item.run_id === run?.source_run_id,
      )
    : undefined;
  const sourceCandidateBound = Boolean(
    sourceCandidate &&
    sourceCandidate.status === 'evaluated_research_only' &&
    sourceCandidate.recommendation === 'formula_research_candidate' &&
    sourceCandidate.promotion_status === 'account_qualification_required',
  );
  const approved = Boolean(
    winner &&
    (status?.qualification_approvals ?? []).some(
      (approval) =>
        approval.qualification_run_id === run?.qualification_run_id &&
        approval.qualification_candidate_id ===
          winner.qualification_candidate_id &&
        approval.target_stage === 'paper_shadow',
    ),
  );
  const approvalEligible = Boolean(
    run &&
    winner &&
    sourceCandidateBound &&
    !approved &&
    run.status === 'completed' &&
    run.selection_status === 'winner_selected' &&
    run.winner_qualification_candidate_id ===
      winner.qualification_candidate_id &&
    winner.status === 'qualified' &&
    winner.recommendation === 'paper_shadow_review' &&
    outcome?.account_qualification_status === 'passed' &&
    outcome.qualification_run_id === run.qualification_run_id &&
    outcome.winner_qualification_candidate_id ===
      winner.qualification_candidate_id,
  );
  return {
    run,
    attempt,
    winner,
    sourceCandidateBound,
    approved,
    approvalEligible,
  };
}

export function ShadowResearchQualificationReview({
  approvedBy,
  copy,
  locale,
  onApprove,
  pending,
  status,
}: {
  approvedBy: string;
  copy: ShadowResearchCopy;
  locale: Locale;
  onApprove: (qualificationCandidateId: string, notes: string) => Promise<void>;
  pending: boolean;
  status: ShadowResearchAutomationStatus | undefined;
}) {
  const [notes, setNotes] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const view = qualificationView(status);
  const outcomeStatus =
    status?.research_outcome.account_qualification_status ?? 'not_evaluated';
  const statusKey = view.run?.status ?? view.attempt?.status ?? outcomeStatus;
  const displayStatus = copy.qualificationStatus[statusKey];
  const blockers = view.run?.blockers ?? view.attempt?.blockers ?? [];
  const failureCode =
    view.run?.failure_code ?? view.attempt?.failure_code ?? null;

  const approve = async () => {
    if (!view.approvalEligible || !view.winner || !notes.trim() || !confirmed) {
      return;
    }
    try {
      await onApprove(view.winner.qualification_candidate_id, notes.trim());
      setNotes('');
      setConfirmed(false);
    } catch {
      // The mutation remains fail closed and exposes its error state to the panel.
    }
  };

  return (
    <section
      aria-labelledby="shadow-research-qualification-title"
      className="mt-6 rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] p-4"
      data-testid="shadow-research-qualification"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3
            className="text-base font-semibold text-[var(--app-text)]"
            id="shadow-research-qualification-title"
          >
            {copy.qualificationTitle}
          </h3>
          <p className="app-muted mt-2 max-w-3xl text-xs leading-5">
            {copy.qualificationDetail}
          </p>
        </div>
        <span className="rounded-full border border-[var(--app-divider)] px-2.5 py-1 text-xs font-semibold">
          {displayStatus}
        </span>
      </div>

      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        <div className="min-w-0 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] p-3">
          <dt className="font-semibold text-[var(--app-muted)]">
            {view.run
              ? copy.qualificationRun
              : view.attempt
                ? copy.qualificationAttempt
                : copy.qualificationRun}
          </dt>
          <dd className="mt-1 break-all font-semibold text-[var(--app-text)]">
            {view.run?.qualification_run_id ?? view.attempt?.attempt_id ?? '—'}
          </dd>
          <dd className="app-muted mt-1">
            {view.run
              ? `${view.run.market_date} · ${view.run.source_run_id}`
              : view.attempt
                ? `${view.attempt.market_date} · ${view.attempt.source_run_id}`
                : copy.qualificationNotEvaluated}
          </dd>
        </div>
        <div className="min-w-0 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] p-3">
          <dt className="font-semibold text-[var(--app-muted)]">
            {copy.qualificationWinnerBinding}
          </dt>
          <dd className="mt-1 break-all font-semibold text-[var(--app-text)]">
            {view.winner
              ? `${view.winner.qualification_candidate_id} → ${view.winner.source_candidate_id}`
              : copy.qualificationNoWinner}
          </dd>
          <dd className="app-muted mt-1">
            {view.winner && view.sourceCandidateBound
              ? copy.qualificationSourceBound
              : copy.qualificationSourceUnbound}
          </dd>
        </div>
      </dl>

      <p className="app-muted mt-3 text-xs leading-5">
        {copy.qualificationSourceLocked}
      </p>

      {blockers.length ? (
        <div className="mt-4">
          <h4 className="text-xs font-semibold text-[var(--app-text)]">
            {copy.qualificationBlockers}
          </h4>
          <ul className="app-muted mt-2 list-disc space-y-1 pl-4 text-xs leading-5">
            {blockers.map((blocker) => (
              <li key={blocker}>{formatPublicStatus(blocker, locale)}</li>
            ))}
            {failureCode && !blockers.includes(failureCode) ? (
              <li>{formatPublicStatus(failureCode, locale)}</li>
            ) : null}
          </ul>
        </div>
      ) : failureCode ? (
        <p className="mt-4 text-xs text-[var(--app-danger-text)]">
          {formatPublicStatus(failureCode, locale)}
        </p>
      ) : null}

      {view.approved ? (
        <p className="mt-4 text-sm font-semibold text-[var(--app-success-text)]">
          {copy.qualificationApproved}
        </p>
      ) : null}

      {view.approvalEligible && view.winner ? (
        <div className="mt-5 border-t border-[var(--app-divider)] pt-4">
          <label className="text-xs font-semibold text-[var(--app-text)]">
            {copy.qualificationApprovalNote}
            <textarea
              className="app-input mt-2 min-h-20 w-full resize-y"
              onChange={(event) => setNotes(event.target.value)}
              value={notes}
            />
          </label>
          <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--app-muted)]">
            <input
              checked={confirmed}
              className="mt-1"
              onChange={(event) => setConfirmed(event.target.checked)}
              type="checkbox"
            />
            <span>{copy.qualificationApprovalConfirm}</span>
          </label>
          <button
            className="app-button-primary mt-3 min-h-11 px-4 py-2 text-sm font-semibold"
            disabled={
              pending || !confirmed || !notes.trim() || !approvedBy.trim()
            }
            onClick={() => void approve()}
            type="button"
          >
            {pending ? copy.qualificationApproving : copy.qualificationApprove}
          </button>
        </div>
      ) : null}
    </section>
  );
}
