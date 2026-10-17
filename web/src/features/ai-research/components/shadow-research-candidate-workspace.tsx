import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

import {
  useStrategyPromotionStatesQuery,
  type ShadowResearchCandidate,
} from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { CandidateCard } from './shadow-research-view';
import { usePublicationPolicy } from '../publication-policy-api';

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
  const publication = usePublicationPolicy();
  const usableSources = publication.isSuccess
    ? (publication.data.usable_current_sources ?? [])
    : [];
  const sourceUsable = (candidate: ShadowResearchCandidate) =>
    usableSources.some(
      (source) =>
        source.strategy_id === `ai_formula_shadow:${candidate.candidate_id}`,
    );
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
      <div className="border-y border-[var(--app-divider)] py-8">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {copy.candidateRegistry}
        </div>
        <p className="app-muted mt-2 max-w-2xl text-sm leading-6">
          {loading ? copy.running : copy.noCandidates}
        </p>
      </div>
    );
  }

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
      publicationUsable={sourceUsable(candidate)}
    />
  );

  return (
    <section
      className="min-w-0 space-y-4"
      data-testid="shadow-research-candidate-workspace"
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--app-divider)] pb-4">
        <div className="min-w-0 flex-1 sm:max-w-xl">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="app-type-overline text-[var(--app-text-tertiary)]">
              {copy.candidateRegistry}
            </span>
            <span className="font-mono text-xs tabular-nums text-[var(--app-text-secondary)]">
              {ordered.length} {copy.candidates}
            </span>
          </div>
          <label className="block min-w-0">
            <span className="sr-only">{copy.currentCandidates}</span>
            <select
              className="app-field min-h-10 w-full min-w-0 px-3 py-2 text-xs font-medium text-[var(--app-text)] sm:text-sm"
              data-testid="shadow-research-current-registry"
              onChange={(event) => setSelectedCandidateId(event.target.value)}
              value={selectedCandidate?.candidate_id ?? ''}
            >
              {current.length ? (
                <optgroup label={copy.currentCandidates}>
                  {current.map((candidate) => (
                    <option
                      value={candidate.candidate_id}
                      key={candidate.candidate_id}
                    >
                      {candidate.comparison.economic_hypothesis ||
                        candidate.draft_id}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {historical.length ? (
                <optgroup label={copy.candidateHistory}>
                  {historical.map((candidate) => (
                    <option
                      value={candidate.candidate_id}
                      key={candidate.candidate_id}
                    >
                      {candidate.comparison.economic_hypothesis ||
                        candidate.draft_id}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </select>
          </label>
        </div>
      </div>
      {selectedCandidate ? (
        <section
          aria-label={copy.selectedCandidate}
          className="min-w-0"
          data-testid="shadow-research-candidate-inspector"
        >
          {renderSelectedCandidate(selectedCandidate)}
        </section>
      ) : null}
    </section>
  );
}
