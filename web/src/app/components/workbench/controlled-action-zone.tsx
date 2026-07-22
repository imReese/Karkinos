import type { ReactNode } from 'react';

import { cn } from '../../../lib/utils/cn';

type ControlledActionTone = 'danger' | 'info';

const TONE_CLASSES: Record<
  ControlledActionTone,
  { container: string; title: string }
> = {
  danger: {
    container: 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)]',
    title: 'text-[var(--app-danger-text)]',
  },
  info: {
    container: 'border-[var(--app-info-border)] bg-[var(--app-info-bg)]',
    title: 'text-[var(--app-info-text)]',
  },
};

export function ControlledActionZone({
  title,
  description,
  evidence,
  children,
  tone = 'danger',
  layout = 'inline',
  className,
}: {
  title: ReactNode;
  description: ReactNode;
  evidence?: ReactNode;
  children: ReactNode;
  tone?: ControlledActionTone;
  layout?: 'inline' | 'stack';
  className?: string;
}) {
  return (
    <section
      data-workbench-primitive="controlled-action-zone"
      data-action-tone={tone}
      className={cn(
        'app-controlled-action-zone rounded-[var(--app-radius-surface)] border border-l-2 px-3 py-3',
        TONE_CLASSES[tone].container,
        className,
      )}
    >
      <div
        className={cn(
          'flex flex-col gap-3',
          layout === 'inline' &&
            'sm:flex-row sm:items-start sm:justify-between',
        )}
      >
        <div className="min-w-0">
          <h2 className={cn('text-sm font-semibold', TONE_CLASSES[tone].title)}>
            {title}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {description}
          </p>
          {evidence ? (
            <div className="mt-1 font-mono text-[11px] leading-4 text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
              {evidence}
            </div>
          ) : null}
        </div>
        <div
          className={cn(
            'flex flex-wrap items-center gap-2',
            layout === 'inline' && 'shrink-0',
          )}
        >
          {children}
        </div>
      </div>
    </section>
  );
}
