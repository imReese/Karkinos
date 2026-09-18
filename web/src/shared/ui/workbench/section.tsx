import type { ReactNode } from 'react';

import { cn } from '../../utils/cn';

export function SectionHeader({
  title,
  description,
  meta,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      data-workbench-primitive="section-header"
      className={cn(
        'app-section-header flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between',
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {title}
          </h2>
          {meta !== undefined && meta !== null ? (
            <span className="app-type-label tabular-nums text-[var(--app-text-tertiary)]">
              {meta}
            </span>
          ) : null}
        </div>
        {description ? (
          <p className="app-type-compact mt-1 max-w-3xl text-[var(--app-text-secondary)]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {actions}
        </div>
      ) : null}
    </header>
  );
}
