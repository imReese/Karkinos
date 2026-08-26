import { useState, type FormEvent } from 'react';

import { EvidenceState, StatusBadge } from '../../../shared/ui/workbench';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useCreateHumanResearchTaskMutation,
  useResearchTaskFixtureAnalysesQuery,
  useResearchTasksQuery,
  useReviewResearchTaskMutation,
  useStartFixtureAnalysisMutation,
  type HumanResearchTask,
} from '../research-task-api';
import {
  BoundaryBadge,
  LabeledInput,
  ResearchTaskCard,
} from './research-task-card';
import { RESEARCH_TASK_COPY } from './research-task-copy';
import { BASE_EVIDENCE, newAuditKey } from './research-task-values';

export function ResearchTaskPanel({
  backtestResultId,
  defaultOpen = false,
  routePrimary = false,
  strategyId,
}: {
  backtestResultId: number | null;
  defaultOpen?: boolean;
  routePrimary?: boolean;
  strategyId: string | null;
}) {
  const { locale } = usePreferences();
  const copy = RESEARCH_TASK_COPY[locale];
  const [open, setOpen] = useState(defaultOpen);
  const [composerOpen, setComposerOpen] = useState(false);
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
      setComposerOpen(false);
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
      className={`app-ai-research-boundary ${routePrimary ? 'p-0' : 'p-3 sm:p-5'}`}
      data-evidence-kind="cited-ai-research"
      data-testid="ai-research-task-panel"
    >
      <ResearchTaskPanelHeader
        copy={copy}
        onToggle={() => setOpen((current) => !current)}
        open={open}
        routePrimary={routePrimary}
      />

      {open ? (
        <div
          className={`${routePrimary ? 'mt-4' : 'mt-5'} grid gap-5 ${
            composerOpen
              ? 'xl:grid-cols-[minmax(320px,0.92fr)_minmax(0,1.08fr)]'
              : ''
          }`}
        >
          <section
            aria-labelledby="ai-research-queue-title"
            className={`min-w-0 ${
              routePrimary ? '' : 'border-t border-[var(--app-divider)] pt-4'
            }`}
          >
            <div
              className={`flex flex-wrap items-start justify-between gap-3 ${
                routePrimary ? 'app-ai-research-route-queue-header' : ''
              }`}
            >
              <div className="min-w-0">
                <div className="app-product-mark">{copy.queueKicker}</div>
                <h3
                  className="app-type-section-title mt-1.5 text-[var(--app-text)]"
                  id="ai-research-queue-title"
                >
                  {copy.queueTitle}
                </h3>
                <p className="app-muted mt-1 max-w-2xl text-xs leading-5">
                  {copy.queueDetail}
                </p>
              </div>
              <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
                <StatusBadge className="max-w-full truncate" tone="neutral">
                  {tasks.isLoading
                    ? copy.loading
                    : copy.taskCount(tasks.data?.tasks.length ?? 0)}
                </StatusBadge>
                <button
                  aria-expanded={composerOpen}
                  className="app-button-secondary min-h-11 px-3 py-2 text-xs font-semibold"
                  onClick={() => setComposerOpen((current) => !current)}
                  type="button"
                >
                  {composerOpen ? copy.closeDraft : copy.newTask}
                </button>
              </div>
            </div>
            {tasks.data?.tasks.length ? (
              <label className="mt-4 block text-xs font-semibold text-[var(--app-muted)]">
                {copy.reviewNote}
                <input
                  className="app-input mt-1 min-h-11 w-full px-3 py-2 text-sm text-[var(--app-text)]"
                  onChange={(event) => setReviewNote(event.target.value)}
                  value={reviewNote}
                />
              </label>
            ) : null}
            {tasks.isLoading ? (
              <EvidenceState
                className="mt-4"
                description={copy.loading}
                kind="loading"
                title={copy.loadingTitle}
              />
            ) : tasks.isError ? (
              <EvidenceState
                className="mt-4"
                description={copy.loadError}
                kind="error"
                title={copy.loadErrorTitle}
              />
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
              <div className="mt-4">
                <EvidenceState
                  description={copy.empty}
                  kind="empty"
                  title={copy.emptyTitle}
                />
                <ol
                  aria-label={copy.emptyWorkflowLabel}
                  className="mt-4 grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2 xl:grid-cols-4 xl:gap-y-5"
                  data-testid="ai-research-empty-workflow"
                >
                  {copy.emptyWorkflow.map((step, index) => (
                    <li
                      className="min-w-0 border-t border-[var(--app-divider)] pt-3"
                      key={step.title}
                    >
                      <span className="app-type-micro font-mono font-semibold text-[var(--app-accent)]">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <strong className="mt-1 block text-xs font-semibold text-[var(--app-text)]">
                        {step.title}
                      </strong>
                      <span className="app-muted app-type-micro mt-1 block">
                        {step.detail}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {successMessage ? (
              <EvidenceState
                className="mt-3"
                description={successMessage}
                kind="ready"
                title={copy.successTitle}
              />
            ) : null}
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
          </section>

          {composerOpen ? (
            <ResearchTaskComposer
              accountAlias={accountAlias}
              backtestResultId={backtestResultId}
              copy={copy}
              createTask={createTask}
              includeBacktest={includeBacktest}
              includeContribution={includeContribution}
              onSubmit={submit}
              operator={operator}
              question={question}
              setAccountAlias={setAccountAlias}
              setIncludeBacktest={setIncludeBacktest}
              setIncludeContribution={setIncludeContribution}
              setOperator={setOperator}
              setQuestion={setQuestion}
              setTitle={setTitle}
              strategyId={strategyId}
              title={title}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ResearchTaskPanelHeader({
  copy,
  onToggle,
  open,
  routePrimary,
}: {
  copy: (typeof RESEARCH_TASK_COPY)[keyof typeof RESEARCH_TASK_COPY];
  onToggle: () => void;
  open: boolean;
  routePrimary: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 ${
        routePrimary
          ? 'app-ai-research-route-toolbar min-h-11 flex-wrap border-b border-[var(--app-divider)] pb-3'
          : 'sm:items-start'
      }`}
    >
      {routePrimary ? (
        <>
          <h2 className="sr-only" id="ai-research-task-title">
            {copy.title}
          </h2>
          <div className="app-ai-research-boundary-badges flex min-w-0 flex-1 flex-wrap gap-2">
            <BoundaryBadge label={copy.noModel} />
            <BoundaryBadge label={copy.noAuthority} />
          </div>
        </>
      ) : (
        <div className="min-w-0">
          <div className="app-kicker app-type-overline hidden sm:block">
            {copy.kicker}
          </div>
          <h2
            className="text-base font-semibold text-[var(--app-text)] sm:mt-2 sm:text-lg"
            id="ai-research-task-title"
          >
            {copy.title}
          </h2>
          <p className="app-muted mt-2 hidden max-w-3xl text-sm leading-6 sm:block">
            {open ? copy.detail : copy.closedDetail}
          </p>
        </div>
      )}
      <div className="flex shrink-0 items-center gap-2">
        {!routePrimary ? (
          <div className="hidden flex-wrap gap-2 sm:flex">
            <BoundaryBadge label={copy.noModel} />
            <BoundaryBadge label={copy.noAuthority} />
          </div>
        ) : null}
        <button
          aria-expanded={open}
          aria-label={open ? copy.close : copy.open}
          className="app-button-secondary min-h-11 px-3 py-2 text-xs font-semibold"
          onClick={onToggle}
          type="button"
        >
          {routePrimary ? (
            <>
              <span className="sm:hidden">
                {open ? copy.closeCompact : copy.openCompact}
              </span>
              <span className="hidden sm:inline">
                {open ? copy.close : copy.open}
              </span>
            </>
          ) : open ? (
            copy.close
          ) : (
            copy.open
          )}
        </button>
      </div>
    </div>
  );
}

function ResearchTaskComposer({
  accountAlias,
  backtestResultId,
  copy,
  createTask,
  includeBacktest,
  includeContribution,
  onSubmit,
  operator,
  question,
  setAccountAlias,
  setIncludeBacktest,
  setIncludeContribution,
  setOperator,
  setQuestion,
  setTitle,
  strategyId,
  title,
}: {
  accountAlias: string;
  backtestResultId: number | null;
  copy: (typeof RESEARCH_TASK_COPY)[keyof typeof RESEARCH_TASK_COPY];
  createTask: ReturnType<typeof useCreateHumanResearchTaskMutation>;
  includeBacktest: boolean;
  includeContribution: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  operator: string;
  question: string;
  setAccountAlias: (value: string) => void;
  setIncludeBacktest: (value: boolean) => void;
  setIncludeContribution: (value: boolean) => void;
  setOperator: (value: string) => void;
  setQuestion: (value: string) => void;
  setTitle: (value: string) => void;
  strategyId: string | null;
  title: string;
}) {
  return (
    <form
      aria-labelledby="ai-research-composer-title"
      className="border-t border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-4"
      onSubmit={(event) => void onSubmit(event)}
    >
      <div className="app-product-mark">{copy.formKicker}</div>
      <h3
        className="app-type-section-title mt-1.5 text-[var(--app-text)]"
        id="ai-research-composer-title"
      >
        {copy.formTitle}
      </h3>
      <p className="app-muted mt-1 text-xs leading-5">{copy.formDetail}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
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
          onChange={(event) => setIncludeContribution(event.target.checked)}
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
          className="app-button-primary min-h-11 px-4 py-2 text-sm font-semibold"
          disabled={
            createTask.isPending || (includeContribution && strategyId === null)
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
        <p className="mt-3 text-sm text-[var(--app-danger-text)]" role="alert">
          {createTask.error.message}
        </p>
      ) : null}
    </form>
  );
}
