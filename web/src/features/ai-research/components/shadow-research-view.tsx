import { usePreferences } from '../../../shared/preferences/context';
import { formatPercent, formatTimestamp } from '../../../shared/format';
import { ChevronDown } from 'lucide-react';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import type { ShadowResearchCandidate } from '../api';
import { CandidateResearchResults } from './candidate-research-results';
import { ShadowResearchObservations } from './shadow-research-observations';
import { ResearchCandidateDefinition } from './research-candidate-definition';
import type { ShadowResearchCopy } from './shadow-research-copy';

export function CandidateCard({
  candidate,
  copy,
  notes,
  approvals,
  onNoteChange,
  onApprovalChange,
  onApprove,
  pauseNotes,
  pauseConfirmations,
  onPauseNoteChange,
  onPauseConfirmationChange,
  onPause,
  promotionStage,
  promotionStateLoaded,
  publicationUsable,
  isDailyWinner,
  isResearchWinner,
  pending,
}: {
  candidate: ShadowResearchCandidate;
  copy: ShadowResearchCopy;
  notes: Record<string, string>;
  approvals: Record<string, boolean>;
  onNoteChange: (value: string) => void;
  onApprovalChange: (value: boolean) => void;
  onApprove: () => void;
  pauseNotes: Record<string, string>;
  pauseConfirmations: Record<string, boolean>;
  onPauseNoteChange: (value: string) => void;
  onPauseConfirmationChange: (value: boolean) => void;
  onPause: () => void;
  promotionStage: string | undefined;
  promotionStateLoaded: boolean;
  publicationUsable: boolean;
  isDailyWinner: boolean;
  isResearchWinner: boolean;
  pending: boolean;
}) {
  const comparison = candidate.comparison;
  const eligible =
    candidate.status === 'awaiting_human_approval' &&
    candidate.recommendation === 'paper_shadow_review' &&
    comparison.promotion_gate.status === 'pass' &&
    isDailyWinner &&
    (candidate.promotion_status !== 'paper_shadow_approved' ||
      promotionStage === 'paused');
  const revocable =
    candidate.promotion_status === 'paper_shadow_approved' &&
    promotionStage === 'paper_shadow';
  const critique = comparison.deepseek_critique;
  const evidenceGate = comparison.research_gate ?? comparison.promotion_gate;
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const candidateStatus = formatPublicStatus(candidate.status, locale);
  const recordedBlockers = [
    ...new Set([
      ...evidenceGate.blockers,
      ...(comparison.deployment_validation?.blockers ?? []),
    ]),
  ];
  const missingEvidence = recordedBlockers.length
    ? recordedBlockers
    : comparison.failure_conditions || [];
  return (
    <article
      className="min-w-0 space-y-4"
      data-testid="shadow-research-candidate"
    >
      <div className="rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-4">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="app-type-overline text-[var(--app-text-tertiary)]">
                {zh ? '审阅策略' : 'Selected strategy'}
              </span>
              <h3 className="break-all font-mono text-sm font-semibold text-[var(--app-text)]">
                {comparison.economic_hypothesis || candidate.draft_id}
              </h3>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span
                className="inline-flex items-center rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 font-medium text-[var(--app-text)]"
                title={candidate.status}
              >
                {candidate.promotion_status === 'paper_shadow_approved'
                  ? promotionStage === 'paper_shadow' && publicationUsable
                    ? copy.approved
                    : promotionStage === 'paper_shadow'
                      ? copy.publicationUnverified
                      : promotionStateLoaded
                        ? copy.paused
                        : candidateStatus
                  : candidateStatus}
              </span>
              {isDailyWinner ? (
                <span className="inline-flex items-center rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-2.5 py-0.5 font-semibold text-[var(--app-success-text)]">
                  {copy.winnerBadge}
                </span>
              ) : null}
              {isResearchWinner ? (
                <span className="inline-flex items-center rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 font-semibold text-[var(--app-text)]">
                  {copy.researchWinnerBadge}
                </span>
              ) : null}
              {candidate.comparison.iteration_lineage ? (
                <span className="inline-flex items-center rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 font-medium text-[var(--app-text-secondary)]">
                  {copy.iterationRound}{' '}
                  {candidate.comparison.iteration_lineage.iteration_number}/
                  {candidate.comparison.iteration_lineage.total_iterations}
                </span>
              ) : null}
              <span className="text-[var(--app-text-tertiary)]">·</span>
              <span className="text-xs text-[var(--app-text-tertiary)]">
                {formatTimestamp(candidate.updated_at)}
              </span>
            </div>
          </div>
          <a
            href={`/backtest?strategy=${encodeURIComponent(candidate.draft_id || candidate.candidate_id)}&source=ai_research`}
            data-testid="shadow-research-clone-backtest"
            className="app-button app-button-secondary inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
            title={copy.openInStrategyLabDetail}
          >
            <span>{copy.openInStrategyLab}</span>
            <span aria-hidden="true">&rarr;</span>
          </a>
        </div>
      </div>

      <CandidateResearchResults candidate={candidate} copy={copy} />

      {comparison.research_capital_mode === 'normalized_notional' ? (
        <ShadowResearchObservations candidate={candidate} defaultOpen />
      ) : null}

      <section
        className="grid min-w-0 gap-4 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-4 sm:grid-cols-2"
        data-testid="research-evidence-next-step"
      >
        <EvidenceList items={missingEvidence} title={copy.blockers} />
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-[var(--app-text)]">
            {zh ? '复核状态' : 'Review status'}
          </h4>
          <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {eligible
              ? zh
                ? '待人工复核授权'
                : 'Awaiting human authorization'
              : revocable
                ? zh
                  ? '已授权 · 前向模拟运行中'
                  : 'Authorized · Paper simulation active'
                : comparison.research_capital_mode === 'normalized_notional'
                  ? zh
                    ? '前向观察已记录'
                    : 'Forward observation recorded'
                  : zh
                    ? '需补齐证据缺口'
                    : 'Evidence gaps pending'}
          </p>
          {comparison.risk_impact ? (
            <p className="mt-1.5 text-xs text-[var(--app-text-secondary)]">
              <span className="font-semibold">{copy.risk}: </span>
              {comparison.risk_impact}
            </p>
          ) : null}
        </div>
      </section>

      {candidate.status === 'awaiting_human_approval' &&
      candidate.recommendation === 'paper_shadow_review' &&
      comparison.promotion_gate.status === 'pass' &&
      !isDailyWinner ? (
        <p className="app-muted mt-2 text-xs leading-5">
          {copy.notDailyWinner}
        </p>
      ) : null}

      {eligible ? (
        <div className="space-y-4 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-accent)_40%,var(--app-border))] bg-[var(--app-surface-raised)] p-5">
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
          </div>
        </div>
      ) : null}

      {revocable ? (
        <div className="space-y-4 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-5">
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

      <details
        className="group border-t border-[var(--app-divider)] py-4"
        data-testid="research-source-disclosure"
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold">
          {zh
            ? '策略来源、验证范围与模型评议'
            : 'Strategy source, validation scope and model critique'}
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 transition-transform group-open:rotate-180"
          />
        </summary>
        <div className="mt-4 min-w-0 space-y-6">
          <ResearchCandidateDefinition candidate={candidate} />
          <EvidenceList
            items={[
              ...(critique?.evidence_gaps || []),
              ...(critique?.contradicted_claims || []),
            ]}
            title={copy.critique}
          />
          <CritiqueEvolutionTimeline candidate={candidate} copy={copy} />
        </div>
      </details>
    </article>
  );
}

export function EvidenceList({
  items,
  title,
}: {
  items: string[];
  title: string;
}) {
  const { locale } = usePreferences();
  return (
    <div className="min-w-0">
      <h4 className="text-sm font-semibold text-[var(--app-text)]">{title}</h4>
      {items.length ? (
        <ul className="mt-1.5 list-disc space-y-1 pl-4 text-xs leading-5 text-[var(--app-warning-text)]">
          {items.map((item) => (
            <li key={item} title={item}>
              {formatPublicCode(item, locale)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-[var(--app-success-text)]">
          <span className="size-1.5 rounded-full bg-[var(--app-success-text)]" />
          {locale === 'zh' ? '无阻断项' : 'No blockers'}
        </p>
      )}
    </div>
  );
}

export function StatusMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] py-4">
      <div className="text-xs font-semibold text-[var(--app-muted)]">
        {label}
      </div>
      <div className="mt-1 font-mono text-base font-semibold tabular-nums text-[var(--app-text)] sm:text-lg">
        {value}
      </div>
      <div className="app-muted mt-2 break-words text-xs leading-5">
        {detail}
      </div>
    </div>
  );
}

export function Field({
  label,
  value,
  type = 'text',
  onChange,
}: {
  label: string;
  value: string;
  type?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-xs font-semibold text-[var(--app-text)]">
      {label}
      <input
        className="app-input mt-2 min-h-11 w-full"
        onChange={(event) => onChange(event.target.value)}
        type={type}
        value={value}
      />
    </label>
  );
}

export function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="text-xs font-semibold text-[var(--app-text)]">
      {label}
      <input
        className="app-input mt-2 min-h-11 w-full"
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

export function CritiqueEvolutionTimeline({
  candidate,
  copy,
}: {
  candidate: ShadowResearchCandidate;
  copy: ShadowResearchCopy;
}) {
  const comparison = candidate.comparison;
  const critique = comparison.deepseek_critique;
  const lineage = comparison.iteration_lineage;
  const baseline = comparison.baseline;
  const target = comparison.candidate;

  const returnDelta =
    baseline && target ? target.total_return - baseline.total_return : null;
  const sharpeDelta =
    baseline && target ? target.sharpe - baseline.sharpe : null;

  return (
    <div
      className="min-w-0 border-t border-[var(--app-divider)] pt-4"
      data-testid="critique-evolution-timeline"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-2">
        <div className="text-xs font-semibold text-[var(--app-text)]">
          {copy.critiqueTrajectory}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {lineage?.sequential_feedback_bound ? (
            <span className="rounded-full border border-[var(--app-divider)] px-2 py-0.5 app-type-micro font-medium text-[var(--app-text-secondary)]">
              {copy.sequentialFeedbackBound}
            </span>
          ) : null}
        </div>
      </div>

      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
        <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
          <div className="app-muted app-type-micro font-semibold">
            {lineage
              ? `${copy.iterationRound} ${lineage.iteration_number}/${lineage.total_iterations}`
              : copy.iterationRound}
          </div>
          <div className="mt-1 font-mono text-xs tabular-nums text-[var(--app-text)] truncate">
            {lineage?.formula_fingerprint
              ? `FP: ${lineage.formula_fingerprint.slice(0, 16)}…`
              : candidate.draft_id}
          </div>
          <div className="app-muted mt-1 app-type-micro">
            {lineage?.parent_draft_id
              ? `Parent: ${lineage.parent_draft_id}`
              : 'Parent not recorded'}
          </div>
        </div>

        <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
          <div className="app-muted app-type-micro font-semibold">
            {copy.critique}
          </div>
          <div className="mt-1 flex flex-wrap gap-1 app-type-micro">
            <span className="text-[var(--app-success-text)]">
              {critique ? (critique.supported_claims?.length ?? 0) : '—'}{' '}
              supported claims
            </span>
            <span className="text-[var(--app-muted)]">·</span>
            <span className="text-[var(--app-warning-text)]">
              {critique ? (critique.contradicted_claims?.length ?? 0) : '—'}{' '}
              contradicted claims
            </span>
          </div>
          {critique?.uncertainty ? (
            <div className="app-muted mt-1 app-type-micro truncate">
              {critique.uncertainty}
            </div>
          ) : null}
        </div>

        <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
          <div className="app-muted app-type-micro font-semibold">
            {copy.metricEvolution}
          </div>
          <div className="mt-1 font-mono text-xs tabular-nums">
            {sharpeDelta !== null ? (
              <span
                className={
                  sharpeDelta > 0
                    ? 'text-[var(--app-pnl-positive)]'
                    : sharpeDelta < 0
                      ? 'text-[var(--app-pnl-negative)]'
                      : 'text-[var(--app-text)]'
                }
              >
                Sharpe:{' '}
                {sharpeDelta > 0
                  ? `+${sharpeDelta.toFixed(2)}`
                  : sharpeDelta.toFixed(2)}
              </span>
            ) : (
              '—'
            )}
            {returnDelta !== null ? (
              <span
                className={`ml-2 ${
                  returnDelta > 0
                    ? 'text-[var(--app-pnl-positive)]'
                    : returnDelta < 0
                      ? 'text-[var(--app-pnl-negative)]'
                      : 'text-[var(--app-text)]'
                }`}
              >
                Return:{' '}
                {returnDelta > 0
                  ? `+${formatPercent(returnDelta)}`
                  : formatPercent(returnDelta)}
              </span>
            ) : null}
          </div>
          {target ? (
            <div className="app-muted mt-1 app-type-micro">
              OOS: {target.oos_validation_status} ({target.oos_fold_count}{' '}
              folds)
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
