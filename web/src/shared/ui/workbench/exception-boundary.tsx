import type { ReactNode } from 'react';

import { cn } from '../../utils/cn';
import type { StatusTone } from './workspace';

const BOUNDARY_CLASSES: Record<Exclude<StatusTone, 'success'>, string> = {
  neutral:
    'border-l-[var(--app-text-tertiary)] bg-transparent text-[var(--app-text)]',
  info: 'border-l-[var(--app-info-indicator)] bg-[var(--app-info-bg)] text-[var(--app-text)]',
  warning:
    'border-l-[var(--app-warning-indicator)] bg-[var(--app-warning-bg)] text-[var(--app-text)]',
  danger:
    'border-l-[var(--app-danger-indicator)] bg-[var(--app-danger-bg)] text-[var(--app-text)]',
};

export function ExceptionBoundary({
  tone = 'warning',
  title,
  description,
  actions,
  children,
  className,
}: {
  tone?: Exclude<StatusTone, 'success'>;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section
      data-workbench-primitive="exception-boundary"
      data-boundary-tone={tone}
      className={cn(
        'app-exception-boundary min-w-0 border-l-2 px-3 py-2.5',
        BOUNDARY_CLASSES[tone],
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="app-type-subsection-title">{title}</h3>
          {description ? (
            <p className="app-type-compact mt-1 text-[var(--app-text-secondary)]">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        ) : null}
      </div>
      {children ? <div className="mt-2">{children}</div> : null}
    </section>
  );
}
