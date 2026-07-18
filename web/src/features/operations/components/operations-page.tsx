import { useMemo } from 'react';

import type { ColumnDef } from '@tanstack/react-table';

import {
  DataTable,
  EvidenceState,
  ExceptionList,
  MetricStrip,
  StatusBadge,
  WorkspaceHeader,
  type ExceptionItem,
  type StatusTone,
} from '../../../app/components/workbench';
import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  type OperationsAttentionItem,
  type OperationsStatus,
  type OperationsSubsystem,
  type OperationsTodayResponse,
  useOperationsTodayQuery,
} from '../api';
import {
  operationsAttentionResolutionLabel,
  operationsNextActionLabel,
  operationsSubsystemLabel,
  operationsTargetHref,
} from '../presentation';

function formatEvidenceTime(value: string | null | undefined, locale: Locale) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(parsed);
}

function statusTone(status: OperationsStatus) {
  if (status === 'blocked') {
    return 'danger' as const;
  }
  if (status === 'degraded' || status === 'manual_action_required') {
    return 'warning' as const;
  }
  if (status === 'pass' || status === 'healthy' || status === 'no_action') {
    return 'success' as const;
  }
  return 'neutral' as const;
}

function exceptionTone(status: OperationsStatus): ExceptionItem['severity'] {
  const tone: StatusTone = statusTone(status);
  return tone === 'success' ? 'neutral' : tone;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function attentionContractIsSafe(
  item: unknown,
): item is OperationsAttentionItem {
  if (!isRecord(item) || !isRecord(item.evidence)) {
    return false;
  }
  return (
    item.schema_version === 'karkinos.operations_attention_item.v1' &&
    typeof item.subsystem_id === 'string' &&
    typeof item.status === 'string' &&
    typeof item.target === 'string' &&
    typeof item.next_action === 'string' &&
    typeof item.resolution_condition === 'string' &&
    typeof item.task_fingerprint === 'string' &&
    item.task_fingerprint.startsWith('sha256:') &&
    typeof item.evidence.status === 'string' &&
    (item.evidence.observed_at === null ||
      typeof item.evidence.observed_at === 'string') &&
    item.manual_acknowledgement_clears_status === false &&
    item.read_only_projection === true &&
    item.provider_contacted === false &&
    item.database_writes_performed === false &&
    item.authorizes_execution === false
  );
}

function subsystemContractIsSafe(value: unknown) {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === 'string' &&
    typeof value.status === 'string' &&
    typeof value.target === 'string' &&
    typeof value.next_action === 'string' &&
    typeof value.detail_status === 'string' &&
    (value.last_run_at === null || typeof value.last_run_at === 'string') &&
    Array.isArray(value.limitations) &&
    value.limitations.every((item) => typeof item === 'string')
  );
}

function operationsProjectionIsSafe(
  value: unknown,
): value is OperationsTodayResponse {
  if (!isRecord(value) || !isRecord(value.health)) {
    return false;
  }
  const health = value.health;
  const attentionItems = value.attention_items ?? [];
  return (
    value.schema_version === 'karkinos.operations_today.v1' &&
    typeof value.generated_at === 'string' &&
    typeof value.conclusion_status === 'string' &&
    [
      'total',
      'pass',
      'degraded',
      'blocked',
      'manual_action_required',
      'skipped',
    ].every(
      (key) => typeof health[key] === 'number' && Number.isFinite(health[key]),
    ) &&
    Array.isArray(value.subsystems) &&
    value.subsystems.every(subsystemContractIsSafe) &&
    Array.isArray(attentionItems) &&
    attentionItems.every(attentionContractIsSafe)
  );
}

export function OperationsPage() {
  const copy = useCopy();
  const labels = copy.operationsPage;
  const { locale } = usePreferences();
  const operations = useOperationsTodayQuery();
  const projection = operations.data;
  const projectionIsSafe = operationsProjectionIsSafe(projection);
  const attentionItems = projectionIsSafe
    ? (projection.attention_items ?? [])
    : [];
  const subsystemColumns = useMemo<ColumnDef<OperationsSubsystem, unknown>[]>(
    () => [
      {
        accessorKey: 'id',
        header: labels.subsystemHealth,
        cell: ({ row }) => (
          <a
            className="font-semibold text-[var(--app-accent)] underline decoration-transparent underline-offset-2 hover:decoration-current"
            href={operationsTargetHref(row.original.target)}
          >
            {operationsSubsystemLabel(row.original.id, locale)}
          </a>
        ),
      },
      {
        accessorKey: 'status',
        header: labels.status,
        cell: ({ row }) => (
          <StatusBadge tone={statusTone(row.original.status)}>
            {formatPublicStatus(row.original.status, locale)}
          </StatusBadge>
        ),
      },
      {
        accessorKey: 'detail_status',
        header: labels.evidenceStatus,
        cell: ({ row }) => (
          <span className="block max-w-48 whitespace-normal leading-5">
            {formatPublicStatus(row.original.detail_status, locale)}
          </span>
        ),
      },
      {
        accessorKey: 'next_action',
        header: labels.nextAction,
        cell: ({ row }) => (
          <span className="block max-w-64 whitespace-normal leading-5">
            {operationsNextActionLabel(row.original.next_action, locale)}
          </span>
        ),
      },
      {
        accessorKey: 'last_run_at',
        header: labels.observedAt,
        cell: ({ row }) =>
          formatEvidenceTime(row.original.last_run_at, locale) ??
          labels.noTimestamp,
      },
      {
        id: 'limitations',
        header: labels.limitations,
        cell: ({ row }) => (
          <span className="block max-w-72 whitespace-normal leading-5">
            {row.original.limitations.length > 0
              ? row.original.limitations.join(' · ')
              : labels.noLimitations}
          </span>
        ),
      },
    ],
    [labels, locale],
  );

  return (
    <section
      className="min-w-0 space-y-5 sm:space-y-6"
      data-testid="operations-page"
    >
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        context={`${labels.readOnly} · ${labels.providerFree} · ${labels.noAuthority}`}
      />

      {operations.isLoading && !projection ? (
        <div data-testid="operations-loading">
          <EvidenceState
            kind="loading"
            title={labels.loading}
            description={labels.sourceBoundary}
          />
        </div>
      ) : operations.isError || !projection ? (
        <div data-testid="operations-error">
          <EvidenceState
            kind="error"
            title={labels.error}
            description={labels.sourceBoundary}
            action={
              <button
                type="button"
                className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                onClick={() => void operations.refetch()}
              >
                {labels.retry}
              </button>
            }
          />
        </div>
      ) : !projectionIsSafe ? (
        <div data-testid="operations-contract-blocked">
          <EvidenceState
            kind="error"
            title={labels.projectionBlocked}
            description={labels.projectionBlockedDetail}
            evidence={labels.sourceBoundary}
          />
        </div>
      ) : (
        <>
          <MetricStrip
            ariaLabel={labels.subsystemHealth}
            items={[
              {
                id: 'total',
                label: labels.total,
                value: projection.health.total,
              },
              {
                id: 'degraded',
                label: labels.degraded,
                value: projection.health.degraded,
                tone: projection.health.degraded > 0 ? 'warning' : 'neutral',
              },
              {
                id: 'blocked',
                label: labels.blocked,
                value: projection.health.blocked,
                tone: projection.health.blocked > 0 ? 'warning' : 'neutral',
              },
              {
                id: 'manual-review',
                label: labels.manualReview,
                value: projection.health.manual_action_required,
                tone:
                  projection.health.manual_action_required > 0
                    ? 'warning'
                    : 'neutral',
              },
            ]}
          />

          <section
            className="min-w-0 space-y-2"
            aria-labelledby="operations-attention-heading"
            data-testid="operations-attention-queue"
          >
            <div className="flex items-baseline justify-between gap-3">
              <h2
                id="operations-attention-heading"
                className="text-base font-semibold text-[var(--app-text)]"
              >
                {labels.attentionQueue}
              </h2>
              <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
                {attentionItems.length}
              </span>
            </div>
            <ExceptionList
              ariaLabel={labels.attentionQueue}
              emptyState={labels.attentionEmpty}
              className="min-w-0"
              labels={{
                reason: labels.evidenceStatus,
                unblockCondition: labels.resolution,
                nextAction: labels.nextAction,
                evidence: labels.observedAt,
              }}
              items={attentionItems.map((item) => {
                const href = operationsTargetHref(item.target);
                return {
                  id: item.task_fingerprint,
                  severity: exceptionTone(item.status),
                  statusLabel: formatPublicStatus(item.status, locale),
                  title: operationsSubsystemLabel(item.subsystem_id, locale),
                  reason: formatPublicStatus(item.evidence.status, locale),
                  unblockCondition: (
                    <span>
                      {operationsAttentionResolutionLabel(
                        item.resolution_condition,
                        locale,
                      )}{' '}
                      <span className="text-[var(--app-text-tertiary)]">
                        {labels.viewingDoesNotClear}
                      </span>
                    </span>
                  ),
                  nextAction: (
                    <span className="flex flex-wrap items-center gap-2">
                      <span>
                        {operationsNextActionLabel(item.next_action, locale)}
                      </span>
                      {href !== '/operations' ? (
                        <a
                          className="font-semibold text-[var(--app-accent)] underline decoration-transparent underline-offset-2 hover:decoration-current"
                          href={href}
                        >
                          {labels.openEvidence}
                        </a>
                      ) : null}
                    </span>
                  ),
                  evidence: (
                    <span title={item.task_fingerprint}>
                      {formatEvidenceTime(item.evidence.observed_at, locale) ??
                        labels.noTimestamp}{' '}
                      · {item.task_fingerprint.slice(0, 14)}…
                      {item.task_fingerprint.slice(-8)}
                    </span>
                  ),
                } satisfies ExceptionItem;
              })}
            />
          </section>

          <details
            className="group min-w-0 border-y border-[var(--app-divider)] py-2"
            data-testid="operations-subsystem-register"
          >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
              <span>{labels.subsystemHealth}</span>
              <span className="flex items-center gap-2 font-mono text-xs font-normal tabular-nums text-[var(--app-text-tertiary)]">
                {projection.subsystems.length}
                <span aria-hidden="true" className="group-open:rotate-180">
                  ▾
                </span>
              </span>
            </summary>
            <div className="mt-3 min-w-0">
              <DataTable
                data={projection.subsystems}
                columns={subsystemColumns}
                caption={labels.subsystemHealth}
                emptyState={labels.attentionEmpty}
                getRowId={(row) => row.id}
                tableTestId="operations-subsystem-table"
                scrollTestId="operations-subsystem-scroll"
              />
            </div>
          </details>

          <section
            className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-4"
            aria-labelledby="operations-timeline-heading"
          >
            <div>
              <h2
                id="operations-timeline-heading"
                className="text-base font-semibold text-[var(--app-text)]"
              >
                {locale === 'zh'
                  ? '持久化证据时间线'
                  : 'Persisted evidence timeline'}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
                {labels.sourceBoundary}
              </p>
            </div>
            <EvidenceState
              kind="empty"
              title={
                locale === 'zh'
                  ? '暂无 canonical 历史事件'
                  : 'No canonical history events'
              }
              description={
                locale === 'zh'
                  ? '当前投影只包含子系统最新状态；不会把它改写成不可变历史。'
                  : 'The current projection contains latest subsystem state only; it is not rewritten as immutable history.'
              }
            />
          </section>
        </>
      )}
    </section>
  );
}
