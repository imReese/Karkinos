import { useState } from 'react';

import { formatPublicStatus } from '../../../shared/public-labels';
import type { Locale } from '../../../shared/preferences/context';
import type {
  ShadowResearchAutomationStatus,
  ShadowResearchCandidate,
  ShadowResearchQualificationCandidate,
  ShadowResearchQualificationRun,
  ForwardReviewBinding,
} from '../api';
import type { ShadowResearchCopy } from './shadow-research-copy';
import { ShadowResearchObservations } from './shadow-research-observations';
import { QualificationForwardReview } from './qualification-forward-review';
import { usePublicationPolicy } from '../publication-policy-api';

type QualificationView = {
  run: ShadowResearchQualificationRun | undefined;
  attempt: ShadowResearchAutomationStatus['latest_qualification_attempt'];
  winner: ShadowResearchQualificationCandidate | undefined;
  sourceCandidateBound: boolean;
  sourceCandidate: ShadowResearchCandidate | undefined;
  approved: boolean;
  approvalRecorded: boolean;
  legacyApproval: boolean;
  approvalEligible: boolean;
};

function qualificationView(
  status: ShadowResearchAutomationStatus | undefined,
  usableSourceIds: string[],
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
  const approval = winner
    ? (status?.qualification_approvals ?? []).find(
        (item) =>
          item.qualification_run_id === run?.qualification_run_id &&
          item.qualification_candidate_id ===
            winner.qualification_candidate_id &&
          item.target_stage === 'paper_shadow',
      )
    : undefined;
  const approvalRecorded = Boolean(approval);
  const legacyApproval =
    approval?.decision_source === 'legacy_ungranted' ||
    approval?.manual_confirmation_recorded === false;
  const approved = Boolean(
    winner &&
    sourceCandidate &&
    usableSourceIds.includes(
      `ai_formula_shadow:${sourceCandidate.candidate_id}`,
    ),
  );
  const approvalEligible = Boolean(
    run &&
    winner &&
    sourceCandidateBound &&
    !approvalRecorded &&
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
    sourceCandidate,
    approved,
    approvalRecorded,
    legacyApproval,
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
  onApprove: (
    qualificationCandidateId: string,
    notes: string,
    forwardReview?: ForwardReviewBinding,
  ) => Promise<void>;
  pending: boolean;
  status: ShadowResearchAutomationStatus | undefined;
}) {
  const [notes, setNotes] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [forwardReview, setForwardReview] =
    useState<ForwardReviewBinding | null>(null);
  const publication = usePublicationPolicy();
  const usableSourceIds = !publication.isError
    ? (publication.data?.usable_current_sources?.map(
        (source) => source.strategy_id,
      ) ?? [])
    : [];
  const view = qualificationView(status, usableSourceIds);
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
      await onApprove(
        view.winner.qualification_candidate_id,
        notes.trim(),
        forwardReview ?? undefined,
      );
      setNotes('');
      setConfirmed(false);
    } catch {
      // The mutation remains fail closed and exposes its error state to the panel.
    }
  };

  return (
    <section
      aria-labelledby="shadow-research-qualification-title"
      className="min-w-0 border-t border-[var(--app-divider)] py-6"
      data-testid="shadow-research-qualification"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3
            className="text-sm font-semibold text-[var(--app-text)]"
            id="shadow-research-qualification-title"
          >
            {copy.qualificationTitle}
          </h3>
          <p className="sr-only">{copy.qualificationDetail}</p>
        </div>
        <span className="rounded-full border border-[var(--app-divider)] px-2 py-0.5 text-xs font-semibold">
          {displayStatus}
        </span>
      </div>

      <dl className="mt-4 grid gap-4 text-xs sm:grid-cols-2">
        <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
          <dt className="font-semibold text-[var(--app-muted)]">
            {view.run
              ? copy.qualificationRun
              : view.attempt
                ? copy.qualificationAttempt
                : copy.qualificationRun}
          </dt>
          <dd className="mt-0.5 break-all font-semibold text-[var(--app-text)]">
            {view.run?.qualification_run_id ?? view.attempt?.attempt_id ?? '—'}
          </dd>
          <dd className="app-muted mt-0.5">
            {view.run
              ? `${view.run.market_date} · ${view.run.source_run_id}`
              : view.attempt
                ? `${view.attempt.market_date} · ${view.attempt.source_run_id}`
                : copy.qualificationNotEvaluated}
          </dd>
        </div>
        <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
          <dt className="font-semibold text-[var(--app-muted)]">
            {copy.qualificationWinnerBinding}
          </dt>
          <dd className="mt-0.5 break-all font-semibold text-[var(--app-text)]">
            {view.winner
              ? `${view.winner.qualification_candidate_id} → ${view.winner.source_candidate_id}`
              : copy.qualificationNoWinner}
          </dd>
          <dd className="app-muted mt-0.5">
            {view.winner && view.sourceCandidateBound
              ? copy.qualificationSourceBound
              : copy.qualificationSourceUnbound}
          </dd>
        </div>
      </dl>

      <p className="sr-only">{copy.qualificationSourceLocked}</p>
      {view.winner?.deployment_validation ? (
        <div
          className="app-muted mt-3 break-words text-xs"
          data-testid="qualification-deployment-validation"
        >
          <p>
            {view.winner.deployment_validation.validation_provenance ===
            'reviewed_account_cost_replay'
              ? locale === 'zh'
                ? '账户审核费率重算验证 / 固定检查点 / 费用来源'
                : 'Reviewed account cost validation / checkpoint / fee source'
              : locale === 'zh'
                ? '独立最终验证 / 固定检查点 / 费用来源'
                : 'Independent final validation / checkpoint / fee source'}
            : {view.winner.deployment_validation.status ?? '—'} /{' '}
            {view.winner.deployment_validation.checkpoint ?? '—'} /{' '}
            {view.winner.deployment_validation.fee_cost_model_reference ?? '—'}
          </p>
          {view.winner.deployment_validation.blockers?.length ? (
            <p>{view.winner.deployment_validation.blockers.join(' · ')}</p>
          ) : null}
          {view.winner.original_simulation_validation ? (
            <p>
              {locale === 'zh'
                ? '原独立模拟验证 / 模型费用'
                : 'Original independent simulation / modeled costs'}
              : {view.winner.original_simulation_validation.status ?? '—'} /{' '}
              {view.winner.original_simulation_validation
                .fee_cost_model_reference ?? '—'}
            </p>
          ) : null}
        </div>
      ) : null}

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

      {view.approvalRecorded && !view.approved ? (
        <p role="status" className="mt-3 text-xs">
          {view.legacyApproval
            ? locale === 'zh'
              ? '历史自动批准记录：未绑定有效发布授权，不代表人工确认或当前可用账户来源。'
              : 'Historical automatic approval: no valid publication grant is bound. This is not human confirmation or a currently usable account source.'
            : locale === 'zh'
              ? '批准记录已保留；当前账户来源尚未核验生效。'
              : 'Approval record retained; current account publication is not verified as applicable.'}
        </p>
      ) : null}

      <ShadowResearchObservations candidate={view.sourceCandidate} />

      {view.approvalEligible && view.winner ? (
        <div className="mt-5 border-t border-[var(--app-divider)] pt-4">
          {view.sourceCandidate?.candidate_result_id ? (
            <QualificationForwardReview
              sourceResultId={view.sourceCandidate.candidate_result_id}
              binding={forwardReview}
              onSelect={setForwardReview}
              disabled={pending}
            />
          ) : null}
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
            className="app-button app-button-primary mt-3 min-h-10 rounded-[var(--app-radius-control)] px-4 py-2 text-xs font-semibold"
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
