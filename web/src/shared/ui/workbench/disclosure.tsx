import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';

import { cn } from '../../utils/cn';

export function Disclosure({
  title,
  meta,
  children,
  defaultOpen = false,
  className,
  testId,
}: {
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  testId?: string;
}) {
  return (
    <details
      open={defaultOpen ? true : undefined}
      data-testid={testId}
      data-workbench-primitive="disclosure"
      className={cn(
        'app-disclosure group min-w-0 border-y border-[var(--app-divider)]',
        className,
      )}
    >
      <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="app-type-subsection-title min-w-0 text-[var(--app-text)]">
          {title}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {meta ? (
            <span className="app-type-label text-[var(--app-text-tertiary)]">
              {meta}
            </span>
          ) : null}
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 text-[var(--app-text-tertiary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="pb-3 pt-1">{children}</div>
    </details>
  );
}
