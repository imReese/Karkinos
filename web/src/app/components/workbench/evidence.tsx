import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';
import { StatusBadge, type StatusTone } from './workspace';

export type ExceptionItem = {
  id: string;
  severity: Exclude<StatusTone, 'success'>;
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
  className,
}: {
  items: ReadonlyArray<ExceptionItem>;
  ariaLabel: string;
  emptyState: ReactNode;
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
    <ul aria-label={ariaLabel} className={cn('grid gap-2', className)}>
      {items.map((item) => (
        <li
          key={item.id}
          className="rounded-[var(--app-radius-surface)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2.5"
        >
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={item.severity}>{item.severity}</StatusBadge>
            <h3 className="text-sm font-semibold text-[var(--app-text)]">
              {item.title}
            </h3>
          </div>
          <dl className="mt-2 grid gap-1.5 text-xs sm:grid-cols-2">
            <EvidenceRow label="Reason">{item.reason}</EvidenceRow>
            {item.unblockCondition ? (
              <EvidenceRow label="Unblock condition">
                {item.unblockCondition}
              </EvidenceRow>
            ) : null}
            {item.nextAction ? (
              <EvidenceRow label="Safe next step">
                {item.nextAction}
              </EvidenceRow>
            ) : null}
            {item.evidence ? (
              <EvidenceRow label="Evidence">{item.evidence}</EvidenceRow>
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
      <dt className="font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd className="mt-0.5 text-[var(--app-text-secondary)]">{children}</dd>
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
      className={cn(
        'max-w-full overflow-x-auto rounded-[var(--app-radius-surface)] border border-[var(--app-border)]',
        className,
      )}
    >
      <table className="w-full min-w-[680px] border-collapse text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
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
            <tr key={item.id}>
              <th scope="row" className="px-3 py-2.5 font-semibold">
                {item.gate}
              </th>
              <td className="px-3 py-2.5">
                <StatusBadge tone={GATE_TONES[item.state]}>
                  {item.state}
                </StatusBadge>
              </td>
              <td className="px-3 py-2.5 text-[var(--app-text-secondary)]">
                {item.reason}
              </td>
              <td className="px-3 py-2.5 text-[var(--app-text-secondary)]">
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
    <ol aria-label={ariaLabel} className={cn('relative ml-2', className)}>
      {items.map((item, index) => (
        <li
          key={item.id}
          className="relative border-l border-[var(--app-divider)] pb-4 pl-5 last:border-transparent last:pb-0"
        >
          <span
            className="absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full border-2 border-[var(--app-surface-raised)] bg-[var(--app-info-indicator)]"
            aria-hidden="true"
          />
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <time className="font-mono text-[11px] tabular-nums text-[var(--app-text-tertiary)]">
              {item.timestamp}
            </time>
            <StatusBadge tone={item.tone ?? 'neutral'}>{index + 1}</StatusBadge>
            <h3 className="text-sm font-semibold text-[var(--app-text)]">
              {item.title}
            </h3>
          </div>
          {item.description ? (
            <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
              {item.description}
            </p>
          ) : null}
          {item.evidence ? (
            <div className="mt-1 font-mono text-[11px] text-[var(--app-text-tertiary)]">
              {item.evidence}
            </div>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
