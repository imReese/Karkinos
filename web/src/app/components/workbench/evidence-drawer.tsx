import { useEffect, useId, useRef, type ReactNode } from 'react';

import { X } from 'lucide-react';

import { cn } from '../../../lib/utils/cn';

export function EvidenceDrawer({
  open,
  onClose,
  title,
  description,
  closeLabel,
  children,
  footer,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  closeLabel: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    const returnFocus = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      returnFocus?.focus();
    };
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[120]">
      <button
        type="button"
        className="absolute inset-0 h-full w-full bg-[color-mix(in_srgb,var(--app-bg)_72%,transparent)]"
        aria-label={closeLabel}
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        className={cn(
          'absolute inset-y-0 right-0 flex w-[min(92vw,560px)] flex-col border-l border-[var(--app-border)] bg-[var(--app-surface-overlay)] shadow-[var(--app-shadow-overlay)]',
          className,
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-[var(--app-divider)] px-4 py-3">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="text-base font-semibold text-[var(--app-text)]"
            >
              {title}
            </h2>
            {description ? (
              <p
                id={descriptionId}
                className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]"
              >
                {description}
              </p>
            ) : null}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="app-button-secondary inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] p-0"
            aria-label={closeLabel}
            onClick={onClose}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {children}
        </div>
        {footer ? (
          <footer className="border-t border-[var(--app-divider)] px-4 py-3">
            {footer}
          </footer>
        ) : null}
      </aside>
    </div>
  );
}
