import type { ReactNode } from 'react';

import { useMotionPresence } from '../../shared/motion';
import { ChevronDownIcon, RotateCwIcon } from './app-shell-icons';
import type {
  ToolbarStatusIndicator,
  ToolbarStatusTone,
} from './app-shell-status-model';

export const TOOLBAR_STATUS_COLORS: Readonly<
  Record<ToolbarStatusTone, string>
> = {
  success: 'var(--app-success-indicator)',
  warning: 'var(--app-warning-indicator)',
  danger: 'var(--app-danger-indicator)',
};

type StatusChipProps = {
  actionLabel?: string;
  expanded?: boolean;
  hoverHint?: string;
  indicator: ToolbarStatusIndicator;
  label: string;
  meta?: string;
  onClick: () => void;
  popup?: ReactNode;
  testId?: string;
  title?: string;
  tone: ToolbarStatusTone;
  value: string;
};

export function StatusChip({
  label,
  value,
  tone,
  indicator,
  onClick,
  actionLabel,
  hoverHint,
  title,
  meta,
  popup,
  expanded = false,
  testId,
}: StatusChipProps) {
  const popupPresence = useMotionPresence(Boolean(popup && expanded));

  return (
    <div className="app-status-chip group relative inline-flex h-7 min-w-0 shrink-0 border-r border-[var(--app-divider)] pr-1">
      <button
        type="button"
        data-testid={testId}
        aria-label={`${actionLabel ? actionLabel : label}: ${value}${meta ? ` · ${meta}` : ''}`}
        aria-expanded={popup ? expanded : undefined}
        aria-haspopup={popup ? 'dialog' : undefined}
        title={title ?? hoverHint}
        onClick={onClick}
        className={`inline-flex h-full min-w-0 items-center overflow-hidden whitespace-nowrap rounded-[var(--app-radius-control)] border border-transparent bg-transparent px-1 text-xs text-[var(--app-text-secondary)] transition-colors hover:bg-[var(--app-surface-overlay)] hover:text-[var(--app-text)] ${
          expanded
            ? 'bg-[var(--app-surface-overlay)] text-[var(--app-text)]'
            : ''
        }`}
      >
        <span className="app-status-chip-label app-type-micro inline-flex h-full shrink-0 items-center px-1.5 font-semibold uppercase text-[var(--app-text-tertiary)]">
          {label}
        </span>
        <span className="grid h-full min-w-0 grid-cols-[12px_minmax(0,auto)_auto_12px] items-center gap-1 px-1 tabular-nums">
          <span className="relative col-start-1 flex h-3.5 w-3.5 items-center justify-center">
            {indicator === 'syncing' ? (
              <RotateCwIcon
                className="h-3 w-3 animate-spin"
                color={TOOLBAR_STATUS_COLORS.warning}
                data-testid={testId ? `${testId}-indicator` : undefined}
              />
            ) : (
              <span
                className="absolute inset-[2px] rounded-full"
                style={{ backgroundColor: TOOLBAR_STATUS_COLORS[tone] }}
                aria-hidden="true"
                data-testid={testId ? `${testId}-indicator` : undefined}
              />
            )}
          </span>
          <span
            className="col-start-2 min-w-0 max-w-28 truncate font-semibold text-[var(--app-text)]"
            data-status-chip-part="value"
          >
            {value}
          </span>
          {meta ? (
            <span
              className="app-type-micro col-start-3 shrink-0 font-mono font-medium text-[var(--app-text-secondary)]"
              data-status-chip-part="meta"
            >
              {meta}
            </span>
          ) : null}
          <ChevronDownIcon
            className={`col-start-4 h-3 w-3 shrink-0 text-[var(--app-text-tertiary)] transition-transform ${expanded ? 'rotate-180' : ''}`}
            data-status-chip-part="chevron"
            aria-hidden="true"
          />
        </span>
      </button>
      {hoverHint && !expanded ? (
        <div className="app-status-tooltip pointer-events-none absolute left-1/2 top-[calc(100%+6px)] z-[75] -translate-x-1/2 rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] px-2.5 py-1.5 text-xs text-[var(--app-text)] opacity-0 shadow-[var(--app-shadow-overlay)] group-hover:opacity-100 group-focus-within:opacity-100">
          {hoverHint}
        </div>
      ) : null}
      {popup && popupPresence.mounted ? (
        <div
          className="app-status-popover-root absolute left-0 top-[calc(100%+8px)] z-[90]"
          data-popup-placement="bottom"
          data-motion-state={popupPresence.state}
          aria-hidden={popupPresence.state === 'closing' ? true : undefined}
          inert={popupPresence.state === 'closing'}
        >
          {popup}
        </div>
      ) : null}
    </div>
  );
}

export function StatusPopover({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: string }>;
}) {
  return (
    <div
      className="min-w-[200px] rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3 shadow-[var(--app-shadow-overlay)]"
      role="dialog"
      aria-label={title}
    >
      <div className="app-type-label mb-2 font-semibold text-[var(--app-text)]">
        {title}
      </div>
      <div className="grid gap-2">
        {rows.map((row) => (
          <div
            key={`${row.label}-${row.value}`}
            className="app-type-label flex items-center justify-between gap-4"
          >
            <span className="app-type-micro font-medium text-[var(--app-text-tertiary)]">
              {row.label}
            </span>
            <span className="tabular-nums font-medium text-[var(--app-text)]">
              {row.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
