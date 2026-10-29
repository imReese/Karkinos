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
import {
  formatCandidateTitle,
  formatDraftSummaryName,
  resolveCandidateEngine,
} from '../candidate-display';
import { CandidateDecisionForms } from './candidate-decision-forms';

export function CandidateCard({
  candidate,
  copy,
  notes,
  approvals,
  approvalError,
  onNoteChange,
  onApprovalChange,
  onApprove,
  pauseNotes,
  pauseConfirmations,
  onPauseNoteChange,
  onPauseConfirmationChange,
  onPause,
  reinstatable: explicitReinstatable,
  reinstateNotes,
  reinstateConfirmations,
  reinstateError,
  onReinstateNoteChange,
  onReinstateConfirmationChange,
  onReinstate,
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
  approvalError?: string | null;
  onNoteChange: (value: string) => void;
  onApprovalChange: (value: boolean) => void;
  onApprove: () => void;
  pauseNotes: Record<string, string>;
  pauseConfirmations: Record<string, boolean>;
  onPauseNoteChange: (value: string) => void;
  onPauseConfirmationChange: (value: boolean) => void;
  onPause: () => void;
  reinstatable?: boolean;
  reinstateNotes?: Record<string, string>;
  reinstateConfirmations?: Record<string, boolean>;
  reinstateError?: string | null;
  onReinstateNoteChange?: (value: string) => void;
  onReinstateConfirmationChange?: (value: boolean) => void;
  onReinstate?: () => void;
  promotionStage: string | undefined;
  promotionStateLoaded: boolean;
  publicationUsable: boolean;
  isDailyWinner: boolean;
  isResearchWinner: boolean;
  pending: boolean;
}) {
  const comparison = candidate.comparison;
  const hasHistoricalPromotion =
    promotionStage !== undefined && promotionStage !== 'paper_shadow';
  const isCurrentlyActiveInPaperShadow = promotionStage === 'paper_shadow';

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
  const reinstatable =
    explicitReinstatable ??
    (hasHistoricalPromotion &&
      (promotionStage === 'paused' ||
        promotionStage === 'retired' ||
        candidate.promotion_status === 'paper_shadow_approved') &&
      !isCurrentlyActiveInPaperShadow &&
      !eligible);
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
      <div className="app-dsh-cockpit-hud relative rounded-[var(--app-radius-control)] p-4 transition-all">
        <div className="app-dsh-light-strip" />
        <div className="app-dsh-ambient-glow" />
        <div className="relative z-10 flex min-w-0 flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="app-type-overline text-[var(--app-text-tertiary)] tracking-widest font-mono">
                {zh ? '审阅策略' : 'Selected strategy'}
              </span>
              <h3 className="font-sans text-sm sm:text-base font-bold tracking-tight text-[var(--app-text)]">
                {formatCandidateTitle(candidate, zh)}
              </h3>
              <span
                className="inline-flex items-center gap-1 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-0.5 font-mono app-type-micro text-[var(--app-text-tertiary)]"
                title={candidate.draft_id || candidate.candidate_id}
              >
                <span className="select-none text-[var(--app-text-tertiary)]">
                  ID:
                </span>
                <span className="max-w-[140px] truncate font-medium text-[var(--app-text-secondary)] sm:max-w-[220px]">
                  {candidate.draft_id || candidate.candidate_id}
                </span>
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 font-mono app-type-micro font-medium text-[var(--app-text)]">
                <span className="size-1 rounded-full bg-[var(--app-accent)]" />
                {resolveCandidateEngine(candidate)}
              </span>
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
                <span
                  className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-semibold ${
                    (candidate.comparison.candidate?.total_return ?? 0) >= 0
                      ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                      : 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
                  }`}
                >
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
                  <span className="font-mono tabular-nums font-semibold">
                    {candidate.comparison.iteration_lineage.iteration_number}/
                    {candidate.comparison.iteration_lineage.total_iterations}
                  </span>
                </span>
              ) : null}
              <span className="text-[var(--app-text-tertiary)]">·</span>
              <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
                {formatTimestamp(candidate.updated_at)}
              </span>
            </div>
          </div>
          <a
            href={`/backtest?strategy=${encodeURIComponent(candidate.draft_id || candidate.candidate_id)}&source=ai_research`}
            data-testid="shadow-research-clone-backtest"
            className="app-button app-button-secondary inline-flex min-h-11 shrink-0 items-center justify-center gap-1.5 rounded-[var(--app-radius-control)] px-3.5 py-2 text-xs font-semibold tracking-wide"
            title={copy.openInStrategyLabDetail}
          >
            <span>{copy.openInStrategyLab}</span>
            <span aria-hidden="true">&rarr;</span>
          </a>
        </div>

        {comparison.economic_hypothesis ? (
          <div className="relative z-10 mt-3 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-3 text-xs leading-relaxed text-[var(--app-text)]">
            <span className="app-type-overline mb-1.5 block font-semibold text-[var(--app-text-tertiary)] tracking-wider">
              {zh
                ? '经济学假说与演化逻辑'
                : 'Economic Hypothesis & Evolution Logic'}
            </span>
            <p className="whitespace-pre-wrap font-sans app-type-body sm:text-sm leading-relaxed text-[var(--app-text-secondary)] font-normal">
              {comparison.economic_hypothesis}
            </p>
          </div>
        ) : null}

        <div className="relative z-10 mt-3.5 border-t border-[var(--app-divider)] pt-3">
          <CritiqueEvolutionTimeline candidate={candidate} copy={copy} />
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
                : reinstatable
                  ? zh
                    ? '已暂停/退役 · 可恢复冠军前向模拟'
                    : 'Paused/retired · Reinstatable champion'
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

      {eligible || revocable || reinstatable ? (
        <CandidateDecisionForms
          approvals={approvals}
          approvalError={approvalError}
          candidate={candidate}
          copy={copy}
          eligible={eligible}
          notes={notes}
          onApprovalChange={onApprovalChange}
          onApprove={onApprove}
          onNoteChange={onNoteChange}
          onPause={onPause}
          onPauseConfirmationChange={onPauseConfirmationChange}
          onPauseNoteChange={onPauseNoteChange}
          pauseConfirmations={pauseConfirmations}
          pauseNotes={pauseNotes}
          reinstatable={reinstatable}
          reinstateConfirmations={reinstateConfirmations}
          reinstateNotes={reinstateNotes}
          reinstateError={reinstateError}
          onReinstate={onReinstate}
          onReinstateConfirmationChange={onReinstateConfirmationChange}
          onReinstateNoteChange={onReinstateNoteChange}
          pending={pending}
          promotionStage={promotionStage}
          revocable={revocable}
          zh={zh}
        />
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
  const isTextual = value.length > 5 && !/^[\d\s/.,:+\-%—]+$/.test(value);
  return (
    <div className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3 shadow-sm transition-colors">
      <div className="app-type-overline truncate text-[var(--app-text-tertiary)]">
        {label}
      </div>
      <div
        className={`mt-1 font-bold tabular-nums text-[var(--app-text)] ${
          isTextual
            ? 'app-type-subsection-title line-clamp-1 font-sans'
            : 'app-type-metric font-mono sm:text-xl'
        }`}
        title={value}
      >
        {value}
      </div>
      <div className="mt-1 break-words app-type-micro leading-relaxed text-[var(--app-text-secondary)]">
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
  const { locale } = usePreferences();
  const zh = locale === 'zh';
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
      className="relative min-w-0 pt-1"
      data-testid="critique-evolution-timeline"
    >
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-2.5">
          <div className="flex items-center gap-2 text-xs font-bold text-[var(--app-text)] font-mono uppercase tracking-tight">
            <span className="app-dsh-pulse-beacon size-2 rounded-full bg-[var(--app-accent)] shadow-[0_0_8px_var(--app-accent)]" />
            <span>
              {resolveCandidateEngine(candidate).toUpperCase()} ·{' '}
              {copy.critiqueTrajectory}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            {lineage?.sequential_feedback_bound ? (
              <span className="rounded-full border border-[var(--app-accent-border,var(--app-divider))] bg-[var(--app-accent-bg)] px-2.5 py-0.5 app-type-micro font-medium text-[var(--app-accent)]">
                {copy.sequentialFeedbackBound}
              </span>
            ) : null}
          </div>
        </div>

        <div className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
          <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
            <div className="app-type-overline text-[var(--app-text-tertiary)] tracking-wider">
              {lineage
                ? `${copy.iterationRound} ${lineage.iteration_number}/${lineage.total_iterations}`
                : copy.iterationRound}
            </div>
            <div className="mt-1 font-mono text-xs tabular-nums text-[var(--app-text)] font-semibold truncate">
              {lineage?.formula_fingerprint
                ? `FP: ${lineage.formula_fingerprint.slice(0, 16)}…`
                : candidate.draft_id}
            </div>
            <div className="app-type-micro mt-0.5 text-[var(--app-text-tertiary)] font-sans truncate">
              {lineage?.parent_draft_id
                ? `${zh ? '父代: ' : 'Parent: '}${formatDraftSummaryName(lineage.parent_draft_id, zh)}`
                : zh
                  ? '无父代记录'
                  : 'Parent not recorded'}
            </div>
          </div>

          <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
            <div className="app-type-overline text-[var(--app-text-tertiary)] tracking-wider">
              {copy.critique}
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5 app-type-micro font-sans">
              <span className="font-mono font-semibold text-[var(--app-text)]">
                {critique ? (critique.supported_claims?.length ?? 0) : '—'}
              </span>
              <span className="text-[var(--app-text-secondary)]">
                supported claims ·
              </span>
              <span className="font-mono font-semibold text-[var(--app-text)]">
                {critique ? (critique.contradicted_claims?.length ?? 0) : '—'}
              </span>
              <span className="text-[var(--app-text-secondary)]">
                contradicted
              </span>
            </div>
            {critique?.uncertainty ? (
              <div className="mt-1 app-type-micro truncate font-mono text-[var(--app-text-tertiary)]">
                {critique.uncertainty}
              </div>
            ) : null}
          </div>

          <div className="min-w-0 border-l border-[var(--app-divider)] pl-4">
            <div className="app-type-overline text-[var(--app-text-tertiary)] tracking-wider">
              {copy.metricEvolution}
            </div>
            <div className="mt-1 font-mono text-xs tabular-nums font-bold">
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
                  className={`ml-2.5 ${
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
              <div className="mt-0.5 font-mono app-type-micro text-[var(--app-text-tertiary)]">
                OOS: {target.oos_validation_status} ({target.oos_fold_count}{' '}
                folds)
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
