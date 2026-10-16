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
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 basis-80">
          <h3 className="max-w-4xl break-words text-xl font-semibold leading-7 text-[var(--app-text)] sm:text-2xl sm:leading-8">
            {comparison.economic_hypothesis || candidate.draft_id}
          </h3>
          <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
            {comparison.research_capital_mode === 'normalized_notional'
              ? zh
                ? '独立名义本金研究'
                : 'Normalized-notional research'
              : candidate.recommendation.replace(/_/g, ' ')}
            {' · '}
            {formatTimestamp(candidate.updated_at)}
          </p>
        </div>
        <a
          href={`/backtest?strategy=${encodeURIComponent(candidate.draft_id || candidate.candidate_id)}&source=ai_research`}
          data-testid="shadow-research-clone-backtest"
          className="app-button-secondary inline-flex min-h-11 items-center justify-center gap-2 px-4 py-2 text-xs font-semibold"
          title={copy.openInStrategyLabDetail}
        >
          {copy.openInStrategyLab} &rarr;
        </a>
        <div className="flex basis-full flex-wrap items-center gap-2">
          <span
            className="rounded-full border border-[var(--app-divider)] px-2.5 py-1 text-xs font-semibold"
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
            <span className="rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-2.5 py-1 text-xs font-semibold text-[var(--app-success-text)]">
              {copy.winnerBadge}
            </span>
          ) : null}
          {isResearchWinner ? (
            <span className="rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-2.5 py-1 text-xs font-semibold text-[var(--app-text)]">
              {copy.researchWinnerBadge}
            </span>
          ) : null}
          {candidate.comparison.iteration_lineage ? (
            <span className="rounded-full border border-[var(--app-divider)] px-2.5 py-1 text-xs font-semibold">
              {copy.iterationRound}{' '}
              {candidate.comparison.iteration_lineage.iteration_number}/
              {candidate.comparison.iteration_lineage.total_iterations}
            </span>
          ) : null}
        </div>
      </header>
      {recordedBlockers.length ? (
        <p
          role="status"
          className="border-l-2 border-[var(--app-warning-border)] pl-4 text-xs leading-5 text-[var(--app-warning-text)]"
        >
          {copy.blockers}:{' '}
          {recordedBlockers
            .map((item) => formatPublicCode(item, locale))
            .join(' · ')}
        </p>
      ) : null}

      {comparison.deployment_validation ? (
        <p className="text-xs text-[var(--app-text-secondary)]">
          {zh ? '独立最终验证' : 'Independent final validation'}:{' '}
          {formatPublicStatus(comparison.deployment_validation.status, locale)}
        </p>
      ) : null}

      <CandidateResearchResults candidate={candidate} copy={copy} />

      {comparison.research_capital_mode === 'normalized_notional' ? (
        <ShadowResearchObservations candidate={candidate} defaultOpen />
      ) : null}

      <section
        className="grid min-w-0 gap-4 border-y border-[var(--app-divider)] py-4 md:grid-cols-2"
        data-testid="research-evidence-next-step"
      >
        <EvidenceList items={missingEvidence} title={copy.blockers} />
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-[var(--app-text)]">
            {zh ? '下一步' : 'Next step'}
          </h4>
          <p className="mt-2 text-sm leading-6 text-[var(--app-text-secondary)]">
            {eligible
              ? zh
                ? '核对研究证据并完成下方人工复核，仅批准 Paper / Shadow。'
                : 'Review the evidence and complete the human review below for paper/shadow only.'
              : revocable
                ? zh
                  ? '复核当前模拟与建议来源；需要时可在下方暂停。'
                  : 'Review current paper evidence and recommendation source; pause below when needed.'
                : comparison.research_capital_mode === 'normalized_notional'
                  ? zh
                    ? '查看下方已保存的前向观察与独立模拟结果。独立最终验证和账户资格仍需分别满足。'
                    : 'Review the saved forward observations and independent paper results below. Independent final validation and account qualification remain separate requirements.'
                  : zh
                    ? '补齐已记录的证据缺口后，再复核该候选；当前状态不授予账户或交易权限。'
                    : 'Resolve the recorded evidence gaps before reviewing this candidate again. Current state grants no account or trading authority.'}
          </p>
          {comparison.risk_impact ? (
            <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
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
        <p className="app-muted mt-4 text-xs leading-5">
          {copy.notDailyWinner}
        </p>
      ) : null}

      {eligible ? (
        <div className="mt-3 border-t border-[var(--app-divider)] pt-2.5">
          <label className="text-xs font-semibold text-[var(--app-text)]">
            {copy.approvalNote}
            <textarea
              className="app-input mt-1.5 min-h-12 w-full resize-y py-1 text-xs"
              onChange={(event) => onNoteChange(event.target.value)}
              value={notes[candidate.candidate_id] ?? ''}
            />
          </label>
          <label className="mt-2 flex items-start gap-2 text-xs leading-5 text-[var(--app-muted)]">
            <input
              checked={approvals[candidate.candidate_id] ?? false}
              className="mt-1"
              onChange={(event) => onApprovalChange(event.target.checked)}
              type="checkbox"
            />
            <span>{copy.approvalConfirm}</span>
          </label>
          <button
            className="app-button-primary mt-2 min-h-9 px-3 py-1.5 text-xs font-semibold"
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
      ) : null}
      {revocable ? (
        <div className="mt-3 border-t border-[var(--app-divider)] pt-2.5">
          <label className="text-xs font-semibold text-[var(--app-text)]">
            {copy.pauseNote}
            <textarea
              className="app-input mt-1.5 min-h-12 w-full resize-y py-1 text-xs"
              onChange={(event) => onPauseNoteChange(event.target.value)}
              value={pauseNotes[candidate.candidate_id] ?? ''}
            />
          </label>
          <label className="mt-2 flex items-start gap-2 text-xs leading-5 text-[var(--app-muted)]">
            <input
              checked={pauseConfirmations[candidate.candidate_id] ?? false}
              className="mt-1"
              onChange={(event) =>
                onPauseConfirmationChange(event.target.checked)
              }
              type="checkbox"
            />
            <span>{copy.pauseConfirm}</span>
          </label>
          <button
            className="app-button-secondary mt-3 min-h-11 px-4 py-2 text-sm font-semibold"
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
    <div className="min-w-0 border-t border-[var(--app-divider)] pt-4">
      <h4 className="text-sm font-semibold text-[var(--app-text)]">{title}</h4>
      {items.length ? (
        <ul className="app-muted mt-2 list-disc space-y-1 pl-4 text-xs leading-5">
          {items.map((item) => (
            <li key={item} title={item}>
              {formatPublicCode(item, locale)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="app-muted mt-2 text-xs">—</p>
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
                    ? 'text-[var(--app-success-text)]'
                    : sharpeDelta < 0
                      ? 'text-[var(--app-danger-text)]'
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
                    ? 'text-[var(--app-success-text)]'
                    : returnDelta < 0
                      ? 'text-[var(--app-danger-text)]'
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
