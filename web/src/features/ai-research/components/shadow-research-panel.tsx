import { useEffect, useState } from 'react';
import { ChevronDown } from 'lucide-react';

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
import { StrategyChampionSpotlight } from './strategy-champion-spotlight';
import { AutomaticPublicationPolicy } from './automatic-publication-policy';

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
    const recommendation =
      selection?.integrity_status === 'verified' &&
      selection.research_recommendation?.research_winner_candidate_id ===
        researchWinner
        ? selection.research_recommendation
        : undefined;
    const stress = recommendation?.ranked_candidates?.find(
      (candidate) => candidate.candidate_id === researchWinner,
    )?.cost_stress;
    const excess = stress?.worst_excess_return;
    const stressDetail =
      recommendation?.schema_version ===
      'karkinos.ai.normalized_daily_research_recommendation.v1'
        ? copy.costStressLegacy
        : recommendation?.schema_version ===
              'karkinos.ai.normalized_daily_research_recommendation.v2' &&
            stress?.status === 'complete' &&
            typeof excess === 'number' &&
            Number.isFinite(excess)
          ? `${copy.worstCostStressExcess}: ${(excess * 100).toFixed(2)}%`
          : copy.costStressUnavailable;
    return {
      value: researchWinner,
      detail: `${copy.researchNotQualified} · ${stressDetail}`,
    };
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

function ShadowResearchTelemetryHUD({
  copy,
  status,
  policy,
  providerWindow,
  locale,
}: {
  copy: (typeof SHADOW_RESEARCH_COPY)[keyof typeof SHADOW_RESEARCH_COPY];
  status: ShadowResearchAutomationStatus | undefined;
  policy: ShadowResearchPolicyInput;
  providerWindow: ShadowResearchAutomationStatus['provider_call_window'];
  locale: string;
}) {
  const zh = locale === 'zh';
  const isEnabled = status?.policy.enabled ?? false;
  const isKillSwitch = status?.kill_switch.enabled ?? false;
  const maxCalls =
    status?.policy.max_provider_calls_per_market_date ??
    policy.max_provider_calls_per_market_date;
  const actualCalls = status?.usage.provider_calls ?? 0;
  const candidateCount = status?.candidates.length ?? 0;
  const reservedTokens = status?.usage.reserved_tokens ?? 0;
  const actualTokens = status?.usage.actual_tokens ?? 0;

  const windowEligible = providerWindow?.status === 'eligible_off_peak';
  const windowLabel = windowEligible
    ? zh
      ? '避峰优惠时段'
      : 'Off-peak active'
    : zh
      ? '日间避峰锁定'
      : 'Peak lock active';

  return (
    <div
      className="app-dsh-cockpit-hud relative p-3.5 transition-all"
      data-testid="shadow-research-telemetry-hud"
    >
      <div className="app-dsh-light-strip" />
      <div className="app-dsh-ambient-glow" />

      <div className="relative z-10 flex flex-wrap items-center justify-between gap-3">
        {/* Left: Engine & Telemetry Status */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="app-dsh-pulse-beacon size-2 rounded-full bg-[var(--app-accent)] shadow-[0_0_8px_var(--app-accent)]" />
            <h2
              id="shadow-research-title"
              className="flex flex-wrap items-center gap-2 font-mono text-xs font-bold tracking-tight text-[var(--app-text)] sm:text-sm uppercase"
            >
              <span>{copy.title}</span>
              <span className="text-[var(--app-text-tertiary)] font-normal">
                /
              </span>
              <span className="inline-flex items-center gap-1.5 font-normal text-xs normal-case text-[var(--app-text-secondary)]">
                <span>
                  {zh
                    ? '现役 Gen 7: DeepSeek V4.1 Flash'
                    : 'Active Gen 7: DeepSeek V4.1 Flash'}
                </span>
                <span className="text-[var(--app-text-tertiary)]">·</span>
                <span className="text-[var(--app-accent)]">
                  {zh
                    ? '待启动: DeepSeek V4.1 Flash (Gen 8)'
                    : 'Queued: DeepSeek V4.1 Flash (Gen 8)'}
                </span>
              </span>
            </h2>
          </div>

          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono app-type-micro font-semibold ${
              isEnabled
                ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                : 'border-[var(--app-divider)] bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]'
            }`}
          >
            <span
              className={`size-1.5 rounded-full ${
                isEnabled
                  ? 'bg-[var(--app-success-text)] shadow-[0_0_6px_var(--app-success-text)]'
                  : 'bg-[var(--app-text-tertiary)]'
              }`}
            />
            {isEnabled ? copy.enabled : copy.disabled}
          </span>

          <span className="hidden items-center gap-1.5 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2.5 py-0.5 font-mono app-type-micro text-[var(--app-text-secondary)] sm:inline-flex">
            <span className="size-1 rounded-full bg-[var(--app-accent)]" />
            {windowLabel}
            <span className="text-[var(--app-text-tertiary)]">
              {zh ? '(09:00-18:00 避峰锁定)' : '(09:00-18:00 Lock)'}
            </span>
          </span>
        </div>

        {/* Right: Metrics & Kill Switch */}
        <div className="flex flex-wrap items-center gap-3 font-mono app-type-micro tabular-nums">
          <div className="flex items-center gap-3 text-[var(--app-text-secondary)]">
            <span>
              <span className="text-[var(--app-text-tertiary)]">
                {zh ? '调用: ' : 'Calls: '}
              </span>
              <strong className="font-semibold text-[var(--app-text)]">
                {actualCalls}
              </strong>
              {' / '}
              {maxCalls}
            </span>
            <span className="text-[var(--app-divider)]">/</span>
            <span>
              <span className="text-[var(--app-text-tertiary)]">
                {zh ? 'Tokens: ' : 'Tokens: '}
              </span>
              <strong className="font-semibold text-[var(--app-text)]">
                {actualTokens > 0
                  ? actualTokens.toLocaleString()
                  : `Est. ${reservedTokens.toLocaleString()}`}
              </strong>
            </span>
            <span className="text-[var(--app-divider)]">/</span>
            <span>
              <span className="text-[var(--app-text-tertiary)]">
                {zh ? '策略库: ' : 'Pool: '}
              </span>
              <strong className="font-semibold text-[var(--app-text)]">
                {candidateCount}
              </strong>
            </span>
          </div>

          <span
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 app-type-micro font-semibold ${
              isKillSwitch
                ? 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger-text)]'
                : 'border-[var(--app-divider)] bg-[var(--app-surface)] text-[var(--app-text-tertiary)]'
            }`}
          >
            <span
              className={`size-1.5 rounded-full ${
                isKillSwitch
                  ? 'bg-[var(--app-danger-text)] shadow-[0_0_6px_var(--app-danger-text)]'
                  : 'bg-[var(--app-text-tertiary)]'
              }`}
            />
            {copy.killSwitch}:{' '}
            {isKillSwitch ? status?.kill_switch.reason || 'ON' : copy.clear}
          </span>
        </div>
      </div>
    </div>
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
    <div
      className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-5"
      data-testid="shadow-research-usage-metrics"
    >
      <StatusMetric
        label={copy.calls}
        value={`${status?.usage.provider_calls ?? 0} / ${
          status?.policy.max_provider_calls_per_market_date ??
          policy.max_provider_calls_per_market_date
        }`}
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
        detail={`${
          status?.policy.token_budget_mode === 'unbounded_daily'
            ? copy.unboundedDailyTokens
            : copy.legacyBoundedDailyTokens
        } · ${copy.tokenAccountingEstimate} ${status?.usage.reserved_tokens ?? 0}`}
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
        ...(current.simulation_validation
          ? { simulation_validation: current.simulation_validation }
          : {}),
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
        (key) =>
          JSON.stringify(policy[key] ?? null) !==
          JSON.stringify(status.policy[key] ?? null),
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
        className="min-w-0 py-8"
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
      className="min-w-0 space-y-4"
      data-evidence-kind="persisted-ai-shadow-research"
      data-testid="shadow-research-panel"
    >
      <ShadowResearchTelemetryHUD
        copy={copy}
        status={status}
        policy={policy}
        providerWindow={providerWindow}
        locale={locale}
      />

      <div className="min-w-0 space-y-8">
        {/* Primary Research & Lineage Review (Full Width) */}
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

        {/* Governance, Qualification & Automation Rail (Full Width Sequential Flow) */}
        <div className="min-w-0 space-y-6">
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

          <div className="grid min-w-0 gap-6 lg:grid-cols-2">
            <StrategyChampionSpotlight status={status} />
            <AutomaticPublicationPolicy updatedBy={policy.updated_by} />
          </div>

          {/* Automation diagnostics and policy configuration */}
          <details
            className="group rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-4"
            data-testid="research-automation-disclosure"
          >
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)] transition-colors">
              <span>
                {locale === 'zh'
                  ? '自动化研究运行诊断与策略配置'
                  : 'Automation Diagnostics & Policy Configuration'}
              </span>
              <ChevronDown
                aria-hidden="true"
                className="size-4 shrink-0 transition-transform group-open:rotate-180"
              />
            </summary>

            <div className="mt-4 space-y-6">
              <ShadowResearchUsageMetrics
                copy={copy}
                status={status}
                policy={policy}
                providerWindow={providerWindow}
              />

              <div className="grid gap-3 sm:grid-cols-2">
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

              <p className="sr-only">{copy.fiveCandidateRule}</p>

              <div className="mt-4">
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
              </div>
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
            </div>
          </details>
        </div>
      </div>
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
