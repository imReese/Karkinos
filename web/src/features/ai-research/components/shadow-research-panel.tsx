import { useEffect, useState } from 'react';

import { usePreferences } from '../../../app/preferences';
import { formatCurrency, formatPercent } from '../../../shared/format';
import {
  useApproveShadowResearchCandidateMutation,
  usePauseShadowResearchCandidateMutation,
  useRunShadowResearchMutation,
  useShadowResearchAutomationQuery,
  useStrategyPromotionStatesQuery,
  useUpdateShadowResearchPolicyMutation,
  type ShadowResearchCandidate,
  type ShadowResearchMetricView,
  type ShadowResearchPolicyInput,
} from '../api';

const COPY = {
  en: {
    kicker: 'After-close DeepSeek research',
    title: 'Automated shadow strategy research',
    detail:
      'After the persisted market close, Karkinos refreshes the baseline locally and sends DeepSeek the saved backtest plus a sanitized account risk/allocation projection. Absolute account values and valuation/ledger identifiers stay redacted. Formula validation, after-cost backtest and rolling OOS remain local before the evidence critique.',
    disabled: 'Paused',
    enabled: 'Authorized',
    killSwitch: 'Kill switch',
    clear: 'Clear',
    calls: 'Provider calls',
    tokens: 'Token budget',
    candidates: 'Research candidates',
    closeTime: 'After-close time',
    question: 'Standing research question',
    operator: 'Owner identity',
    save: 'Save standing policy',
    saving: 'Saving…',
    confirmEnable:
      'I authorize the displayed recurring saved-backtest and sanitized account risk/allocation payload within this budget. It has no strategy replacement or trading authority.',
    confirmPause: 'I confirm pausing recurring AI strategy research.',
    run: 'Check and run now',
    running: 'Checking evidence…',
    noCandidates:
      'No completed automated candidate is in the research pool yet.',
    baseline: 'Current baseline',
    candidate: 'New candidate',
    return: 'Total return',
    sharpe: 'Sharpe',
    drawdown: 'Max drawdown',
    costs: 'Total cost',
    oos: 'Mean / worst OOS',
    trades: 'Trades',
    risk: 'Risk impact',
    blockers: 'Promotion blockers',
    critique: 'DeepSeek evidence critique',
    approve: 'Approve for paper/shadow only',
    reapprove: 'Re-review for paper/shadow',
    approving: 'Recording approval…',
    approvalNote: 'Human review note',
    approvalConfirm:
      'I reviewed the baseline comparison, costs, rolling OOS, risks and critique. Approve this candidate for paper/shadow research only.',
    approved: 'Paper/shadow approved',
    paused: 'Paper/shadow paused / revoked',
    pause: 'Pause / revoke paper-shadow',
    pausing: 'Recording pause…',
    pauseNote: 'Pause / revocation reason',
    pauseConfirm:
      'I confirm pausing this exact candidate. Existing approval remains auditable, but new tickets must fail closed until a new explicit review.',
    noAuthority: 'No production replacement · no broker order',
    failure: 'The operation failed closed. No strategy or order was changed.',
  },
  zh: {
    kicker: 'DeepSeek 收盘后研究',
    title: '自动 shadow 策略研究池',
    detail:
      '持久化行情收盘后，Karkinos 在本地刷新基线，只向 DeepSeek 发送保存的回测证据与脱敏账户风险/配置投影；绝对账户金额及 valuation/ledger 标识不外发。Formula 校验、权威成本后回测和 rolling OOS 均留在本地，之后再发送证据做 critique。',
    disabled: '已暂停',
    enabled: '已授权',
    killSwitch: 'Kill Switch',
    clear: '未触发',
    calls: '模型调用',
    tokens: 'Token 预算',
    candidates: '研究候选',
    closeTime: '收盘后时间',
    question: '长期研究问题',
    operator: '所有者身份',
    save: '保存站立授权',
    saving: '保存中…',
    confirmEnable:
      '我授权按页面所示范围与预算周期性发送保存的回测证据及脱敏账户风险/配置 payload；该授权不包含策略替换权或交易权。',
    confirmPause: '我确认暂停周期性 AI 策略研究。',
    run: '立即检查并运行',
    running: '正在检查证据…',
    noCandidates: '研究池里还没有完成的自动候选。',
    baseline: '当前基线',
    candidate: '新候选',
    return: '总收益',
    sharpe: '夏普',
    drawdown: '最大回撤',
    costs: '总成本',
    oos: 'OOS 均值 / 最差',
    trades: '成交数',
    risk: '风险影响',
    blockers: '晋级阻断项',
    critique: 'DeepSeek 证据批判',
    approve: '仅批准进入 paper/shadow',
    reapprove: '重新复核进入 paper/shadow',
    approving: '正在记录批准…',
    approvalNote: '人工复核备注',
    approvalConfirm:
      '我已复核基线对比、成本、rolling OOS、风险与 critique；仅批准该候选进入 paper/shadow 研究。',
    approved: '已批准 paper/shadow',
    paused: 'paper/shadow 已暂停 / 撤销',
    pause: '暂停 / 撤销 paper-shadow',
    pausing: '正在记录暂停…',
    pauseNote: '暂停 / 撤销原因',
    pauseConfirm:
      '我确认暂停这一精确候选；原批准保留供审计，但重新明确复核前，新票据必须 fail closed。',
    noAuthority: '不会替换生产策略 · 不会创建 broker 订单',
    failure: '操作已 fail closed；没有修改策略或订单。',
  },
} as const;

const PROVIDER_TOKEN_RESERVATION = 225_280;

const EMPTY_POLICY: ShadowResearchPolicyInput = {
  enabled: false,
  after_close_time: '15:30',
  max_provider_calls_per_market_date: 3,
  daily_token_budget: 700_000,
  max_candidates_per_run: 2,
  baseline_backtest_result_id: null,
  require_complete_account_evidence: true,
  research_question: '',
  updated_by: 'human:owner',
};

export function ShadowResearchPanel() {
  const { locale } = usePreferences();
  const copy = COPY[locale];
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
        daily_token_budget: current.daily_token_budget,
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
  const latestRun = status?.runs[0];

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

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <StatusMetric
          label={copy.calls}
          value={`${status?.usage.provider_calls ?? 0} / ${status?.policy.max_provider_calls_per_market_date ?? policy.max_provider_calls_per_market_date}`}
          detail={status?.usage.market_date ?? '—'}
        />
        <StatusMetric
          label={copy.tokens}
          value={`${status?.usage.actual_tokens ?? 0} / ${status?.policy.daily_token_budget ?? policy.daily_token_budget}`}
          detail={`reserved ${status?.usage.reserved_tokens ?? 0}`}
        />
        <StatusMetric
          label={copy.candidates}
          value={String(status?.candidates.length ?? 0)}
          detail={
            latestRun ? `${latestRun.market_date} · ${latestRun.status}` : '—'
          }
        />
      </div>

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
          max={4}
          min={2}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              max_provider_calls_per_market_date: value,
              max_candidates_per_run: Math.min(
                current.max_candidates_per_run,
                Math.max(1, value - 1),
              ),
            }))
          }
          value={policy.max_provider_calls_per_market_date}
        />
        <NumberField
          label={copy.tokens}
          max={1_000_000}
          min={PROVIDER_TOKEN_RESERVATION * (policy.max_candidates_per_run + 1)}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              daily_token_budget: value,
            }))
          }
          step={1_000}
          value={policy.daily_token_budget}
        />
        <NumberField
          label={copy.candidates}
          max={Math.max(1, policy.max_provider_calls_per_market_date - 1)}
          min={1}
          onChange={(value) =>
            setPolicy((current) => ({
              ...current,
              max_candidates_per_run: value,
              daily_token_budget: Math.max(
                current.daily_token_budget,
                PROVIDER_TOKEN_RESERVATION * (value + 1),
              ),
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
            !policy.research_question.trim()
          }
          onClick={() => void savePolicy()}
          type="button"
        >
          {updatePolicy.isPending ? copy.saving : copy.save}
        </button>
        <button
          className="app-button-secondary min-h-11 px-4 py-2 text-sm font-semibold"
          disabled={run.isPending || !status?.policy.enabled}
          onClick={() => run.mutate()}
          type="button"
        >
          {run.isPending ? copy.running : copy.run}
        </button>
      </div>
      <p className="app-muted mt-3 text-xs leading-5">{copy.noAuthority}</p>
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

function CandidateCard({
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
  pending,
}: {
  candidate: ShadowResearchCandidate;
  copy: (typeof COPY)[keyof typeof COPY];
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
  pending: boolean;
}) {
  const comparison = candidate.comparison;
  const eligible =
    candidate.status === 'awaiting_human_approval' &&
    candidate.recommendation === 'paper_shadow_review' &&
    comparison.promotion_gate.status === 'pass' &&
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

function MetricComparison({
  label,
  metrics,
}: {
  label: string;
  metrics: ShadowResearchMetricView;
}) {
  const { locale } = usePreferences();
  const copy = COPY[locale];
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[var(--app-muted)]">{label}</dt>
      <dd className="mt-1 font-semibold text-[var(--app-text)]">{value}</dd>
    </div>
  );
}

function EvidenceList({ items, title }: { items: string[]; title: string }) {
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

function StatusMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] p-3">
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

function Field({
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

function NumberField({
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
