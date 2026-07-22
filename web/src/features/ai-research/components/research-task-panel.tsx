import { useState, type FormEvent } from 'react';

import { useCopy } from '../../../app/copy';
import { EvidenceIdentityDisclosure } from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import {
  useCreateHumanResearchTaskMutation,
  useResearchTaskAnalysisReviewsQuery,
  useResearchTaskFixtureAnalysesQuery,
  useResearchTasksQuery,
  useReviewFixtureAnalysisMutation,
  useReviewResearchTaskMutation,
  useStartFixtureAnalysisMutation,
  type AnalysisReviewDecision,
  type HumanResearchTask,
  type ResearchEvidenceType,
  type ResearchTaskAnalysisReview,
  type ResearchTaskFixtureAnalysis,
} from '../api';

const BASE_EVIDENCE: ResearchEvidenceType[] = [
  'portfolio',
  'account_state',
  'operations',
  'account_truth',
];

let auditKeySequence = 0;

function newAuditKey(prefix: string) {
  auditKeySequence += 1;
  const random = globalThis.crypto?.randomUUID?.();
  return `${prefix}:${random ?? `${Date.now()}-${auditKeySequence}`}`;
}

const COPY = {
  en: {
    kicker: 'AI research boundary',
    title: 'Human research tasks',
    detail:
      'Freeze canonical evidence, review the context, then explicitly run an offline deterministic fixture. External models remain off.',
    closedDetail:
      'This boundary is idle until you open it. It never polls a model or provider.',
    open: 'Open research tasks',
    close: 'Close',
    noModel: 'External models off',
    noAuthority: 'No trading authority',
    operator: 'Human operator',
    account: 'Account alias',
    taskTitle: 'Task title',
    question: 'Research question',
    includeBacktest: 'Bind saved backtest evidence',
    includeContribution: 'Bind current strategy outcome evidence',
    noContribution:
      'No exact current strategy is available for contribution capture.',
    noBacktest:
      'Run and save a backtest first to bind exact research evidence.',
    submit: 'Capture evidence and record task',
    submitting: 'Recording…',
    success: 'The task was recorded without starting model execution.',
    loading: 'Loading persisted research tasks…',
    loadError: 'Persisted research tasks could not be loaded.',
    empty: 'No human research task has been recorded yet.',
    evidence: 'Evidence',
    authoritative: 'Authoritative',
    blocked: 'Blocked',
    snapshot: 'Valuation snapshot',
    cutoff: 'Ledger cutoff',
    reviewNote: 'Human review note',
    accept: 'Accept context',
    revise: 'Request revision',
    closeWithout: 'Close without analysis',
    reviewing: 'Recording review…',
    acceptBlocked: 'Acceptance requires complete authoritative evidence.',
    persistedOnly: 'Persisted facts only',
    analysisLoading: 'Loading persisted fixture analyses…',
    analysisLoadError: 'Fixture analysis records could not be loaded.',
    runFixture: 'Run offline fixture analysis',
    runningFixture: 'Running local fixture…',
    fixtureOnly: 'Deterministic fixture only',
    noNetwork: 'No network or external model',
    analysisStatus: 'Fixture workflow',
    bindingStatus: 'Evidence binding',
    memoryStatus: 'Memory draft',
    auditValid: 'Audit replay valid',
    auditInvalid: 'Audit replay blocked',
    bindingValid: 'Exact context valid',
    bindingDrift: 'Evidence drift — output invalidated',
    memoryPending: 'Human review required; exact context only',
    memoryInvalid: 'Invalidated by evidence drift',
    report: 'Fixture report',
    artifacts: 'Artifacts',
    analysisReview: 'Human analysis review',
    analysisReviewBoundary:
      'This decision only controls research-memory recall. It cannot enter Decision or grant trading authority.',
    reviewer: 'Reviewer',
    analysisReviewNote: 'Analysis review note',
    acceptMemory: 'Accept as reviewed memory',
    requestAnalysisRevision: 'Request analysis revision',
    rejectAnalysis: 'Reject fixture output',
    recordingAnalysisReview: 'Recording analysis review…',
    analysisReviewLoadError: 'Analysis review could not be loaded.',
    analysisReviewRequired: 'A reviewer and note are required.',
    acceptAnalysisBlocked:
      'Acceptance requires a completed, exact, replay-valid analysis and memory artifact.',
    memoryRecallEligible: 'Eligible for reviewed research recall',
    memoryRecallIneligible: 'Not eligible for research recall',
    analysisReviewStatuses: {
      reviewed_memory: 'Reviewed memory',
      revision_requested: 'Revision requested',
      rejected: 'Rejected',
      invalidated_by_evidence_drift: 'Invalidated by evidence drift',
    },
    statuses: {
      awaiting_human_review: 'Awaiting human review',
      blocked_by_evidence: 'Blocked by evidence',
      context_accepted: 'Context accepted',
      context_revision_requested: 'Revision requested',
      closed_without_analysis: 'Closed without analysis',
    },
  },
  zh: {
    kicker: 'AI 投研边界',
    title: '人工研究任务',
    detail:
      '先冻结 canonical 证据并人工复核，再由人显式运行离线 deterministic fixture；外部模型继续关闭。',
    closedDetail: '显式打开前保持空闲；不会轮询模型或 provider。',
    open: '打开研究任务',
    close: '收起',
    noModel: '外部模型关闭',
    noAuthority: '无交易权限',
    operator: '人工操作人',
    account: '账户别名',
    taskTitle: '任务标题',
    question: '研究问题',
    includeBacktest: '绑定已保存回测证据',
    includeContribution: '绑定当前策略结果证据',
    noContribution: '当前没有可供精确选择的策略贡献证据。',
    noBacktest: '请先运行并保存回测，才能绑定精确 research evidence。',
    submit: '冻结证据并记录任务',
    submitting: '记录中…',
    success: '任务已记录，未启动任何模型执行。',
    loading: '正在读取持久化研究任务…',
    loadError: '无法读取持久化研究任务。',
    empty: '尚未记录人工研究任务。',
    evidence: '证据',
    authoritative: '权威完整',
    blocked: '阻断',
    snapshot: '估值快照',
    cutoff: '账本截止',
    reviewNote: '人工复核备注',
    accept: '接受上下文',
    revise: '要求修订',
    closeWithout: '不分析并关闭',
    reviewing: '正在记录复核…',
    acceptBlocked: '只有完整、权威的证据上下文才可接受。',
    persistedOnly: '仅持久化事实',
    analysisLoading: '正在读取持久化 fixture analysis…',
    analysisLoadError: '无法读取 fixture analysis 记录。',
    runFixture: '运行离线 fixture analysis',
    runningFixture: '本地 fixture 运行中…',
    fixtureOnly: '仅 deterministic fixture',
    noNetwork: '无网络、无外部模型',
    analysisStatus: 'Fixture workflow',
    bindingStatus: '证据绑定',
    memoryStatus: '记忆草稿',
    auditValid: '审计回放有效',
    auditInvalid: '审计回放阻断',
    bindingValid: '精确上下文有效',
    bindingDrift: '证据漂移——产物已失效',
    memoryPending: '等待人工复核；仅对精确上下文有效',
    memoryInvalid: '已因证据漂移失效',
    report: 'Fixture 报告',
    artifacts: '产物',
    analysisReview: '人工分析复核',
    analysisReviewBoundary:
      '该决定只控制研究记忆的回忆资格，不能进入 Decision，也不授予任何交易权限。',
    reviewer: '复核人',
    analysisReviewNote: '分析复核备注',
    acceptMemory: '接受为已复核研究记忆',
    requestAnalysisRevision: '要求修订分析',
    rejectAnalysis: '驳回 fixture 产物',
    recordingAnalysisReview: '正在记录分析复核…',
    analysisReviewLoadError: '无法读取分析复核记录。',
    analysisReviewRequired: '必须填写复核人和备注。',
    acceptAnalysisBlocked:
      '只有已完成、精确绑定、回放有效且包含 memory 的分析才能接受。',
    memoryRecallEligible: '可用于已复核研究回忆',
    memoryRecallIneligible: '不可用于研究回忆',
    analysisReviewStatuses: {
      reviewed_memory: '已复核研究记忆',
      revision_requested: '已要求修订',
      rejected: '已驳回',
      invalidated_by_evidence_drift: '已因证据漂移失效',
    },
    statuses: {
      awaiting_human_review: '等待人工复核',
      blocked_by_evidence: '证据阻断',
      context_accepted: '上下文已接受',
      context_revision_requested: '已要求修订',
      closed_without_analysis: '已关闭且未分析',
    },
  },
} as const;

export function ResearchTaskPanel({
  backtestResultId,
  strategyId,
}: {
  backtestResultId: number | null;
  strategyId: string | null;
}) {
  const { locale } = usePreferences();
  const copy = COPY[locale];
  const [open, setOpen] = useState(false);
  const tasks = useResearchTasksQuery(open);
  const analyses = useResearchTaskFixtureAnalysesQuery(open);
  const createTask = useCreateHumanResearchTaskMutation();
  const reviewTask = useReviewResearchTaskMutation();
  const startFixture = useStartFixtureAnalysisMutation();
  const [operator, setOperator] = useState('human:owner');
  const [accountAlias, setAccountAlias] = useState('primary');
  const [title, setTitle] = useState('Review frozen investment evidence');
  const [question, setQuestion] = useState('');
  const [includeBacktest, setIncludeBacktest] = useState(false);
  const [includeContribution, setIncludeContribution] = useState(false);
  const [reviewNote, setReviewNote] = useState('');
  const [captureKey, setCaptureKey] = useState(() =>
    newAuditKey('ai-context-capture'),
  );
  const [taskKey, setTaskKey] = useState(() => newAuditKey('ai-research-task'));
  const [reviewKeys, setReviewKeys] = useState<Record<string, string>>({});
  const [analysisKeys, setAnalysisKeys] = useState<Record<string, string>>({});
  const [successMessage, setSuccessMessage] = useState('');

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSuccessMessage('');
    const evidenceTypes = [...BASE_EVIDENCE];
    if (includeBacktest && backtestResultId !== null) {
      evidenceTypes.push('research_evidence');
    }
    if (includeContribution && strategyId !== null) {
      evidenceTypes.push('strategy_contribution');
    }
    try {
      await createTask.mutateAsync({
        capture_idempotency_key: captureKey,
        task_idempotency_key: taskKey,
        operator: operator.trim(),
        account_alias: accountAlias.trim(),
        title: title.trim(),
        research_question: question.trim(),
        evidence_types: evidenceTypes,
        backtest_result_id: backtestResultId,
        strategy_id: strategyId,
      });
      setCaptureKey(newAuditKey('ai-context-capture'));
      setTaskKey(newAuditKey('ai-research-task'));
      setSuccessMessage(copy.success);
    } catch {
      // Mutation state renders the fail-closed response while keys remain stable.
    }
  };

  const review = async (
    task: HumanResearchTask,
    decision:
      | 'context_accepted'
      | 'context_revision_requested'
      | 'closed_without_analysis',
  ) => {
    const keyName = `${task.task_id}:${decision}`;
    const idempotencyKey =
      reviewKeys[keyName] ?? newAuditKey('ai-research-review');
    if (!reviewKeys[keyName]) {
      setReviewKeys((current) => ({
        ...current,
        [keyName]: idempotencyKey,
      }));
    }
    try {
      await reviewTask.mutateAsync({
        task_id: task.task_id,
        idempotency_key: idempotencyKey,
        reviewed_by: operator.trim(),
        decision,
        note: reviewNote.trim(),
      });
    } catch {
      // Mutation state renders the error while the idempotency key is retained.
    }
  };

  const startAnalysis = async (task: HumanResearchTask) => {
    const idempotencyKey =
      analysisKeys[task.task_id] ?? newAuditKey('ai-fixture-analysis');
    if (!analysisKeys[task.task_id]) {
      setAnalysisKeys((current) => ({
        ...current,
        [task.task_id]: idempotencyKey,
      }));
    }
    try {
      await startFixture.mutateAsync({
        task_id: task.task_id,
        idempotency_key: idempotencyKey,
        requested_by: operator.trim(),
      });
    } catch {
      // Mutation state renders the error while the idempotency key is retained.
    }
  };

  return (
    <section
      aria-labelledby="ai-research-task-title"
      className="app-ai-research-boundary p-4 sm:p-5"
      data-evidence-kind="cited-ai-research"
      data-testid="ai-research-task-panel"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {copy.kicker}
          </div>
          <h2
            className="mt-2 text-lg font-semibold text-[var(--app-text)]"
            id="ai-research-task-title"
          >
            {copy.title}
          </h2>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {open ? copy.detail : copy.closedDetail}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <BoundaryBadge label={copy.noModel} />
          <BoundaryBadge label={copy.noAuthority} />
          <button
            className="app-button-secondary px-3 py-2 text-xs font-semibold"
            onClick={() => setOpen((current) => !current)}
            type="button"
          >
            {open ? copy.close : copy.open}
          </button>
        </div>
      </div>

      {open ? (
        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.18fr)]">
          <form
            className="border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-4"
            onSubmit={(event) => void submit(event)}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <LabeledInput
                label={copy.operator}
                onChange={setOperator}
                required
                value={operator}
              />
              <LabeledInput
                label={copy.account}
                onChange={setAccountAlias}
                required
                value={accountAlias}
              />
            </div>
            <div className="mt-3">
              <LabeledInput
                label={copy.taskTitle}
                onChange={setTitle}
                required
                value={title}
              />
            </div>
            <label className="mt-3 block text-xs font-semibold text-[var(--app-muted)]">
              {copy.question}
              <textarea
                className="app-input mt-1 min-h-24 w-full resize-y px-3 py-2 text-sm text-[var(--app-text)]"
                onChange={(event) => setQuestion(event.target.value)}
                required
                value={question}
              />
            </label>
            <label className="mt-3 flex items-start gap-2 text-sm text-[var(--app-text)]">
              <input
                checked={includeBacktest}
                className="mt-1"
                disabled={backtestResultId === null}
                onChange={(event) => setIncludeBacktest(event.target.checked)}
                type="checkbox"
              />
              <span>
                {copy.includeBacktest}
                {backtestResultId === null ? (
                  <span className="app-muted mt-1 block text-xs">
                    {copy.noBacktest}
                  </span>
                ) : (
                  <span className="app-muted mt-1 block font-mono text-xs">
                    backtest_result_id={backtestResultId}
                  </span>
                )}
              </span>
            </label>
            <label className="mt-3 flex items-start gap-2 text-sm text-[var(--app-text)]">
              <input
                checked={includeContribution}
                className="mt-1"
                disabled={strategyId === null}
                onChange={(event) =>
                  setIncludeContribution(event.target.checked)
                }
                type="checkbox"
              />
              <span>
                {copy.includeContribution}
                {strategyId === null ? (
                  <span className="app-muted mt-1 block text-xs">
                    {copy.noContribution}
                  </span>
                ) : (
                  <span className="app-muted mt-1 block font-mono text-xs">
                    strategy_id={strategyId}
                  </span>
                )}
              </span>
            </label>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                className="app-button-primary px-4 py-2 text-sm font-semibold"
                disabled={
                  createTask.isPending ||
                  (includeContribution && strategyId === null)
                }
                type="submit"
              >
                {createTask.isPending ? copy.submitting : copy.submit}
              </button>
              <span className="text-xs text-[var(--app-muted)]">
                {copy.persistedOnly}
              </span>
            </div>
            {createTask.isError ? (
              <p
                className="mt-3 text-sm text-[var(--app-danger-text)]"
                role="alert"
              >
                {createTask.error.message}
              </p>
            ) : null}
            {successMessage ? (
              <p
                className="mt-3 text-sm text-[var(--app-success-text)]"
                role="status"
              >
                {successMessage}
              </p>
            ) : null}
          </form>

          <div className="min-w-0">
            <label className="block text-xs font-semibold text-[var(--app-muted)]">
              {copy.reviewNote}
              <input
                className="app-input mt-1 w-full px-3 py-2 text-sm text-[var(--app-text)]"
                onChange={(event) => setReviewNote(event.target.value)}
                value={reviewNote}
              />
            </label>
            {tasks.isLoading ? (
              <p className="app-muted mt-4 text-sm" role="status">
                {copy.loading}
              </p>
            ) : tasks.isError ? (
              <p
                className="mt-4 text-sm text-[var(--app-danger-text)]"
                role="alert"
              >
                {copy.loadError}
              </p>
            ) : tasks.data?.tasks.length ? (
              <div className="mt-3 space-y-3">
                {tasks.data.tasks.map((task) => (
                  <ResearchTaskCard
                    analysis={analyses.data?.analyses.find(
                      (item) => item.task_id === task.task_id,
                    )}
                    analysisPending={startFixture.isPending}
                    copy={copy}
                    key={task.task_id}
                    onReview={(decision) => void review(task, decision)}
                    onStartAnalysis={() => void startAnalysis(task)}
                    reviewDisabled={reviewTask.isPending || !reviewNote.trim()}
                    task={task}
                  />
                ))}
              </div>
            ) : (
              <p className="app-muted mt-4 text-sm">{copy.empty}</p>
            )}
            {reviewTask.isPending ? (
              <p className="app-muted mt-3 text-xs" role="status">
                {copy.reviewing}
              </p>
            ) : null}
            {reviewTask.isError ? (
              <p
                className="mt-3 text-sm text-[var(--app-danger-text)]"
                role="alert"
              >
                {reviewTask.error.message}
              </p>
            ) : null}
            {analyses.isLoading ? (
              <p className="app-muted mt-3 text-xs" role="status">
                {copy.analysisLoading}
              </p>
            ) : null}
            {analyses.isError ? (
              <p
                className="mt-3 text-sm text-[var(--app-danger-text)]"
                role="alert"
              >
                {copy.analysisLoadError}
              </p>
            ) : null}
            {startFixture.isError ? (
              <p
                className="mt-3 text-sm text-[var(--app-danger-text)]"
                role="alert"
              >
                {startFixture.error.message}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ResearchTaskCard({
  analysis,
  analysisPending,
  copy,
  onReview,
  onStartAnalysis,
  reviewDisabled,
  task,
}: {
  analysis?: ResearchTaskFixtureAnalysis;
  analysisPending: boolean;
  copy: (typeof COPY)['en'] | (typeof COPY)['zh'];
  onReview: (
    decision:
      | 'context_accepted'
      | 'context_revision_requested'
      | 'closed_without_analysis',
  ) => void;
  onStartAnalysis: () => void;
  reviewDisabled: boolean;
  task: HumanResearchTask;
}) {
  const appCopy = useCopy();
  const reviewable =
    task.status === 'awaiting_human_review' ||
    task.status === 'blocked_by_evidence';
  return (
    <article className="rounded-2xl border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_62%,transparent)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-[var(--app-text)]">
            {task.title}
          </h3>
          <p className="app-muted mt-1 text-xs leading-5">
            {task.research_question}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <EvidenceIdentityDisclosure
            triggerLabel={appCopy.common.viewEvidenceIdentity}
            title={appCopy.common.evidenceIdentityTitle}
            description={appCopy.common.evidenceIdentityDescription}
            closeLabel={appCopy.common.closeEvidenceIdentity}
            copyLabel={appCopy.common.copyEvidenceValue}
            copiedLabel={appCopy.common.evidenceValueCopied}
            fields={[
              {
                label: appCopy.common.valuationSnapshot,
                value: task.valuation_snapshot_id,
                mono: true,
              },
              {
                label: appCopy.common.ledgerCutoff,
                value: task.ledger_cutoff_id,
                mono: true,
              },
              {
                label: appCopy.common.captureIdentity,
                value: task.capture_id,
                mono: true,
              },
              {
                label: appCopy.common.contextSnapshot,
                value: task.context_snapshot_id,
                mono: true,
              },
              {
                label: appCopy.common.contextFingerprint,
                value: task.context_fingerprint,
                mono: true,
              },
            ]}
          />
          <span className="rounded-full border border-[var(--app-border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-text)]">
            {copy.statuses[task.status]}
          </span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {task.evidence.map((evidence) => (
          <span
            className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[10px] text-[var(--app-muted)]"
            key={evidence.evidence_reference_id}
            title={evidence.evidence_reference_id}
          >
            {evidence.tool_name} · {evidence.status}
          </span>
        ))}
        <span className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[10px] text-[var(--app-muted)]">
          {copy.evidence}: {task.evidence.length}
        </span>
        <span className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[10px] text-[var(--app-muted)]">
          {task.all_evidence_authoritative
            ? copy.authoritative
            : `${copy.blocked}: ${task.blockers.length}`}
        </span>
      </div>
      {reviewable ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="app-button-secondary px-3 py-1.5 text-xs font-semibold"
            disabled={reviewDisabled || !task.all_evidence_authoritative}
            onClick={() => onReview('context_accepted')}
            title={
              task.all_evidence_authoritative ? undefined : copy.acceptBlocked
            }
            type="button"
          >
            {copy.accept}
          </button>
          <button
            className="app-button-secondary px-3 py-1.5 text-xs font-semibold"
            disabled={reviewDisabled}
            onClick={() => onReview('context_revision_requested')}
            type="button"
          >
            {copy.revise}
          </button>
          <button
            className="app-button-secondary px-3 py-1.5 text-xs font-semibold"
            disabled={reviewDisabled}
            onClick={() => onReview('closed_without_analysis')}
            type="button"
          >
            {copy.closeWithout}
          </button>
        </div>
      ) : null}
      {task.status === 'context_accepted' && !analysis ? (
        <div className="mt-4 border-t border-[var(--app-border)] pt-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-1.5">
              <BoundaryBadge label={copy.fixtureOnly} />
              <BoundaryBadge label={copy.noNetwork} />
            </div>
            <button
              className="app-button-primary px-3 py-1.5 text-xs font-semibold"
              disabled={analysisPending}
              onClick={onStartAnalysis}
              type="button"
            >
              {analysisPending ? copy.runningFixture : copy.runFixture}
            </button>
          </div>
        </div>
      ) : null}
      {analysis ? (
        <FixtureAnalysisSummary analysis={analysis} copy={copy} />
      ) : null}
    </article>
  );
}

function FixtureAnalysisSummary({
  analysis,
  copy,
}: {
  analysis: ResearchTaskFixtureAnalysis;
  copy: (typeof COPY)['en'] | (typeof COPY)['zh'];
}) {
  const reportArtifact = analysis.artifacts.find(
    (artifact) => artifact.kind === 'report',
  );
  const reportSummary =
    typeof reportArtifact?.content.summary === 'string'
      ? reportArtifact.content.summary
      : null;
  const bindingValid = analysis.binding_validity === 'valid';
  const memoryValid =
    analysis.memory_validity === 'human_review_required_exact_context_only';

  return (
    <section
      aria-label={copy.report}
      className="mt-4 border-t border-[var(--app-border)] pt-3"
    >
      <div className="flex flex-wrap gap-1.5">
        <BoundaryBadge label={copy.fixtureOnly} />
        <BoundaryBadge label={copy.noNetwork} />
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <EvidenceIdentity
          label={copy.analysisStatus}
          value={analysis.workflow_status}
        />
        <EvidenceIdentity
          label={copy.bindingStatus}
          value={bindingValid ? copy.bindingValid : copy.bindingDrift}
        />
        <EvidenceIdentity
          label={copy.memoryStatus}
          value={memoryValid ? copy.memoryPending : copy.memoryInvalid}
        />
        <EvidenceIdentity
          label="Audit"
          value={
            analysis.audit_replay.valid ? copy.auditValid : copy.auditInvalid
          }
        />
      </dl>
      <div className="mt-3 flex flex-wrap gap-1.5" aria-label={copy.artifacts}>
        {analysis.artifacts.map((artifact) => (
          <span
            className="rounded-full border border-[var(--app-border)] px-2 py-1 text-[10px] text-[var(--app-muted)]"
            key={artifact.artifact_id}
            title={artifact.artifact_id}
          >
            {artifact.kind} · {artifact.evidence_reference_ids.length}
          </span>
        ))}
      </div>
      {reportSummary ? (
        <div className="mt-3 rounded-xl border border-[var(--app-border)] p-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--app-muted)]">
            {copy.report}
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text)]">
            {reportSummary}
          </p>
        </div>
      ) : null}
      {!bindingValid && analysis.binding_errors.length ? (
        <ul className="mt-3 space-y-1 text-xs text-[var(--app-danger-text)]">
          {analysis.binding_errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      ) : null}
      <FixtureAnalysisReviewControl analysis={analysis} copy={copy} />
    </section>
  );
}

function FixtureAnalysisReviewControl({
  analysis,
  copy,
}: {
  analysis: ResearchTaskFixtureAnalysis;
  copy: (typeof COPY)['en'] | (typeof COPY)['zh'];
}) {
  const reviews = useResearchTaskAnalysisReviewsQuery(analysis.analysis_id);
  const recordReview = useReviewFixtureAnalysisMutation();
  const [reviewedBy, setReviewedBy] = useState(analysis.requested_by);
  const [note, setNote] = useState('');
  const [idempotencyKeys, setIdempotencyKeys] = useState<
    Partial<Record<AnalysisReviewDecision, string>>
  >({});
  const review = reviews.data?.reviews[0];
  const acceptanceEligible =
    analysis.workflow_status === 'completed' &&
    !analysis.partial_result &&
    analysis.binding_validity === 'valid' &&
    analysis.audit_replay.valid &&
    analysis.memory_validity === 'human_review_required_exact_context_only';
  const formReady = Boolean(reviewedBy.trim() && note.trim());

  const submitReview = async (decision: AnalysisReviewDecision) => {
    const idempotencyKey =
      idempotencyKeys[decision] ?? newAuditKey('ai-analysis-review');
    if (!idempotencyKeys[decision]) {
      setIdempotencyKeys((current) => ({
        ...current,
        [decision]: idempotencyKey,
      }));
    }
    try {
      await recordReview.mutateAsync({
        analysis_id: analysis.analysis_id,
        idempotency_key: idempotencyKey,
        reviewed_by: reviewedBy.trim(),
        decision,
        note: note.trim(),
      });
    } catch {
      // The mutation state renders the fail-closed response and keeps the key.
    }
  };

  return (
    <section
      aria-label={copy.analysisReview}
      className="mt-4 rounded-xl border border-[var(--app-border)] p-3"
    >
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--app-muted)]">
        {copy.analysisReview}
      </div>
      <p className="app-muted mt-1 text-xs leading-5">
        {copy.analysisReviewBoundary}
      </p>
      {reviews.isLoading ? (
        <p className="app-muted mt-3 text-xs" role="status">
          {copy.analysisLoading}
        </p>
      ) : reviews.isError ? (
        <p className="mt-3 text-xs text-[var(--app-danger-text)]" role="alert">
          {copy.analysisReviewLoadError}
        </p>
      ) : review ? (
        <RecordedAnalysisReview copy={copy} review={review} />
      ) : (
        <div className="mt-3 space-y-3">
          <LabeledInput
            label={copy.reviewer}
            onChange={setReviewedBy}
            required
            value={reviewedBy}
          />
          <label className="block text-xs font-semibold text-[var(--app-muted)]">
            {copy.analysisReviewNote}
            <textarea
              className="app-input mt-1 min-h-20 w-full resize-y px-3 py-2 text-sm text-[var(--app-text)]"
              onChange={(event) => setNote(event.target.value)}
              required
              value={note}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              className="app-button-primary px-3 py-1.5 text-xs font-semibold"
              disabled={
                recordReview.isPending || !formReady || !acceptanceEligible
              }
              onClick={() => void submitReview('accept_as_reviewed_memory')}
              title={
                acceptanceEligible ? undefined : copy.acceptAnalysisBlocked
              }
              type="button"
            >
              {copy.acceptMemory}
            </button>
            <button
              className="app-button-secondary px-3 py-1.5 text-xs font-semibold"
              disabled={recordReview.isPending || !formReady}
              onClick={() => void submitReview('request_revision')}
              type="button"
            >
              {copy.requestAnalysisRevision}
            </button>
            <button
              className="app-button-secondary px-3 py-1.5 text-xs font-semibold"
              disabled={recordReview.isPending || !formReady}
              onClick={() => void submitReview('reject')}
              type="button"
            >
              {copy.rejectAnalysis}
            </button>
          </div>
          {!formReady ? (
            <p className="app-muted text-xs">{copy.analysisReviewRequired}</p>
          ) : null}
        </div>
      )}
      {recordReview.isPending ? (
        <p className="app-muted mt-3 text-xs" role="status">
          {copy.recordingAnalysisReview}
        </p>
      ) : null}
      {recordReview.isError ? (
        <p className="mt-3 text-xs text-[var(--app-danger-text)]" role="alert">
          {recordReview.error.message}
        </p>
      ) : null}
    </section>
  );
}

function RecordedAnalysisReview({
  copy,
  review,
}: {
  copy: (typeof COPY)['en'] | (typeof COPY)['zh'];
  review: ResearchTaskAnalysisReview;
}) {
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-[var(--app-border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-text)]">
          {copy.analysisReviewStatuses[review.effective_status]}
        </span>
        <span className="text-xs text-[var(--app-muted)]">
          {review.memory_recall_eligible
            ? copy.memoryRecallEligible
            : copy.memoryRecallIneligible}
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--app-text)]">
        {review.note}
      </p>
      <p className="app-muted mt-1 text-[10px]">
        {review.reviewed_by} · {review.created_at}
      </p>
      {review.invalidation_reasons.length ? (
        <ul className="mt-2 space-y-1 text-xs text-[var(--app-danger-text)]">
          {review.invalidation_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function LabeledInput({
  label,
  onChange,
  required,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  required?: boolean;
  value: string;
}) {
  return (
    <label className="block text-xs font-semibold text-[var(--app-muted)]">
      {label}
      <input
        className="app-input mt-1 w-full px-3 py-2 text-sm text-[var(--app-text)]"
        onChange={(event) => onChange(event.target.value)}
        required={required}
        value={value}
      />
    </label>
  );
}

function BoundaryBadge({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-[color-mix(in_srgb,var(--app-warning)_42%,var(--app-border))] bg-[var(--app-warning-bg)] px-2.5 py-1.5 text-[10px] font-semibold text-[var(--app-warning)]">
      {label}
    </span>
  );
}

function EvidenceIdentity({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.12em] text-[var(--app-muted)]">
        {label}
      </dt>
      <dd
        className="mt-1 truncate font-mono text-[var(--app-text)]"
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
