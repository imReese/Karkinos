import { useMemo, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import { StatusBadge } from '../../../shared/ui/workbench';
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
      className="app-decision-next-action min-w-0 border-l-2 border-[var(--app-accent)] bg-[var(--app-surface)] px-4 py-4 sm:px-6 sm:py-5"
      aria-labelledby="decision-next-action-title"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="app-type-label font-semibold text-[var(--app-text-secondary)]">
          {labels.nextActionKicker}
        </span>
        <StatusBadge
          tone={
            guide.status === '通过' || guide.status === 'Passed'
              ? 'success'
              : 'warning'
          }
        >
          {guide.status}
        </StatusBadge>
      </div>
      <div className="mt-2 flex min-w-0 flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 max-w-3xl">
          <h2
            id="decision-next-action-title"
            className="text-xl font-semibold leading-7 tracking-tight text-[var(--app-text)] sm:text-2xl sm:leading-8"
          >
            {guide.title}
          </h2>
          <p className="mt-2 text-sm leading-6 text-[var(--app-text-secondary)]">
            {guide.reason}
          </p>
        </div>
        {guide.href && guide.cta ? (
          <a
            className="app-button-primary inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-[var(--app-radius-control)] px-4 py-2 text-sm font-semibold"
            href={guide.href}
            onClick={(event) => handleClientNavigation(event, guide.href!)}
          >
            {guide.cta}
            <ArrowUpRight className="size-4 shrink-0" aria-hidden="true" />
          </a>
        ) : null}
      </div>
      <div className="mt-4 border-t border-[var(--app-divider)] pt-3 text-xs leading-5 text-[var(--app-text-secondary)]">
        <span className="mr-2 font-medium text-[var(--app-text)]">
          {locale === 'zh' ? '解除条件' : 'Unblock condition'}
        </span>
        {guide.unblockCondition}
        {guide.note &&
        guide.note !== guide.reason &&
        guide.note !== guide.unblockCondition ? (
          <p className="mt-1 text-[var(--app-text-tertiary)]">{guide.note}</p>
        ) : null}
      </div>
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
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
    >
      <div className="min-w-0 px-1 sm:px-3">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.workflowLaneKicker}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.workflowLaneTitle}
            </h2>
            <p className="sr-only">{labels.workflowLaneDetail}</p>
          </div>
        </div>

        {!expanded ? (
          <div className="mt-4 flex min-w-0 flex-col gap-3 border-y border-[var(--app-divider)] px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.workflowCollapsedTitle(denseCandidateCount)}
              </div>
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
          onClick={(e) => handleClientNavigation(e, target.href)}
        >
          {target.label}
        </a>
      ) : null}
    </article>
  );
}
