import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';
import { StatusBadge, type StatusTone } from './workspace';

export type ExceptionItem = {
  id: string;
  severity: Exclude<StatusTone, 'success'>;
  statusLabel?: ReactNode;
  title: ReactNode;
  reason: ReactNode;
  unblockCondition?: ReactNode;
  nextAction?: ReactNode;
  evidence?: ReactNode;
};

export function ExceptionList({
  items,
  ariaLabel,
  emptyState,
  density = 'default',
  labels = {
    reason: 'Reason',
    unblockCondition: 'Unblock condition',
    nextAction: 'Safe next step',
    evidence: 'Evidence',
  },
  className,
}: {
  items: ReadonlyArray<ExceptionItem>;
  ariaLabel: string;
  emptyState: ReactNode;
  density?: 'default' | 'compact';
  labels?: {
    reason: string;
    unblockCondition: string;
    nextAction: string;
    evidence: string;
  };
  className?: string;
}) {
  if (items.length === 0) {
    return (
      <div
        role="status"
        className={cn(
          'border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]',
          className,
        )}
      >
        {emptyState}
      </div>
    );
  }

  return (
    <ul
      aria-label={ariaLabel}
      data-workbench-primitive="exception-list"
      data-density={density}
      className={cn(
        density === 'compact'
          ? 'divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]'
          : 'grid gap-2',
        className,
      )}
    >
      {items.map((item) => (
        <li
          key={item.id}
          data-severity={item.severity}
          className={cn(
            'app-exception-item px-3 py-2.5',
            density === 'compact'
              ? 'bg-transparent'
              : 'rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface)]',
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={item.severity}>
              {item.statusLabel ?? item.severity}
            </StatusBadge>
            <h3 className="app-type-subsection-title text-[var(--app-text)]">
              {item.title}
            </h3>
          </div>
          <dl
            className={cn(
              'app-type-compact grid sm:grid-cols-2',
              density === 'compact' ? 'mt-1.5 gap-x-3 gap-y-1' : 'mt-2 gap-1.5',
            )}
          >
            <EvidenceRow label={labels.reason}>{item.reason}</EvidenceRow>
            {item.unblockCondition ? (
              <EvidenceRow label={labels.unblockCondition}>
                {item.unblockCondition}
              </EvidenceRow>
            ) : null}
            {item.nextAction ? (
              <EvidenceRow label={labels.nextAction}>
                {item.nextAction}
              </EvidenceRow>
            ) : null}
            {item.evidence ? (
              <EvidenceRow label={labels.evidence}>{item.evidence}</EvidenceRow>
            ) : null}
          </dl>
        </li>
      ))}
    </ul>
  );
}

function EvidenceRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="app-type-label font-semibold text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd className="mt-0.5 text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
        {children}
      </dd>
    </div>
  );
}

export type GateState = 'pass' | 'warning' | 'block' | 'unknown';

const GATE_TONES: Record<GateState, StatusTone> = {
  pass: 'success',
  warning: 'warning',
  block: 'danger',
  unknown: 'neutral',
};

export type GateMatrixItem = {
  id: string;
  gate: ReactNode;
  state: GateState;
  stateLabel?: ReactNode;
  reason: ReactNode;
  evidence?: ReactNode;
  unblockCondition?: ReactNode;
};

export function GateMatrix({
  items,
  caption,
  labels = {
    gate: 'Gate',
    state: 'State',
    reason: 'Reason',
    evidence: 'Evidence / unblock',
  },
  className,
}: {
  items: ReadonlyArray<GateMatrixItem>;
  caption: string;
  labels?: {
    gate: string;
    state: string;
    reason: string;
    evidence: string;
  };
  className?: string;
}) {
  return (
    <div
      data-workbench-primitive="gate-matrix"
      className={cn(
        'app-gate-matrix max-w-full border-y border-[var(--app-divider)]',
        className,
      )}
    >
      <table
        className="app-type-compact w-full border-collapse text-left"
        data-mobile-layout="stacked"
        data-testid="gate-matrix-responsive-table"
      >
        <caption className="sr-only">{caption}</caption>
        <thead className="sr-only bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)] sm:not-sr-only sm:table-header-group">
          <tr>
            {[labels.gate, labels.state, labels.reason, labels.evidence].map(
              (label) => (
                <th
                  key={label}
                  scope="col"
                  className="border-b border-[var(--app-divider)] px-3 py-2 font-semibold"
                >
                  {label}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
          {items.map((item) => (
            <tr
              key={item.id}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 px-3 py-3 sm:table-row sm:px-0 sm:py-0"
              data-gate-id={item.id}
              data-gate-state={item.state}
            >
              <th
                scope="row"
                className="col-start-1 px-0 py-0 text-sm font-semibold sm:table-cell sm:px-3 sm:py-2.5 sm:text-[length:var(--app-font-size-compact)]"
              >
                {item.gate}
              </th>
              <td className="col-start-2 px-0 py-0 sm:table-cell sm:px-3 sm:py-2.5">
                <StatusBadge tone={GATE_TONES[item.state]}>
                  {item.stateLabel ?? item.state}
                </StatusBadge>
              </td>
              <td className="col-span-2 px-0 py-0 text-[var(--app-text-secondary)] sm:table-cell sm:px-3 sm:py-2.5">
                <span className="app-type-label mb-0.5 block font-semibold text-[var(--app-text-tertiary)] sm:hidden">
                  {labels.reason}
                </span>
                {item.reason}
              </td>
              <td className="col-span-2 px-0 py-0 text-[var(--app-text-secondary)] sm:table-cell sm:px-3 sm:py-2.5">
                <span className="app-type-label mb-0.5 block font-semibold text-[var(--app-text-tertiary)] sm:hidden">
                  {labels.evidence}
                </span>
                {item.evidence}
                {item.evidence && item.unblockCondition ? ' · ' : null}
                {item.unblockCondition}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export type TimelineItem = {
  id: string;
  timestamp: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  evidence?: ReactNode;
  tone?: StatusTone;
};

const TIMELINE_TONE_CLASSES: Record<StatusTone, string> = {
  neutral: 'bg-[var(--app-text-tertiary)]',
  info: 'bg-[var(--app-info-indicator)]',
  success: 'bg-[var(--app-success-indicator)]',
  warning: 'bg-[var(--app-warning-indicator)]',
  danger: 'bg-[var(--app-danger-indicator)]',
};

export function Timeline({
  items,
  ariaLabel,
  emptyState,
  className,
}: {
  items: ReadonlyArray<TimelineItem>;
  ariaLabel: string;
  emptyState: ReactNode;
  className?: string;
}) {
  if (items.length === 0) {
    return (
      <div
        className={cn('text-sm text-[var(--app-text-secondary)]', className)}
      >
        {emptyState}
      </div>
    );
  }

  return (
    <ol
      aria-label={ariaLabel}
      data-workbench-primitive="timeline"
      className={cn('relative ml-2', className)}
    >
      {items.map((item) => (
        <li
          key={item.id}
          className="relative border-l border-[var(--app-divider)] pb-4 pl-5 last:border-transparent last:pb-0"
        >
          <span
            className={cn(
              'absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full border-2 border-[var(--app-bg)]',
              TIMELINE_TONE_CLASSES[item.tone ?? 'info'],
            )}
            aria-hidden="true"
          />
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <time className="app-type-micro font-mono tabular-nums text-[var(--app-text-tertiary)]">
              {item.timestamp}
            </time>
            <h3 className="app-type-subsection-title text-[var(--app-text)]">
              {item.title}
            </h3>
          </div>
          {item.description ? (
            <p className="app-type-body mt-1 text-[var(--app-text-secondary)]">
              {item.description}
            </p>
          ) : null}
          {item.evidence ? (
            <div className="app-type-micro mt-1 font-mono text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
              {item.evidence}
            </div>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
