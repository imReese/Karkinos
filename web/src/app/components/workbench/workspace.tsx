import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export type MetricTone =
  'neutral' | 'pnl-positive' | 'pnl-negative' | 'warning';

const STATUS_TONE_CLASSES: Record<StatusTone, string> = {
  neutral:
    'border-[var(--app-divider)] bg-transparent text-[var(--app-text-secondary)]',
  info: 'border-[var(--app-info-border)] bg-[var(--app-info-bg)] text-[var(--app-info-text)]',
  success:
    'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]',
  warning:
    'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]',
  danger:
    'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger-text)]',
};

const METRIC_TONE_CLASSES: Record<MetricTone, string> = {
  neutral: 'text-[var(--app-text)]',
  'pnl-positive': 'text-[var(--app-pnl-positive)]',
  'pnl-negative': 'text-[var(--app-pnl-negative)]',
  warning: 'text-[var(--app-warning-text)]',
};

export function WorkspaceHeader({
  eyebrow,
  title,
  description,
  context,
  actions,
  className,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  context?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      data-workbench-primitive="workspace-header"
      className={cn(
        'app-workspace-header flex min-w-0 flex-col gap-2.5 border-b border-[var(--app-divider)] pb-3 sm:flex-row sm:items-start sm:justify-between',
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
            {eyebrow}
          </div>
        ) : null}
        <h1 className="text-[1.375rem] leading-7 font-semibold tracking-[-0.025em] text-[var(--app-text)] sm:text-2xl sm:leading-8">
          {title}
        </h1>
        {description ? (
          <p className="mt-0.5 max-w-4xl text-[13px] leading-5 text-[var(--app-text-secondary)]">
            {description}
          </p>
        ) : null}
        {context ? (
          <div className="mt-1.5 max-w-full overflow-hidden text-ellipsis text-[11px] leading-4 text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
            {context}
          </div>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {actions}
        </div>
      ) : null}
    </header>
  );
}

export type MetricStripItem = {
  id: string;
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: MetricTone;
};

export function MetricStrip({
  items,
  ariaLabel,
  className,
}: {
  items: ReadonlyArray<MetricStripItem>;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <dl
      aria-label={ariaLabel}
      data-workbench-primitive="metric-strip"
      className={cn(
        'app-metric-strip grid min-w-0 grid-cols-2 border-y border-[var(--app-divider)] bg-transparent sm:grid-flow-col sm:auto-cols-fr sm:grid-cols-none',
        className,
      )}
    >
      {items.map((item) => (
        <div
          key={item.id}
          className="app-metric-strip-item min-w-0 px-3 py-2.5"
        >
          <dt className="truncate text-[11px] leading-4 font-medium text-[var(--app-text-secondary)]">
            {item.label}
          </dt>
          <dd
            className={cn(
              'mt-0.5 truncate text-[17px] leading-[22px] font-semibold tracking-[-0.015em] tabular-nums',
              METRIC_TONE_CLASSES[item.tone ?? 'neutral'],
            )}
          >
            {item.value}
          </dd>
          {item.detail ? (
            <div className="mt-0.5 truncate text-[11px] leading-4 text-[var(--app-text-tertiary)]">
              {item.detail}
            </div>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

export function FilterBar({
  label,
  children,
  summary,
  className,
}: {
  label: string;
  children: ReactNode;
  summary?: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={label}
      data-workbench-primitive="filter-bar"
      className={cn(
        'app-filter-bar flex min-w-0 flex-col gap-2 border-y border-[var(--app-divider)] bg-transparent py-2 sm:flex-row sm:items-center sm:justify-between',
        className,
      )}
    >
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
        {children}
      </div>
      {summary ? (
        <div className="shrink-0 text-xs text-[var(--app-text-tertiary)]">
          {summary}
        </div>
      ) : null}
    </section>
  );
}

export function StatusBadge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode;
  tone?: StatusTone;
  className?: string;
}) {
  return (
    <span
      data-workbench-primitive="status-badge"
      className={cn(
        'inline-flex min-h-[22px] items-center rounded-[var(--app-radius-control)] border px-1.5 py-0.5 text-[11px] leading-4 font-semibold',
        STATUS_TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export type EvidenceStateKind =
  'loading' | 'empty' | 'missing' | 'stale' | 'partial' | 'error' | 'ready';

const EVIDENCE_STATE_TONES: Record<EvidenceStateKind, StatusTone> = {
  loading: 'info',
  empty: 'neutral',
  missing: 'danger',
  stale: 'warning',
  partial: 'warning',
  error: 'danger',
  ready: 'success',
};

export function EvidenceState({
  kind,
  title,
  description,
  evidence,
  action,
  className,
}: {
  kind: EvidenceStateKind;
  title: ReactNode;
  description?: ReactNode;
  evidence?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-live={kind === 'loading' ? 'polite' : undefined}
      aria-busy={kind === 'loading'}
      data-evidence-kind={kind}
      data-workbench-primitive="evidence-state"
      className={cn(
        'app-evidence-state flex min-w-0 flex-col gap-2 border-l-2 border-[var(--app-border)] bg-transparent px-3 py-2.5 sm:flex-row sm:items-start sm:justify-between',
        kind === 'missing' || kind === 'error'
          ? 'border-l-[var(--app-danger-indicator)]'
          : kind === 'stale' || kind === 'partial'
            ? 'border-l-[var(--app-warning-indicator)]'
            : kind === 'ready'
              ? 'border-l-[var(--app-success-indicator)]'
              : 'border-l-[var(--app-info-indicator)]',
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={EVIDENCE_STATE_TONES[kind]}>{kind}</StatusBadge>
          <h2 className="text-sm font-semibold text-[var(--app-text)]">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="mt-1 text-xs leading-[18px] text-[var(--app-text-secondary)]">
            {description}
          </p>
        ) : null}
        {evidence ? (
          <div className="mt-1 font-mono text-[11px] leading-4 text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
            {evidence}
          </div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </section>
  );
}
