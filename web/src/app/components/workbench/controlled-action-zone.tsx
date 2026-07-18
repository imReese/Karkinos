import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';

export function ControlledActionZone({
  title,
  description,
  evidence,
  children,
  className,
}: {
  title: ReactNode;
  description: ReactNode;
  evidence?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        'rounded-[var(--app-radius-surface)] border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-3 py-3',
        className,
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--app-danger-text)]">
            {title}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {description}
          </p>
          {evidence ? (
            <div className="mt-1 font-mono text-[11px] text-[var(--app-text-tertiary)]">
              {evidence}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {children}
        </div>
      </div>
    </section>
  );
}
