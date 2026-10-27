import type { ShadowResearchCandidate } from '../api';
import type { ShadowResearchCopy } from './shadow-research-copy';

export type CandidateDecisionFormsProps = {
  approvals: Record<string, boolean>;
  approvalError?: string | null;
  candidate: ShadowResearchCandidate;
  copy: ShadowResearchCopy;
  eligible: boolean;
  notes: Record<string, string>;
  onApprovalChange: (value: boolean) => void;
  onApprove: () => void;
  onNoteChange: (value: string) => void;
  onPause: () => void;
  onPauseConfirmationChange: (value: boolean) => void;
  onPauseNoteChange: (value: string) => void;
  pauseConfirmations: Record<string, boolean>;
  pauseNotes: Record<string, string>;
  reinstatable?: boolean;
  reinstateConfirmations?: Record<string, boolean>;
  reinstateNotes?: Record<string, string>;
  reinstateError?: string | null;
  onReinstate?: () => void;
  onReinstateConfirmationChange?: (value: boolean) => void;
  onReinstateNoteChange?: (value: string) => void;
  pending: boolean;
  promotionStage: string | undefined;
  revocable: boolean;
  zh: boolean;
};

export function formatApprovalError(error: string, zh: boolean): string {
  if (!zh) return error;
  if (
    error.includes('daily_strategy_operating_constraints_candidate_mismatch')
  ) {
    return '候选策略未包含在当日备份快照中（存证不匹配），系统拒绝未经验证的策略晋级';
  }
  if (error.includes('candidate_account_qualification_required')) {
    return '候选策略尚未通过账户级资格认证';
  }
  if (error.includes('daily_strategy_operating_constraints_incomplete')) {
    return '候选策略操作约束与风控假设不完整';
  }
  if (error.includes('canonical_paper_shadow_stage_conflict')) {
    return '策略前向模拟阶段冲突';
  }
  if (error.includes('candidate_is_not_verified_daily_winner')) {
    return '候选策略不是经核准的当日优胜策略';
  }
  if (error.includes('automated_decision_cannot_create_human_approval')) {
    return '自动化身份不能签署人工复核批准';
  }
  if (error.includes('no historical promotion record found')) {
    return '未找到历史晋级记录，不能执行冠军恢复';
  }
  if (error.includes('is already in paper_shadow')) {
    return '该策略当前已处于前向模拟阶段，无需恢复';
  }
  if (error.includes('reinstatement requires exact human confirmation')) {
    return '恢复操作需要明确的人工确认';
  }
  if (error.includes('missing readiness requirements for reinstatement')) {
    return '策略缺少恢复所需的完备验证前提';
  }
  return error;
}

export function CandidateDecisionForms({
  approvals,
  approvalError,
  candidate,
  copy,
  eligible,
  notes,
  onApprovalChange,
  onApprove,
  onNoteChange,
  onPause,
  onPauseConfirmationChange,
  onPauseNoteChange,
  pauseConfirmations,
  pauseNotes,
  reinstatable,
  reinstateConfirmations,
  reinstateNotes,
  reinstateError,
  onReinstate,
  onReinstateConfirmationChange,
  onReinstateNoteChange,
  pending,
  promotionStage,
  revocable,
  zh,
}: CandidateDecisionFormsProps) {
  return (
    <>
      {eligible ? (
        <div
          className="space-y-4 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-accent)_40%,var(--app-border))] bg-[var(--app-surface-raised)] p-5"
          data-testid="candidate-approval-form"
        >
          <div className="flex items-center justify-between border-b border-[var(--app-divider)] pb-2.5">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
              <span className="size-2 rounded-full bg-[var(--app-accent)]" />
              {zh ? '人工复核与授权决策' : 'Human Review & Authorization'}
            </h4>
            <span className="app-type-micro font-medium text-[var(--app-text-tertiary)]">
              {zh
                ? '需要人工核准后方可进入前向模拟'
                : 'Human approval required for paper shadow'}
            </span>
          </div>
          <div className="max-w-2xl space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-[var(--app-text)]">
                {copy.approvalNote}
              </span>
              <textarea
                className="app-input mt-1.5 min-h-20 w-full resize-y rounded-[var(--app-radius-control)] p-2.5 font-sans text-xs text-[var(--app-text)] focus:border-[var(--app-accent)]"
                placeholder={
                  zh
                    ? '请输入复核依据、风险评估或前向观察理由…'
                    : 'Enter review notes and forward observation rationale…'
                }
                onChange={(event) => onNoteChange(event.target.value)}
                value={notes[candidate.candidate_id] ?? ''}
              />
            </label>
            <label className="flex cursor-pointer items-start gap-2.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 text-xs leading-5 text-[var(--app-text-secondary)] transition-colors hover:border-[var(--app-border)]">
              <input
                checked={approvals[candidate.candidate_id] ?? false}
                className="mt-0.5 size-4 cursor-pointer rounded accent-[var(--app-accent)]"
                onChange={(event) => onApprovalChange(event.target.checked)}
                type="checkbox"
              />
              <span>{copy.approvalConfirm}</span>
            </label>
            <div>
              <button
                className="app-button app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-5 py-2 text-xs font-semibold"
                disabled={
                  pending ||
                  !approvals[candidate.candidate_id] ||
                  !notes[candidate.candidate_id]?.trim()
                }
                onClick={onApprove}
                type="button"
              >
                {pending
                  ? copy.approving
                  : promotionStage === 'paused'
                    ? copy.reapprove
                    : copy.approve}
              </button>
            </div>
            {approvalError ? (
              <div
                role="alert"
                className="rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] p-3 text-xs text-[var(--app-danger-text)] animate-in fade-in"
              >
                <div className="font-semibold">
                  {zh
                    ? '审核被拦截 / 无法进入前向模拟：'
                    : 'Approval rejected: '}
                </div>
                <div className="mt-1 leading-relaxed">
                  {formatApprovalError(approvalError, zh)}
                </div>
                <div className="mt-1.5 font-mono app-type-micro opacity-75">
                  {approvalError}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {revocable ? (
        <div
          className="space-y-4 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-5"
          data-testid="candidate-pause-form"
        >
          <div className="flex items-center justify-between border-b border-[var(--app-divider)] pb-2.5">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
              <span className="size-2 rounded-full bg-[var(--app-warning)]" />
              {zh ? '前向模拟暂停与撤销' : 'Pause / Revoke Simulation'}
            </h4>
          </div>
          <div className="max-w-2xl space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-[var(--app-text)]">
                {copy.pauseNote}
              </span>
              <textarea
                className="app-input mt-1.5 min-h-20 w-full resize-y rounded-[var(--app-radius-control)] p-2.5 font-sans text-xs text-[var(--app-text)] focus:border-[var(--app-warning)]"
                placeholder={
                  zh ? '请输入暂停或撤销的原因…' : 'Enter revocation reason…'
                }
                onChange={(event) => onPauseNoteChange(event.target.value)}
                value={pauseNotes[candidate.candidate_id] ?? ''}
              />
            </label>
            <label className="flex cursor-pointer items-start gap-2.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 text-xs leading-5 text-[var(--app-text-secondary)] transition-colors hover:border-[var(--app-border)]">
              <input
                checked={pauseConfirmations[candidate.candidate_id] ?? false}
                className="mt-0.5 size-4 cursor-pointer rounded accent-[var(--app-warning)]"
                onChange={(event) =>
                  onPauseConfirmationChange(event.target.checked)
                }
                type="checkbox"
              />
              <span>{copy.pauseConfirm}</span>
            </label>
            <div>
              <button
                className="app-button app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-5 py-2 text-xs font-semibold"
                disabled={
                  pending ||
                  !pauseConfirmations[candidate.candidate_id] ||
                  !pauseNotes[candidate.candidate_id]?.trim()
                }
                onClick={onPause}
                type="button"
              >
                {pending ? copy.pausing : copy.pause}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {reinstatable ? (
        <div
          className="space-y-4 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-success-border)_50%,var(--app-border))] bg-[var(--app-surface-raised)] p-5"
          data-testid="candidate-reinstate-form"
        >
          <div className="flex items-center justify-between border-b border-[var(--app-divider)] pb-2.5">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
              <span className="size-2 rounded-full bg-[var(--app-success-text)]" />
              {copy.reinstateTitle}
            </h4>
            <span className="app-type-micro font-medium text-[var(--app-text-tertiary)]">
              {zh ? '已验证冠军降级兜底' : 'Verified champion safety fallback'}
            </span>
          </div>
          <p className="text-xs text-[var(--app-text-secondary)]">
            {copy.reinstateSubtitle}
          </p>
          <div className="max-w-2xl space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-[var(--app-text)]">
                {copy.reinstateNote}
              </span>
              <textarea
                aria-label={copy.reinstateNote}
                className="app-input mt-1.5 min-h-20 w-full resize-y rounded-[var(--app-radius-control)] p-2.5 font-sans text-xs text-[var(--app-text)] focus:border-[var(--app-success-text)]"
                data-testid="reinstatement-reason-input"
                placeholder={
                  zh
                    ? '请输入恢复冠军策略的原因（如：实验性挑战者策略已撤回，回退至历史核准冠军）…'
                    : 'Enter reinstatement rationale (e.g., experimental challenger withdrawn, falling back to verified champion)…'
                }
                onChange={(event) =>
                  onReinstateNoteChange?.(event.target.value)
                }
                value={reinstateNotes?.[candidate.candidate_id] ?? ''}
              />
            </label>
            <label className="flex cursor-pointer items-start gap-2.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 text-xs leading-5 text-[var(--app-text-secondary)] transition-colors hover:border-[var(--app-border)]">
              <input
                checked={
                  reinstateConfirmations?.[candidate.candidate_id] ?? false
                }
                className="mt-0.5 size-4 cursor-pointer rounded accent-[var(--app-success-text)]"
                data-testid="reinstatement-confirmation-checkbox"
                onChange={(event) =>
                  onReinstateConfirmationChange?.(event.target.checked)
                }
                type="checkbox"
              />
              <span>{copy.reinstateConfirm}</span>
            </label>
            <div>
              <button
                className="app-button app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-5 py-2 text-xs font-semibold"
                data-testid="reinstate-candidate-button"
                disabled={
                  pending ||
                  !reinstateConfirmations?.[candidate.candidate_id] ||
                  !reinstateNotes?.[candidate.candidate_id]?.trim()
                }
                onClick={onReinstate}
                type="button"
              >
                {pending ? copy.reinstating : copy.reinstate}
              </button>
            </div>
            {reinstateError ? (
              <div
                role="alert"
                className="rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] p-3 text-xs text-[var(--app-danger-text)] animate-in fade-in"
              >
                <div className="font-semibold">
                  {zh
                    ? '恢复操作被拦截 / 无法恢复前向模拟：'
                    : 'Reinstatement rejected: '}
                </div>
                <div className="mt-1 leading-relaxed">
                  {formatApprovalError(reinstateError, zh)}
                </div>
                <div className="mt-1.5 font-mono app-type-micro opacity-75">
                  {reinstateError}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
