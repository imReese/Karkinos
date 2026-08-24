import { useEffect, useState } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  useApproveShadowResearchCandidateMutation,
  usePauseShadowResearchCandidateMutation,
  useRunShadowResearchMutation,
  useShadowResearchAutomationQuery,
  useStrategyPromotionStatesQuery,
  useUpdateShadowResearchPolicyMutation,
  type ShadowResearchCandidate,
  type ShadowResearchPolicyInput,
} from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import {
  CandidateCard,
  Field,
  NumberField,
  StatusMetric,
} from './shadow-research-view';

const MAX_PROVIDER_CALLS = 10;
const MAX_CANDIDATES = 5;

function isFiveRoundPolicy(policy: {
  max_provider_calls_per_market_date: number;
  daily_token_budget: number | null;
  token_budget_mode: 'unbounded_daily' | 'legacy_bounded_daily';
  max_candidates_per_run: number;
}) {
  return (
    policy.max_provider_calls_per_market_date === MAX_PROVIDER_CALLS &&
    policy.daily_token_budget === null &&
    policy.token_budget_mode === 'unbounded_daily' &&
    policy.max_candidates_per_run === MAX_CANDIDATES
  );
}

const EMPTY_POLICY: ShadowResearchPolicyInput = {
  enabled: false,
  after_close_time: '15:30',
  max_provider_calls_per_market_date: MAX_PROVIDER_CALLS,
  daily_token_budget: null,
  token_budget_mode: 'unbounded_daily',
  max_candidates_per_run: MAX_CANDIDATES,
  baseline_backtest_result_id: null,
  require_complete_account_evidence: true,
  research_question: '',
  updated_by: 'human:owner',
};

export function ShadowResearchPanel() {
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  const query = useShadowResearchAutomationQuery();
  const promotionStates = useStrategyPromotionStatesQuery();
  const updatePolicy = useUpdateShadowResearchPolicyMutation();
  const run = useRunShadowResearchMutation();
  const approve = useApproveShadowResearchCandidateMutation();
  const pause = usePauseShadowResearchCandidateMutation();
  const [policy, setPolicy] = useState<ShadowResearchPolicyInput>(EMPTY_POLICY);
  const [policyConfirmed, setPolicyConfirmed] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [approvals, setApprovals] = useState<Record<string, boolean>>({});
  const [pauseNotes, setPauseNotes] = useState<Record<string, string>>({});
  const [pauseConfirmations, setPauseConfirmations] = useState<
    Record<string, boolean>
  >({});

  useEffect(() => {
    if (!initialized && query.data?.policy) {
      const current = query.data.policy;
      setPolicy({
        enabled: current.enabled,
        after_close_time: current.after_close_time,
        max_provider_calls_per_market_date:
          current.max_provider_calls_per_market_date,
        daily_token_budget: null,
        token_budget_mode: 'unbounded_daily',
        max_candidates_per_run: current.max_candidates_per_run,
        baseline_backtest_result_id: current.baseline_backtest_result_id,
        require_complete_account_evidence:
          current.require_complete_account_evidence,
        research_question: current.research_question,
        updated_by: current.updated_by,
      });
      setInitialized(true);
    }
  }, [initialized, query.data?.policy]);

  const savePolicy = async () => {
    if (!policyConfirmed || !policy.research_question.trim()) return;
    try {
      await updatePolicy.mutateAsync(policy);
      setPolicyConfirmed(false);
      setInitialized(false);
    } catch {
      // Mutation state renders the fail-closed error.
    }
  };

  const approveCandidate = async (candidate: ShadowResearchCandidate) => {
    const note = notes[candidate.candidate_id]?.trim();
    if (!note || !approvals[candidate.candidate_id]) return;
    try {
      await approve.mutateAsync({
        candidate_id: candidate.candidate_id,
        approved_by: policy.updated_by,
        notes: note,
      });
      setApprovals((current) => ({
        ...current,
        [candidate.candidate_id]: false,
      }));
      setNotes((current) => ({
        ...current,
        [candidate.candidate_id]: '',
      }));
    } catch {
      // Mutation state renders the fail-closed error.
    }
  };

  const pauseCandidate = async (candidate: ShadowResearchCandidate) => {
    const reason = pauseNotes[candidate.candidate_id]?.trim();
    if (!reason || !pauseConfirmations[candidate.candidate_id]) return;
    try {
      await pause.mutateAsync({
        candidate_id: candidate.candidate_id,
        actor: policy.updated_by,
        reason,
      });
      setPauseConfirmations((current) => ({
        ...current,
        [candidate.candidate_id]: false,
      }));
      setPauseNotes((current) => ({
        ...current,
        [candidate.candidate_id]: '',
      }));
    } catch {
      // Mutation state renders the fail-closed error.
    }
  };

  const status = query.data;
  const draftPolicyReady = isFiveRoundPolicy(policy);
  const persistedPolicyReady = status?.policy
    ? isFiveRoundPolicy(status.policy)
    : false;
  const latestRun = status?.runs[0];
  const latestSelection = status?.daily_selections?.[0];
  const latestBackup = status?.daily_backups?.[0];
  const verifiedWinnerCandidateIds = new Set(
    (status?.daily_selections ?? [])
      .filter(
        (selection) =>
          selection.status === 'winner_selected' &&
          selection.integrity_status === 'verified' &&
          (status?.daily_backups ?? []).some(
            (backup) =>
              backup.run_id === selection.run_id &&
              backup.verification_status === 'verified',
          ),
      )
      .map((selection) => selection.winner_candidate_id)
      .filter((candidateId): candidateId is string => Boolean(candidateId)),
  );

  return (
    <section
      aria-labelledby="shadow-research-title"
      className="app-ai-research-boundary min-w-0 p-4 sm:p-5"
      data-evidence-kind="persisted-ai-shadow-research"
      data-testid="shadow-research-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-4xl">
          <div className="app-kicker">{copy.kicker}</div>
          <h2
            className="mt-2 text-lg font-semibold text-[var(--app-text)]"
            id="shadow-research-title"
          >
            {copy.title}
          </h2>
          <p className="app-muted mt-2 text-sm leading-6">{copy.detail}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded-full border border-[var(--app-divider)] px-2.5 py-1">
            {status?.policy.enabled ? copy.enabled : copy.disabled}
          </span>
          <span className="rounded-full border border-[var(--app-divider)] px-2.5 py-1">
            {copy.killSwitch}:{' '}
            {status?.kill_switch.enabled
              ? status.kill_switch.reason || 'ON'
              : copy.clear}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <StatusMetric
          label={copy.dailyWinner}
          value={
            status?.daily_new_candidate_winner_id
              ? status.daily_new_candidate_winner_id
              : copy.noWinner
          }
          detail={
            latestSelection
              ? `${latestSelection.market_date} · ${latestSelection.observed_candidate_count}/${latestSelection.expected_candidate_count}`
              : '—'
          }
        />
        <StatusMetric
          label={copy.backup}
          value={
            latestBackup?.verification_status === 'verified'
              ? copy.backupVerified
              : latestBackup?.verification_status || '—'
          }
          detail={latestBackup?.artifact_fingerprint || '—'}
        />
      </div>

      <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-3">
        <StatusMetric
          label={copy.calls}
          value={`${status?.usage.provider_calls ?? 0} / ${status?.policy.max_provider_calls_per_market_date ?? policy.max_provider_calls_per_market_date}`}
          detail={status?.usage.market_date ?? '—'}
        />
        <StatusMetric
          label={copy.tokens}
          value={String(status?.usage.actual_tokens ?? 0)}
          detail={`${status?.policy.token_budget_mode === 'unbounded_daily' ? copy.unboundedDailyTokens : copy.legacyBoundedDailyTokens} · ${copy.tokenAccountingEstimate} ${status?.usage.reserved_tokens ?? 0}`}
        />
        <StatusMetric
          label={copy.candidates}
          value={String(status?.candidates.length ?? 0)}
          detail={
            latestRun ? `${latestRun.market_date} · ${latestRun.status}` : '—'
          }
        />
      </div>
      <p className="app-muted mt-2 text-xs leading-5">
        {copy.fiveCandidateRule}
      </p>

      <div className="mt-5 grid gap-4 border-t border-[var(--app-divider)] pt-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <label className="min-w-0 text-xs font-semibold text-[var(--app-text)]">
          {copy.question}
          <textarea
            className="app-input mt-2 min-h-24 w-full resize-y"
            onChange={(event) =>
              setPolicy((current) => ({
                ...current,
                research_question: event.target.value,
              }))
            }
            value={policy.research_question}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <Field
            label={copy.operator}
            onChange={(value) =>
              setPolicy((current) => ({ ...current, updated_by: value }))
            }
            value={policy.updated_by}
          />
          <Field
            label={copy.closeTime}
            onChange={(value) =>
              setPolicy((current) => ({
                ...current,
                after_close_time: value,
              }))
            }
            type="time"
            value={policy.after_close_time}
          />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <NumberField
          label={copy.calls}
          max={MAX_PROVIDER_CALLS}
          min={2}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              max_provider_calls_per_market_date: value,
              max_candidates_per_run: Math.min(
                current.max_candidates_per_run,
                Math.max(1, Math.floor(value / 2)),
              ),
            }))
          }
          value={policy.max_provider_calls_per_market_date}
        />
        <StatusMetric
          detail={copy.providerLimitsRemain}
          label={copy.tokenPolicy}
          value={copy.unboundedDailyTokens}
        />
        <NumberField
          label={copy.candidates}
          max={Math.min(
            MAX_CANDIDATES,
            Math.max(
              1,
              Math.floor(policy.max_provider_calls_per_market_date / 2),
            ),
          )}
          min={1}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              max_candidates_per_run: value,
            }))
          }
          value={policy.max_candidates_per_run}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex min-h-11 items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
          <input
            checked={policy.enabled}
            onChange={(event) => {
              setPolicy((current) => ({
                ...current,
                enabled: event.target.checked,
              }));
              setPolicyConfirmed(false);
            }}
            type="checkbox"
          />
          {policy.enabled ? copy.enabled : copy.disabled}
        </label>
        <label className="flex min-w-0 flex-1 items-start gap-2 text-xs leading-5 text-[var(--app-muted)]">
          <input
            checked={policyConfirmed}
            className="mt-1"
            onChange={(event) => setPolicyConfirmed(event.target.checked)}
            type="checkbox"
          />
          <span>{policy.enabled ? copy.confirmEnable : copy.confirmPause}</span>
        </label>
        <button
          className="app-button-primary min-h-11 px-4 py-2 text-sm font-semibold"
          disabled={
            updatePolicy.isPending ||
            !policyConfirmed ||
            !policy.research_question.trim() ||
            (policy.enabled && !draftPolicyReady)
          }
          onClick={() => void savePolicy()}
          type="button"
        >
          {updatePolicy.isPending ? copy.saving : copy.save}
        </button>
        <button
          className="app-button-secondary min-h-11 px-4 py-2 text-sm font-semibold"
          disabled={
            run.isPending || !status?.policy.enabled || !persistedPolicyReady
          }
          onClick={() => run.mutate()}
          type="button"
        >
          {run.isPending ? copy.running : copy.run}
        </button>
      </div>
      <p className="app-muted mt-3 text-xs leading-5">{copy.noAuthority}</p>
      {policy.enabled && !draftPolicyReady && (
        <p className="mt-3 text-sm text-[var(--app-danger-text)]">
          {copy.fiveRoundPolicyBlocked}
        </p>
      )}
      {(query.isError ||
        updatePolicy.isError ||
        run.isError ||
        approve.isError ||
        pause.isError ||
        promotionStates.isError) && (
        <p className="mt-3 text-sm text-[var(--app-danger-text)]">
          {copy.failure}
        </p>
      )}

      <div className="mt-6 grid gap-4">
        {status?.candidates.length ? (
          status.candidates.map((candidate) => (
            <CandidateCard
              approvals={approvals}
              candidate={candidate}
              copy={copy}
              isDailyWinner={verifiedWinnerCandidateIds.has(
                candidate.candidate_id,
              )}
              key={candidate.candidate_id}
              notes={notes}
              onPause={() => void pauseCandidate(candidate)}
              onPauseConfirmationChange={(checked) =>
                setPauseConfirmations((current) => ({
                  ...current,
                  [candidate.candidate_id]: checked,
                }))
              }
              onPauseNoteChange={(value) =>
                setPauseNotes((current) => ({
                  ...current,
                  [candidate.candidate_id]: value,
                }))
              }
              onApprovalChange={(checked) =>
                setApprovals((current) => ({
                  ...current,
                  [candidate.candidate_id]: checked,
                }))
              }
              onApprove={() => void approveCandidate(candidate)}
              onNoteChange={(value) =>
                setNotes((current) => ({
                  ...current,
                  [candidate.candidate_id]: value,
                }))
              }
              pauseConfirmations={pauseConfirmations}
              pauseNotes={pauseNotes}
              pending={approve.isPending || pause.isPending}
              promotionStage={
                promotionStates.data?.find(
                  (state) =>
                    state.strategy_id ===
                    `ai_formula_shadow:${candidate.candidate_id}`,
                )?.stage
              }
              promotionStateLoaded={promotionStates.isSuccess}
            />
          ))
        ) : (
          <div className="rounded-[var(--app-radius-surface)] border border-dashed border-[var(--app-divider)] p-5 text-sm text-[var(--app-muted)]">
            {query.isLoading ? copy.running : copy.noCandidates}
          </div>
        )}
      </div>
    </section>
  );
}
