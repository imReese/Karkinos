import { useMemo, useState } from 'react';

import type { ColumnDef } from '@tanstack/react-table';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { StatusBadge } from '../../../shared/ui/workbench';
import { type OperationsSubsystem, useOperationsTodayQuery } from '../api';
import {
  operationsNextActionLabel,
  operationsSubsystemLabel,
  operationsTargetHref,
} from '../presentation';
import {
  formatEvidenceTime,
  operationsProjectionIsSafe,
  statusTone,
} from './operations-page-model';

export type OperationsPageLabels = ReturnType<typeof useCopy>['operationsPage'];

export function useOperationsPageController() {
  const copy = useCopy();
  const labels = copy.operationsPage;
  const { locale } = usePreferences();
  const operations = useOperationsTodayQuery();
  const [selectedAttentionFingerprint, setSelectedAttentionFingerprint] =
    useState<string | null>(null);
  const projection = operations.data;
  const safeProjection = operationsProjectionIsSafe(projection)
    ? projection
    : null;
  const projectionIsSafe = safeProjection !== null;
  const pilotReadiness = safeProjection
    ? safeProjection.controlled_per_order_pilot_readiness
    : undefined;
  const attentionItems = safeProjection?.attention_items ?? [];
  const selectedAttention =
    attentionItems.find(
      (item) => item.task_fingerprint === selectedAttentionFingerprint,
    ) ?? null;
  const subsystemColumns = useMemo<ColumnDef<OperationsSubsystem, unknown>[]>(
    () => [
      {
        accessorKey: 'id',
        header: labels.subsystem,
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
          <span className="block min-w-40 max-w-56 whitespace-normal leading-5">
            <span className="block text-[var(--app-text)]">
              {formatPublicStatus(row.original.detail_status, locale)}
            </span>
            <span className="mt-1 block font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
              {labels.observedAt}:{' '}
              {formatEvidenceTime(row.original.last_run_at, locale) ??
                labels.noTimestamp}
            </span>
          </span>
        ),
      },
      {
        accessorKey: 'next_action',
        header: labels.nextAction,
        cell: ({ row }) => (
          <span className="block min-w-48 max-w-80 whitespace-normal leading-5">
            <span className="block text-[var(--app-text)]">
              {operationsNextActionLabel(row.original.next_action, locale)}
            </span>
            <span className="mt-1 block text-xs text-[var(--app-text-tertiary)]">
              {labels.limitations}:{' '}
              {row.original.limitations.length > 0
                ? row.original.limitations.join(' · ')
                : labels.noLimitations}
            </span>
          </span>
        ),
      },
    ],
    [labels, locale],
  );

  return {
    attentionItems,
    copy,
    labels,
    locale,
    operations,
    pilotReadiness,
    projection,
    projectionIsSafe,
    safeProjection,
    selectedAttention,
    setSelectedAttentionFingerprint,
    subsystemColumns,
  };
}

export type OperationsPageController = ReturnType<
  typeof useOperationsPageController
>;
