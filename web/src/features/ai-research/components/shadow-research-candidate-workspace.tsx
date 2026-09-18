import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

import { formatTimestamp } from '../../../shared/format';
import {
  useStrategyPromotionStatesQuery,
  type ShadowResearchCandidate,
} from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { CandidateCard } from './shadow-research-view';

export function ShadowResearchCandidateWorkspace({
  approvals,
  candidates,
  copy,
  loading,
  latestRunId,
  notes,
  onApprovalChange,
  onApprove,
  onNoteChange,
  onPause,
  onPauseConfirmationChange,
  onPauseNoteChange,
  pauseConfirmations,
  pauseNotes,
  pending,
  promotionStates,
  verifiedResearchWinnerCandidateIds,
  verifiedWinnerCandidateIds,
}: {
  approvals: Record<string, boolean>;
  candidates: ShadowResearchCandidate[];
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  loading: boolean;
  latestRunId: string | null;
  notes: Record<string, string>;
  onApprovalChange: Dispatch<SetStateAction<Record<string, boolean>>>;
  onApprove: (candidate: ShadowResearchCandidate) => Promise<void>;
  onNoteChange: Dispatch<SetStateAction<Record<string, string>>>;
  onPause: (candidate: ShadowResearchCandidate) => Promise<void>;
  onPauseConfirmationChange: Dispatch<SetStateAction<Record<string, boolean>>>;
  onPauseNoteChange: Dispatch<SetStateAction<Record<string, string>>>;
  pauseConfirmations: Record<string, boolean>;
  pauseNotes: Record<string, string>;
  pending: boolean;
  promotionStates: ReturnType<typeof useStrategyPromotionStatesQuery>;
  verifiedResearchWinnerCandidateIds: Set<string>;
  verifiedWinnerCandidateIds: Set<string>;
}) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(
    null,
  );

  const ordered = [...candidates].sort((left, right) =>
    right.updated_at.localeCompare(left.updated_at),
  );
  const current = ordered.filter(
    (candidate) =>
      candidate.run_id === latestRunId ||
      candidate.promotion_status === 'paper_shadow_approved' ||
      verifiedWinnerCandidateIds.has(candidate.candidate_id) ||
      verifiedResearchWinnerCandidateIds.has(candidate.candidate_id),
  );
  const currentIds = new Set(
    current.map((candidate) => candidate.candidate_id),
  );
  const historical = ordered.filter(
    (candidate) => !currentIds.has(candidate.candidate_id),
  );
  const preferredCandidate =
    current.find((candidate) =>
      verifiedWinnerCandidateIds.has(candidate.candidate_id),
    ) ??
    current.find((candidate) =>
      verifiedResearchWinnerCandidateIds.has(candidate.candidate_id),
    ) ??
    current.find(
      (candidate) => candidate.promotion_status === 'paper_shadow_approved',
    ) ??
    current[0] ??
    ordered[0] ??
    null;
  const preferredCandidateId = preferredCandidate?.candidate_id ?? null;
  const candidateIdentity = ordered
    .map((candidate) => candidate.candidate_id)
    .join('|');
  const selectedCandidate =
    ordered.find(
      (candidate) => candidate.candidate_id === selectedCandidateId,
    ) ?? preferredCandidate;

  useEffect(() => {
    if (!preferredCandidateId) {
      if (selectedCandidateId !== null) {
        setSelectedCandidateId(null);
      }
      return;
    }
    const candidateIds = candidateIdentity ? candidateIdentity.split('|') : [];
    if (
      selectedCandidateId === null ||
      !candidateIds.includes(selectedCandidateId)
    ) {
      setSelectedCandidateId(preferredCandidateId);
    }
  }, [candidateIdentity, preferredCandidateId, selectedCandidateId]);

  if (candidates.length === 0) {
    return (
      <div className="mt-6 grid gap-4">
        <div className="border-y border-dashed border-[var(--app-divider)] p-5 text-sm text-[var(--app-muted)]">
          {loading ? copy.running : copy.noCandidates}
        </div>
      </div>
    );
  }

  const renderRegistryRow = (candidate: ShadowResearchCandidate) => {
    const selected = candidate.candidate_id === selectedCandidate?.candidate_id;
    const lineage = candidate.comparison.iteration_lineage;
    const statusLabel =
      candidate.promotion_status === 'paper_shadow_approved'
        ? copy.approved
        : candidate.status.replace(/_/g, ' ');
    const rowClassName = [
      'grid w-full min-w-0 gap-2 px-1 py-3 text-left transition-colors sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center',
      selected
        ? 'bg-[color-mix(in_srgb,var(--app-accent)_7%,transparent)]'
        : 'hover:bg-[color-mix(in_srgb,var(--app-surface-overlay)_45%,transparent)]',
    ].join(' ');

    return (
      <button
        aria-pressed={selected}
        className={rowClassName}
        data-candidate-id={candidate.candidate_id}
        data-testid="shadow-research-candidate-row"
        key={candidate.candidate_id}
        onClick={() => setSelectedCandidateId(candidate.candidate_id)}
        type="button"
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-[var(--app-text)]">
            {candidate.comparison.economic_hypothesis || candidate.draft_id}
          </span>
          <span className="app-type-micro mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[var(--app-text-tertiary)]">
            <span>{statusLabel}</span>
            {lineage ? (
              <span>
                {copy.iterationRound} {lineage.iteration_number}/
                {lineage.total_iterations}
              </span>
            ) : null}
            <span>{formatTimestamp(candidate.updated_at)}</span>
          </span>
        </span>
        <span className="flex shrink-0 flex-wrap items-center gap-1.5 sm:justify-end">
          {verifiedWinnerCandidateIds.has(candidate.candidate_id) ? (
            <span className="rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-2 py-0.5 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-success-text)]">
              {copy.winnerBadge}
            </span>
          ) : null}
          {verifiedResearchWinnerCandidateIds.has(candidate.candidate_id) ? (
            <span className="rounded-full border border-[var(--app-divider)] px-2 py-0.5 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-text-secondary)]">
              {copy.researchWinnerBadge}
            </span>
          ) : null}
        </span>
      </button>
    );
  };

  const renderSelectedCandidate = (candidate: ShadowResearchCandidate) => (
    <CandidateCard
      approvals={approvals}
      candidate={candidate}
      copy={copy}
      isDailyWinner={verifiedWinnerCandidateIds.has(candidate.candidate_id)}
      isResearchWinner={verifiedResearchWinnerCandidateIds.has(
        candidate.candidate_id,
      )}
      notes={notes}
      onPause={() => void onPause(candidate)}
      onPauseConfirmationChange={(checked) =>
        onPauseConfirmationChange((currentState) => ({
          ...currentState,
          [candidate.candidate_id]: checked,
        }))
      }
      onPauseNoteChange={(value) =>
        onPauseNoteChange((currentState) => ({
          ...currentState,
          [candidate.candidate_id]: value,
        }))
      }
      onApprovalChange={(checked) =>
        onApprovalChange((currentState) => ({
          ...currentState,
          [candidate.candidate_id]: checked,
        }))
      }
      onApprove={() => void onApprove(candidate)}
      onNoteChange={(value) =>
        onNoteChange((currentState) => ({
          ...currentState,
          [candidate.candidate_id]: value,
        }))
      }
      pauseConfirmations={pauseConfirmations}
      pauseNotes={pauseNotes}
      pending={pending}
      promotionStage={
        promotionStates.data?.find(
          (state) =>
            state.strategy_id === 'ai_formula_shadow:' + candidate.candidate_id,
        )?.stage
      }
      promotionStateLoaded={promotionStates.isSuccess}
    />
  );

  return (
    <section
      className="mt-6 min-w-0"
      data-testid="shadow-research-candidate-workspace"
    >
      <div className="border-b border-[var(--app-divider)] pb-2">
        <h3 className="app-type-section-title text-[var(--app-text)]">
          {copy.candidateRegistry}
        </h3>
        <p className="app-muted mt-1 text-xs leading-5">
          {copy.candidateRegistryDetail}
        </p>
      </div>

      <div className="mt-3 grid min-w-0 gap-5 2xl:grid-cols-[minmax(300px,0.42fr)_minmax(0,1fr)] 2xl:items-start">
        <div className="min-w-0">
          <div className="flex items-baseline justify-between gap-3 pb-2">
            <h4 className="text-sm font-semibold text-[var(--app-text)]">
              {copy.currentCandidates}
            </h4>
            <span className="app-type-micro tabular-nums text-[var(--app-text-tertiary)]">
              {current.length}
            </span>
          </div>
          <div
            className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
            data-testid="shadow-research-current-registry"
          >
            {current.map(renderRegistryRow)}
          </div>

          {historical.length ? (
            <details
              className="mt-4 border-y border-[var(--app-divider)]"
              onToggle={(event) => setHistoryOpen(event.currentTarget.open)}
              open={historyOpen}
            >
              <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-3">
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-[var(--app-text)]">
                    {copy.candidateHistory}
                  </span>
                  <span className="app-type-micro mt-0.5 block text-[var(--app-text-secondary)]">
                    {copy.candidateHistoryDetail(historical.length)}
                  </span>
                </span>
                <span className="app-type-micro shrink-0 tabular-nums text-[var(--app-text-tertiary)]">
                  {historyOpen ? '−' : '+'}
                </span>
              </summary>
              {historyOpen ? (
                <div
                  className="divide-y divide-[var(--app-divider)] border-t border-[var(--app-divider)]"
                  data-testid="shadow-research-history-registry"
                >
                  {historical.map(renderRegistryRow)}
                </div>
              ) : null}
            </details>
          ) : null}
        </div>

        {selectedCandidate ? (
          <section
            aria-label={copy.selectedCandidate}
            className="min-w-0"
            data-testid="shadow-research-candidate-inspector"
          >
            <div className="app-product-mark mb-2">
              {copy.selectedCandidate}
            </div>
            {renderSelectedCandidate(selectedCandidate)}
          </section>
        ) : null}
      </div>
    </section>
  );
}
