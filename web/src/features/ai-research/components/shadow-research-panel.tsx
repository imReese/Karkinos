import { useEffect, useState } from 'react';

import { formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { EvidenceState } from '../../../shared/ui/workbench';
import {
  useApproveShadowResearchQualificationCandidateMutation,
  useApproveShadowResearchCandidateMutation,
  usePauseShadowResearchCandidateMutation,
  useRunShadowResearchMutation,
  useShadowResearchAutomationQuery,
  useStrategyPromotionStatesQuery,
  useUpdateShadowResearchPolicyMutation,
  type ShadowResearchAutomationStatus,
  type ShadowResearchCandidate,
  type ShadowResearchPolicyInput,
} from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';
import { ShadowResearchCandidateWorkspace } from './shadow-research-candidate-workspace';
import { ShadowResearchQualificationReview } from './shadow-research-qualification';
import {
  MAX_PROVIDER_CALLS,
  MAX_CANDIDATES,
  ShadowResearchPolicyCard,
  hasValidResearchDates,
} from './shadow-research-policy-card';
import { StatusMetric } from './shadow-research-view';

function isFiveRoundPolicy(policy: {
  max_provider_calls_per_market_date: number;
  daily_token_budget: number | null;
  token_budget_mode: 'unbounded_daily' | 'legacy_bounded_daily';
  max_candidates_per_run: number;
  research_capital_mode: 'normalized_notional' | 'account_bound';
  require_complete_account_evidence: boolean;
}) {
  return (
    policy.max_provider_calls_per_market_date === MAX_PROVIDER_CALLS &&
    policy.daily_token_budget === null &&
    policy.token_budget_mode === 'unbounded_daily' &&
    policy.max_candidates_per_run === MAX_CANDIDATES &&
    policy.research_capital_mode === 'normalized_notional' &&
    policy.require_complete_account_evidence === false
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
  research_end_date: null,
  sealed_end_date: null,
  research_capital_mode: 'normalized_notional',
  require_complete_account_evidence: false,
  research_question: '',
  updated_by: 'human:owner',
};

function dailyResearchOutcome(
  status: ShadowResearchAutomationStatus | undefined,
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY],
) {
  const selection = status?.daily_selections?.[0];
  const researchWinner = status?.daily_research_winner_candidate_id ?? null;
  const promotionWinner = status?.daily_winner_candidate_id ?? null;
  if (researchWinner) {
    return { value: researchWinner, detail: copy.researchNotQualified };
  }
  if (promotionWinner) {
    return { value: promotionWinner, detail: copy.winnerBadge };
  }
  return {
    value: copy.noWinner,
    detail: selection
      ? `${selection.market_date} · ${selection.observed_candidate_count}/${selection.expected_candidate_count}`
      : '—',
  };
}

function verifiedDailyCandidateIds(
  status: ShadowResearchAutomationStatus | undefined,
) {
  const selections = status?.daily_selections ?? [];
  const backups = status?.daily_backups ?? [];
  const hasVerifiedBackup = (runId: string) =>
    backups.some(
      (backup) =>
        backup.run_id === runId && backup.verification_status === 'verified',
    );
  return {
    promotion: new Set(
      selections
        .filter(
          (selection) =>
            selection.status === 'winner_selected' &&
            selection.integrity_status === 'verified' &&
            hasVerifiedBackup(selection.run_id),
        )
        .map((selection) => selection.winner_candidate_id)
        .filter((candidateId): candidateId is string => Boolean(candidateId)),
    ),
    research: new Set(
      selections
        .filter(
          (selection) =>
            selection.integrity_status === 'verified' &&
            selection.research_recommendation?.status ===
              'best_available_for_further_research' &&
            selection.research_recommendation.account_qualified === false &&
            hasVerifiedBackup(selection.run_id),
        )
        .map(
          (selection) =>
            selection.research_recommendation?.research_winner_candidate_id,
        )
        .filter((candidateId): candidateId is string => Boolean(candidateId)),
    ),
  };
}

function TodayProviderActivityMetric({
  copy,
  activity,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  activity: ShadowResearchAutomationStatus['today_provider_activity'];
}) {
  return (
    <StatusMetric
      label={copy.todayCalls}
      value={activity ? String(activity.provider_calls) : '—'}
      detail={
        activity?.last_provider_call_at
          ? `${copy.lastProviderCall}: ${formatTimestamp(
              activity.last_provider_call_at,
            )} · ${copy.researchMarketDate}: ${activity.last_provider_call_market_date ?? '—'}`
          : `${activity?.local_date ?? '—'} · ${copy.noCallsToday}`
      }
    />
  );
}

function ShadowResearchUsageMetrics({
  copy,
  status,
  policy,
  providerWindow,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  status: ShadowResearchAutomationStatus | undefined;
  policy: ShadowResearchPolicyInput;
  providerWindow: ShadowResearchAutomationStatus['provider_call_window'];
}) {
  const latestRun = status?.runs[0];
  return (
    <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <StatusMetric
        label={copy.calls}
        value={`${status?.usage.provider_calls ?? 0} / ${status?.policy.max_provider_calls_per_market_date ?? policy.max_provider_calls_per_market_date}`}
        detail={status?.usage.market_date ?? '—'}
      />
      <TodayProviderActivityMetric
        copy={copy}
        activity={status?.today_provider_activity}
      />
      <ProviderCallWindowMetric copy={copy} providerWindow={providerWindow} />
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
  );
}

export function ShadowResearchPanel() {
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  const query = useShadowResearchAutomationQuery();
  const promotionStates = useStrategyPromotionStatesQuery();
  const updatePolicy = useUpdateShadowResearchPolicyMutation();
  const run = useRunShadowResearchMutation();
  const approve = useApproveShadowResearchCandidateMutation();
  const approveQualification =
    useApproveShadowResearchQualificationCandidateMutation();
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
        research_end_date: current.research_end_date ?? null,
        sealed_end_date: current.sealed_end_date ?? null,
        research_capital_mode: 'normalized_notional',
        require_complete_account_evidence: false,
        research_question: current.research_question,
        updated_by: current.updated_by,
      });
      setInitialized(true);
    }
  }, [initialized, query.data?.policy]);

  const datesValid = hasValidResearchDates(policy);

  const savePolicy = async () => {
    if (!policyConfirmed || !policy.research_question.trim() || !datesValid)
      return;
    run.reset();
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
  const policyDirty = status
    ? (Object.keys(policy) as Array<keyof ShadowResearchPolicyInput>).some(
        (key) => (policy[key] ?? null) !== (status.policy[key] ?? null),
      )
    : false;
  const draftPolicyReady = isFiveRoundPolicy(policy);
  const persistedPolicyReady = status?.policy
    ? isFiveRoundPolicy(status.policy)
    : false;
  const providerWindow = status?.provider_call_window;
  const providerWindowEligible =
    providerWindow?.status !== 'deferred_for_provider_off_peak';
  const latestBackup = status?.daily_backups?.[0];
  const dailyOutcome = dailyResearchOutcome(status, copy);
  const verifiedCandidateIds = verifiedDailyCandidateIds(status);

  if (!status || query.isError) {
    return (
      <section
        aria-labelledby="shadow-research-title"
        className="app-ai-research-boundary min-w-0 p-4 sm:p-5"
        data-evidence-kind="persisted-ai-shadow-research"
        data-testid="shadow-research-panel"
      >
        <h2
          id="shadow-research-title"
          className="app-type-section-title text-[var(--app-text)]"
        >
          {copy.title}
        </h2>
        <EvidenceState
          className="mt-4"
          kind={query.isError ? 'error' : 'loading'}
          title={query.isError ? copy.loadFailed : copy.loading}
          action={
            query.isError ? (
              <button
                className="app-button-secondary min-h-11 px-3 py-2 text-xs font-semibold"
                disabled={query.isFetching}
                onClick={() => void query.refetch()}
                type="button"
              >
                {query.isFetching ? copy.loading : copy.retry}
              </button>
            ) : undefined
          }
        />
      </section>
    );
  }

  return (
    <section
      aria-labelledby="shadow-research-title"
      className="app-ai-research-boundary min-w-0 p-4 sm:p-5"
      data-evidence-kind="persisted-ai-shadow-research"
      data-testid="shadow-research-panel"
    >
      <ShadowResearchHeader copy={copy} status={status} />

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <StatusMetric
          label={copy.dailyWinner}
          value={dailyOutcome.value}
          detail={dailyOutcome.detail}
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

      <ShadowResearchUsageMetrics
        copy={copy}
        status={status}
        policy={policy}
        providerWindow={providerWindow}
      />
      <p className="sr-only">{copy.fiveCandidateRule}</p>

      <ShadowResearchPolicyCard
        copy={copy}
        datesValid={datesValid}
        draftPolicyReady={draftPolicyReady}
        locale={locale}
        onRun={() => run.mutate()}
        onSavePolicy={() => void savePolicy()}
        persistedPolicyReady={persistedPolicyReady}
        policy={policy}
        policyConfirmed={policyConfirmed}
        policyDirty={policyDirty}
        providerWindowEligible={providerWindowEligible}
        runPending={run.isPending}
        runReceipt={run.isPending ? undefined : run.data}
        setPolicy={(update) => {
          run.reset();
          setPolicy(update);
          setPolicyConfirmed(false);
        }}
        setPolicyConfirmed={setPolicyConfirmed}
        status={status}
        updatePolicyPending={updatePolicy.isPending}
      />
      {updatePolicy.isSuccess && !policyDirty ? (
        <p
          role="status"
          className="mt-3 text-sm text-[var(--app-success-text)]"
        >
          {copy.policySaved}
        </p>
      ) : null}
      {(query.isError ||
        updatePolicy.isError ||
        run.isError ||
        approve.isError ||
        approveQualification.isError ||
        pause.isError ||
        promotionStates.isError) && (
        <p className="mt-3 text-sm text-[var(--app-danger-text)]">
          {copy.failure}
        </p>
      )}

      <ShadowResearchQualificationReview
        approvedBy={policy.updated_by}
        copy={copy}
        locale={locale}
        onApprove={async (
          qualificationCandidateId,
          approvalNotes,
          forwardReview,
        ) => {
          await approveQualification.mutateAsync({
            qualification_candidate_id: qualificationCandidateId,
            approved_by: policy.updated_by,
            notes: approvalNotes,
            ...(forwardReview ? { forward_review: forwardReview } : {}),
          });
        }}
        pending={approveQualification.isPending}
        status={status}
      />

      <ShadowResearchCandidateWorkspace
        approvals={approvals}
        candidates={status?.candidates ?? []}
        copy={copy}
        loading={query.isLoading}
        latestRunId={status?.runs[0]?.run_id ?? null}
        notes={notes}
        onApprovalChange={setApprovals}
        onApprove={approveCandidate}
        onNoteChange={setNotes}
        onPause={pauseCandidate}
        onPauseConfirmationChange={setPauseConfirmations}
        onPauseNoteChange={setPauseNotes}
        pauseConfirmations={pauseConfirmations}
        pauseNotes={pauseNotes}
        pending={approve.isPending || pause.isPending}
        promotionStates={promotionStates}
        verifiedResearchWinnerCandidateIds={verifiedCandidateIds.research}
        verifiedWinnerCandidateIds={verifiedCandidateIds.promotion}
      />
    </section>
  );
}

function ProviderCallWindowMetric({
  copy,
  providerWindow,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  providerWindow: ShadowResearchAutomationStatus['provider_call_window'];
}) {
  return (
    <StatusMetric
      label={copy.providerWindow}
      value={
        providerWindow?.status === 'eligible_off_peak'
          ? copy.offPeakEligible
          : providerWindow
            ? copy.offPeakDeferred
            : '—'
      }
      detail={
        providerWindow?.next_eligible_at
          ? `${copy.nextEligible}: ${providerWindow.next_eligible_at}`
          : copy.offPeakSchedule
      }
    />
  );
}

function ShadowResearchHeader({
  copy,
  status,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  status: ReturnType<typeof useShadowResearchAutomationQuery>['data'];
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--app-divider)] pb-4">
      <div className="min-w-0 max-w-4xl">
        <div className="app-kicker">{copy.kicker}</div>
        <h2
          className="mt-1.5 text-base font-semibold text-[var(--app-text)] sm:text-lg"
          id="shadow-research-title"
        >
          {copy.title}
        </h2>
        <p className="sr-only">{copy.detail}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
        <span
          className={`rounded-full border px-2.5 py-1 ${
            status?.policy.enabled
              ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
              : 'border-[var(--app-divider)] text-[var(--app-text-secondary)]'
          }`}
        >
          {status?.policy.enabled ? copy.enabled : copy.disabled}
        </span>
        <span className="rounded-full border border-[var(--app-divider)] px-2.5 py-1 text-[var(--app-text-secondary)]">
          {copy.killSwitch}:{' '}
          {status?.kill_switch.enabled
            ? status.kill_switch.reason || 'ON'
            : copy.clear}
        </span>
      </div>
    </div>
  );
}
