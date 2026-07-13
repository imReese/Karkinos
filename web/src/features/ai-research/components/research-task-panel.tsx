import { useState, type FormEvent } from 'react';

import { usePreferences } from '../../../app/preferences';
import {
  useCreateHumanResearchTaskMutation,
  useResearchTasksQuery,
  useReviewResearchTaskMutation,
  type HumanResearchTask,
  type ResearchEvidenceType,
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
      'Freeze canonical evidence, record a task, then review the context. No model or workflow is started.',
    closedDetail:
      'This boundary is idle until you open it. It never polls a model or provider.',
    open: 'Open research tasks',
    close: 'Close',
    noModel: 'Model execution off',
    noAuthority: 'No trading authority',
    operator: 'Human operator',
    account: 'Account alias',
    taskTitle: 'Task title',
    question: 'Research question',
    includeBacktest: 'Bind saved backtest evidence',
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
      '先冻结 canonical 证据，再记录任务并人工复核上下文；本阶段不会启动模型或 workflow。',
    closedDetail: '显式打开前保持空闲；不会轮询模型或 provider。',
    open: '打开研究任务',
    close: '收起',
    noModel: '模型执行关闭',
    noAuthority: '无交易权限',
    operator: '人工操作人',
    account: '账户别名',
    taskTitle: '任务标题',
    question: '研究问题',
    includeBacktest: '绑定已保存回测证据',
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
}: {
  backtestResultId: number | null;
}) {
  const { locale } = usePreferences();
  const copy = COPY[locale];
  const [open, setOpen] = useState(false);
  const tasks = useResearchTasksQuery(open);
  const createTask = useCreateHumanResearchTaskMutation();
  const reviewTask = useReviewResearchTaskMutation();
  const [operator, setOperator] = useState('human:owner');
  const [accountAlias, setAccountAlias] = useState('primary');
  const [title, setTitle] = useState('Review frozen investment evidence');
  const [question, setQuestion] = useState('');
  const [includeBacktest, setIncludeBacktest] = useState(false);
  const [reviewNote, setReviewNote] = useState('');
  const [captureKey, setCaptureKey] = useState(() =>
    newAuditKey('ai-context-capture'),
  );
  const [taskKey, setTaskKey] = useState(() => newAuditKey('ai-research-task'));
  const [reviewKeys, setReviewKeys] = useState<Record<string, string>>({});
  const [successMessage, setSuccessMessage] = useState('');

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSuccessMessage('');
    const evidenceTypes = [...BASE_EVIDENCE];
    if (includeBacktest && backtestResultId !== null) {
      evidenceTypes.push('research_evidence');
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

  return (
    <section
      aria-labelledby="ai-research-task-title"
      className="app-panel rounded-[28px] border border-[color-mix(in_srgb,var(--app-accent)_24%,var(--app-border))] p-5 sm:p-6"
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
            className="rounded-2xl border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_62%,transparent)] p-4"
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
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                className="app-button-primary px-4 py-2 text-sm font-semibold"
                disabled={createTask.isPending}
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
                className="mt-3 text-sm text-[var(--app-negative)]"
                role="alert"
              >
                {createTask.error.message}
              </p>
            ) : null}
            {successMessage ? (
              <p
                className="mt-3 text-sm text-[var(--app-positive)]"
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
                className="mt-4 text-sm text-[var(--app-negative)]"
                role="alert"
              >
                {copy.loadError}
              </p>
            ) : tasks.data?.tasks.length ? (
              <div className="mt-3 space-y-3">
                {tasks.data.tasks.map((task) => (
                  <ResearchTaskCard
                    copy={copy}
                    key={task.task_id}
                    onReview={(decision) => void review(task, decision)}
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
                className="mt-3 text-sm text-[var(--app-negative)]"
                role="alert"
              >
                {reviewTask.error.message}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ResearchTaskCard({
  copy,
  onReview,
  reviewDisabled,
  task,
}: {
  copy: (typeof COPY)['en'] | (typeof COPY)['zh'];
  onReview: (
    decision:
      | 'context_accepted'
      | 'context_revision_requested'
      | 'closed_without_analysis',
  ) => void;
  reviewDisabled: boolean;
  task: HumanResearchTask;
}) {
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
        <span className="rounded-full border border-[var(--app-border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-text)]">
          {copy.statuses[task.status]}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <EvidenceIdentity
          label={copy.snapshot}
          value={task.valuation_snapshot_id}
        />
        <EvidenceIdentity
          label={copy.cutoff}
          value={String(task.ledger_cutoff_id)}
        />
      </dl>
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
    </article>
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
