import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  useStrategyPromotionStatesQuery,
  type ShadowResearchCandidate,
} from '../api';
import { formatCandidateOptionLabel } from '../candidate-display';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { CandidateCard } from './shadow-research-view';
import { StrategyEvolutionLineage } from './strategy-evolution-lineage';
import { usePublicationPolicy } from '../publication-policy-api';

export function ShadowResearchCandidateWorkspace({
  approvals,
  approvalError,
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
  approvalError?: string | null;
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
  const { locale } = usePreferences();
  const zh = locale === 'zh';
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

  const prevPreferredRef = useRef<string | null>(null);

  useEffect(() => {
    if (!preferredCandidateId) {
      if (selectedCandidateId !== null) {
        setSelectedCandidateId(null);
      }
      prevPreferredRef.current = null;
      return;
    }
    const candidateIds = candidateIdentity ? candidateIdentity.split('|') : [];
    const preferredChanged =
      prevPreferredRef.current !== null &&
      prevPreferredRef.current !== preferredCandidateId;
    const wasFollowingPreferred =
      selectedCandidateId === prevPreferredRef.current;

    if (
      selectedCandidateId === null ||
      !candidateIds.includes(selectedCandidateId) ||
      (preferredChanged && wasFollowingPreferred)
    ) {
      setSelectedCandidateId(preferredCandidateId);
    }
    prevPreferredRef.current = preferredCandidateId;
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
      approvalError={approvalError}
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

  const registryControl = (
    <label className="inline-flex items-center">
      <span className="sr-only">{copy.currentCandidates}</span>
      <select
        aria-label={copy.currentCandidates}
        className="h-7 max-w-[180px] sm:max-w-[240px] truncate rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-0.5 text-xs font-mono font-medium text-[var(--app-text)] shadow-sm transition-colors focus:border-[var(--app-accent)] focus:outline-none"
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
                {formatCandidateOptionLabel(candidate, zh)}
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
                {formatCandidateOptionLabel(candidate, zh)}
              </option>
            ))}
          </optgroup>
        ) : null}
      </select>
    </label>
  );

  return (
    <section
      className="min-w-0 space-y-4"
      data-testid="shadow-research-candidate-workspace"
    >
      {ordered.length > 0 ? (
        <StrategyEvolutionLineage
          candidates={ordered}
          currentCandidates={current}
          historicalCandidates={historical}
          onSelectCandidate={setSelectedCandidateId}
          registryControl={registryControl}
          selectedCandidateId={selectedCandidate?.candidate_id ?? null}
          verifiedWinnerCandidateIds={verifiedWinnerCandidateIds}
        />
      ) : null}

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
