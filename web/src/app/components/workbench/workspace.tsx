import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';

export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export type MetricTone =
  'neutral' | 'pnl-positive' | 'pnl-negative' | 'warning' | 'danger';

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
  danger: 'text-[var(--app-danger-text)]',
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
        'app-workspace-header flex min-w-0 flex-col gap-3 border-b border-[var(--app-divider)] pb-4 sm:flex-row sm:items-start sm:justify-between',
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <div className="app-workspace-eyebrow mb-1.5">{eyebrow}</div>
        ) : null}
        <h1 className="app-workspace-title">{title}</h1>
        {description ? (
          <p className="app-workspace-description mt-1 max-w-4xl">
            {description}
          </p>
        ) : null}
        {context ? (
          <div className="app-workspace-context mt-2 max-w-full overflow-hidden text-ellipsis [overflow-wrap:anywhere]">
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
          <dt className="app-type-label truncate font-medium text-[var(--app-text-secondary)]">
            {item.label}
          </dt>
          <dd
            className={cn(
              'mt-0.5 truncate text-lg leading-6 font-semibold tracking-[-0.015em] tabular-nums',
              METRIC_TONE_CLASSES[item.tone ?? 'neutral'],
            )}
          >
            {item.value}
          </dd>
          {item.detail ? (
            <div className="app-type-label mt-0.5 truncate text-[var(--app-text-tertiary)]">
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
        <div className="app-type-compact shrink-0 text-[var(--app-text-tertiary)]">
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
        'app-type-label inline-flex min-h-6 items-center rounded-[var(--app-radius-control)] border px-1.5 py-0.5 font-semibold',
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
  statusLabel,
  title,
  description,
  evidence,
  action,
  className,
}: {
  kind: EvidenceStateKind;
  statusLabel?: ReactNode;
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
          {statusLabel ? (
            <StatusBadge tone={EVIDENCE_STATE_TONES[kind]}>
              {statusLabel}
            </StatusBadge>
          ) : null}
          <h2 className="app-type-subsection-title text-[var(--app-text)]">
            {title}
          </h2>
        </div>
        {description ? (
          <div className="app-type-body mt-1 text-[var(--app-text-secondary)]">
            {description}
          </div>
        ) : null}
        {evidence ? (
          <div className="app-type-micro mt-1 font-mono text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
            {evidence}
          </div>
        ) : null}
        {kind === 'loading' ? (
          <span
            aria-hidden="true"
            className="mt-2 block h-0.5 w-24 overflow-hidden rounded-full bg-[var(--app-info-bg)]"
            data-testid="evidence-loading-indicator"
          >
            <span className="block h-full w-2/3 rounded-full bg-[var(--app-info-indicator)] motion-safe:animate-pulse" />
          </span>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </section>
  );
}

export function EvidenceLoadingLayout({
  title,
  description,
  metricCount = 4,
  rowCount = 3,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  metricCount?: number;
  rowCount?: number;
  className?: string;
}) {
  return (
    <div
      className={cn('min-w-0 space-y-4', className)}
      data-workbench-primitive="evidence-loading-layout"
    >
      <EvidenceState kind="loading" title={title} description={description} />
      <div
        aria-hidden="true"
        className="grid min-w-0 grid-cols-2 divide-x divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] lg:grid-cols-4 lg:divide-y-0"
        data-testid="evidence-loading-metrics"
      >
        {Array.from({ length: metricCount }, (_, index) => (
          <div key={index} className="min-w-0 px-3 py-3">
            <span className="block h-2 w-16 rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
            <span className="mt-2 block h-4 w-24 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
          </div>
        ))}
      </div>
      <div
        aria-hidden="true"
        className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
        data-testid="evidence-loading-rows"
      >
        {Array.from({ length: rowCount }, (_, index) => (
          <div
            key={index}
            className="grid min-w-0 gap-3 px-3 py-3 sm:grid-cols-[minmax(9rem,0.55fr)_minmax(0,1fr)]"
          >
            <span className="block h-3 w-28 max-w-full rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
            <span className="block h-3 w-full max-w-md rounded-full bg-[var(--app-surface-overlay)] motion-safe:animate-pulse" />
          </div>
        ))}
      </div>
    </div>
  );
}
