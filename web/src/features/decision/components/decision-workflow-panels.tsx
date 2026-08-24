import { useMemo, useState } from 'react';
import { ExceptionList, StatusBadge } from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import {
  usePreferences,
  type Locale,
} from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { type DecisionResponse, type DecisionWorkflowTask } from '../api';
import { decisionTone } from './decision-status-model';
import {
  decisionGateDetailLabels,
  decisionNextActionGuide,
  decisionWorkflowTarget,
} from './decision-workflow-model';

export function DecisionNextActionGuidePanel({
  lanes,
}: {
  lanes: DecisionResponse[];
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const guide = useMemo(
    () => decisionNextActionGuide(lanes, labels, locale),
    [lanes, labels, locale],
  );

  if (!guide) {
    return null;
  }

  return (
    <section
      data-testid="decision-next-action-guide"
      className="min-w-0 space-y-2"
    >
      <h2 className="app-type-section-title text-[var(--app-text)]">
        {labels.nextActionKicker}
      </h2>
      <ExceptionList
        ariaLabel={labels.nextActionKicker}
        density="compact"
        emptyState={labels.workflowDetail}
        labels={{
          reason: locale === 'zh' ? '阻断原因' : 'Reason',
          unblockCondition: locale === 'zh' ? '解除条件' : 'Unblock condition',
          nextAction: locale === 'zh' ? '安全下一步' : 'Safe next step',
          evidence: locale === 'zh' ? '证据' : 'Evidence',
        }}
        items={[
          {
            id: 'primary-decision-action',
            severity: 'warning',
            statusLabel: guide.status,
            title: guide.title,
            reason: guide.reason,
            unblockCondition: guide.unblockCondition,
            nextAction:
              guide.href && guide.cta ? (
                <a
                  className="font-semibold text-[var(--app-accent)] underline decoration-transparent underline-offset-2 hover:decoration-current"
                  href={guide.href}
                >
                  {guide.cta}
                </a>
              ) : (
                guide.unblockCondition
              ),
            evidence: guide.note,
          },
        ]}
      />
    </section>
  );
}

export function DecisionSummaryCollapsedPanel({
  candidateCount,
  onExpand,
}: {
  candidateCount: number;
  onExpand: () => void;
}) {
  const labels = useCopy().decision;
  return (
    <section
      data-testid="decision-summary-collapsed"
      className="min-w-0 border-y border-[var(--app-divider)] py-3"
    >
      <div className="flex min-w-0 flex-col gap-3 px-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">
            {labels.summaryCollapsedKicker}
          </div>
          <h2 className="app-card-title mt-1.5">
            {labels.summaryCollapsedTitle(candidateCount)}
          </h2>
          <p className="app-muted mt-2 break-words text-sm leading-6">
            {labels.summaryCollapsedDetail}
          </p>
        </div>
        <button
          className="app-button-secondary inline-flex min-h-10 max-w-full items-center justify-center rounded-[var(--app-radius-control)] px-4 py-2 text-sm font-semibold"
          type="button"
          onClick={onExpand}
        >
          {labels.expandSummary}
        </button>
      </div>
    </section>
  );
}

export function DecisionWorkflowPanel({
  lanes,
}: {
  lanes: DecisionResponse[];
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const lanesWithTasks = lanes.filter(
    (lane) => (lane.summary.workflow_tasks ?? []).length > 0,
  );
  const denseCandidateCount = lanesWithTasks.reduce(
    (total, lane) => total + lane.summary.candidate_count,
    0,
  );
  const [expanded, setExpanded] = useState(denseCandidateCount === 0);

  if (lanesWithTasks.length === 0) {
    return null;
  }

  return (
    <section
      data-testid="decision-workflow-tasks"
      className="app-workbench-section min-w-0 py-4"
    >
      <div className="min-w-0 px-1 sm:px-3">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.workflowLaneKicker}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.workflowLaneTitle}
            </h2>
          </div>
          <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
            {labels.workflowLaneDetail}
          </p>
        </div>

        {!expanded ? (
          <div className="mt-4 flex min-w-0 flex-col gap-3 border-y border-[var(--app-divider)] px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.workflowCollapsedTitle(denseCandidateCount)}
              </div>
              <p className="app-muted mt-1 break-words text-xs leading-5">
                {labels.workflowCollapsedDetail}
              </p>
            </div>
            <button
              className="app-button-secondary inline-flex min-h-9 max-w-full items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
              type="button"
              onClick={() => setExpanded(true)}
            >
              {labels.expandWorkflow}
            </button>
          </div>
        ) : (
          <div className="mt-4 grid gap-4">
            {lanesWithTasks.map((lane) => {
              const laneLabel =
                lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane;
              const tasks = [...(lane.summary.workflow_tasks ?? [])].sort(
                (left, right) => left.priority - right.priority,
              );
              return (
                <div key={`${lane.lane}-workflow`} className="min-w-0">
                  <div className="app-product-mark mb-2">{laneLabel}</div>
                  <div className="grid min-w-0 divide-y divide-[var(--app-divider)] md:grid-cols-2 md:divide-y-0 xl:grid-cols-3">
                    {tasks.map((task) => (
                      <DecisionWorkflowTaskCard
                        key={`${lane.lane}-${task.id}`}
                        task={task}
                        locale={locale}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function DecisionWorkflowTaskCard({
  task,
  locale,
}: {
  task: DecisionWorkflowTask;
  locale: Locale;
}) {
  const labels = useCopy().decision;
  const actionLabels = decisionGateDetailLabels({
    requiredActions: task.required_actions,
    blockingReasons: task.blocking_reasons,
    labels,
    locale,
  });
  const taskLabel = labels.workflowTaskLabel(task.id);
  const target = decisionWorkflowTarget(task.id, labels);

  return (
    <article className="min-w-0 border-l-2 border-[var(--app-divider)] px-3 py-2.5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-words text-sm font-semibold text-[var(--app-text)]">
            {taskLabel}
          </div>
          <div className="app-muted mt-1 text-xs">
            {formatPublicStatus(task.status, locale)}
          </div>
        </div>
        <StatusBadge tone={decisionTone(task.status)}>
          {formatPublicStatus(task.status, locale)}
        </StatusBadge>
      </div>
      <ul className="mt-2 grid min-w-0 gap-1">
        {(actionLabels.length > 0 ? actionLabels : [labels.none]).map(
          (label, index) => (
            <li
              key={`${index}-${label}`}
              className="min-w-0 border-l border-[var(--app-divider)] pl-2 text-xs leading-5 text-[var(--app-text-secondary)]"
            >
              {label}
            </li>
          ),
        )}
      </ul>
      {target ? (
        <a
          aria-label={labels.workflowOpenSurfaceLabel(target.label, taskLabel)}
          className="app-button-secondary mt-3 inline-flex min-h-8 max-w-full items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
          href={target.href}
        >
          {target.label}
        </a>
      ) : null}
    </article>
  );
}
