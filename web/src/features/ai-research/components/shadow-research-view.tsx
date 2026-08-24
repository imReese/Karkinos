import { usePreferences } from '../../../shared/preferences/context';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { ShadowResearchCandidate, ShadowResearchMetricView } from '../api';
import {
  SHADOW_RESEARCH_COPY,
  type ShadowResearchCopy,
} from './shadow-research-copy';

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
  isDailyWinner,
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
  isDailyWinner: boolean;
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
  return (
    <article
      className="rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] p-4"
      data-testid="shadow-research-candidate"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="app-type-overline text-[var(--app-muted)]">
            {candidate.recommendation.replace(/_/g, ' ')}
          </div>
          <h3 className="mt-2 text-base font-semibold text-[var(--app-text)]">
            {comparison.economic_hypothesis || candidate.draft_id}
          </h3>
        </div>
        <span className="rounded-full border border-[var(--app-divider)] px-2.5 py-1 text-xs font-semibold">
          {candidate.promotion_status === 'paper_shadow_approved'
            ? promotionStage === 'paper_shadow'
              ? copy.approved
              : promotionStateLoaded
                ? copy.paused
                : candidate.status.replace(/_/g, ' ')
            : candidate.status.replace(/_/g, ' ')}
        </span>
        {isDailyWinner ? (
          <span className="rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-2.5 py-1 text-xs font-semibold text-[var(--app-success-text)]">
            {copy.winnerBadge}
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

      {comparison.baseline && comparison.candidate ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <MetricComparison
            label={copy.baseline}
            metrics={comparison.baseline}
          />
          <MetricComparison
            label={copy.candidate}
            metrics={comparison.candidate}
          />
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <EvidenceList
          items={
            comparison.promotion_gate.blockers.length
              ? comparison.promotion_gate.blockers
              : comparison.failure_conditions || []
          }
          title={copy.blockers}
        />
        <EvidenceList
          items={[
            ...(critique?.evidence_gaps || []),
            ...(critique?.contradicted_claims || []),
          ]}
          title={copy.critique}
        />
      </div>
      {comparison.risk_impact ? (
        <p className="app-muted mt-4 text-sm leading-6">
          <span className="font-semibold text-[var(--app-text)]">
            {copy.risk}:{' '}
          </span>
          {comparison.risk_impact}
        </p>
      ) : null}

      {candidate.status === 'awaiting_human_approval' &&
      candidate.recommendation === 'paper_shadow_review' &&
      comparison.promotion_gate.status === 'pass' &&
      !isDailyWinner ? (
        <p className="app-muted mt-4 text-xs leading-5">
          {copy.notDailyWinner}
        </p>
      ) : null}

      {eligible ? (
        <div className="mt-5 border-t border-[var(--app-divider)] pt-4">
          <label className="text-xs font-semibold text-[var(--app-text)]">
            {copy.approvalNote}
            <textarea
              className="app-input mt-2 min-h-20 w-full resize-y"
              onChange={(event) => onNoteChange(event.target.value)}
              value={notes[candidate.candidate_id] ?? ''}
            />
          </label>
          <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--app-muted)]">
            <input
              checked={approvals[candidate.candidate_id] ?? false}
              className="mt-1"
              onChange={(event) => onApprovalChange(event.target.checked)}
              type="checkbox"
            />
            <span>{copy.approvalConfirm}</span>
          </label>
          <button
            className="app-button-primary mt-3 min-h-11 px-4 py-2 text-sm font-semibold"
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
        <div className="mt-5 border-t border-[var(--app-divider)] pt-4">
          <label className="text-xs font-semibold text-[var(--app-text)]">
            {copy.pauseNote}
            <textarea
              className="app-input mt-2 min-h-20 w-full resize-y"
              onChange={(event) => onPauseNoteChange(event.target.value)}
              value={pauseNotes[candidate.candidate_id] ?? ''}
            />
          </label>
          <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--app-muted)]">
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
    </article>
  );
}

export function MetricComparison({
  label,
  metrics,
}: {
  label: string;
  metrics: ShadowResearchMetricView;
}) {
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  return (
    <div className="rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)] p-3">
      <div className="text-xs font-semibold text-[var(--app-muted)]">
        {label}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs sm:grid-cols-3">
        <Metric
          label={copy.return}
          value={formatPercent(metrics.total_return)}
        />
        <Metric label={copy.sharpe} value={metrics.sharpe.toFixed(2)} />
        <Metric
          label={copy.drawdown}
          value={formatPercent(-Math.abs(metrics.max_drawdown))}
        />
        <Metric label={copy.costs} value={formatCurrency(metrics.total_cost)} />
        <Metric
          label={copy.oos}
          value={`${formatPercent(metrics.mean_oos_return)} / ${formatPercent(metrics.worst_oos_return)}`}
        />
        <Metric label={copy.trades} value={String(metrics.total_trades)} />
      </dl>
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[var(--app-muted)]">{label}</dt>
      <dd className="mt-1 font-semibold text-[var(--app-text)]">{value}</dd>
    </div>
  );
}

export function EvidenceList({
  items,
  title,
}: {
  items: string[];
  title: string;
}) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-[var(--app-text)]">{title}</h4>
      {items.length ? (
        <ul className="app-muted mt-2 list-disc space-y-1 pl-4 text-xs leading-5">
          {items.slice(0, 5).map((item) => (
            <li key={item}>{item}</li>
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
    <div className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] p-3">
      <div className="text-xs font-semibold text-[var(--app-muted)]">
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold text-[var(--app-text)]">
        {value}
      </div>
      <div className="app-muted mt-1 truncate text-xs">{detail}</div>
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
