import { useState, type ReactNode } from 'react';

import { EvidenceDrawer } from './evidence-drawer';

export type EvidenceIdentityField = {
  label: ReactNode;
  value: ReactNode;
  mono?: boolean;
};

export function EvidenceIdentityDisclosure({
  triggerLabel,
  title,
  description,
  closeLabel,
  fields,
  className,
}: {
  triggerLabel: string;
  title: ReactNode;
  description?: ReactNode;
  closeLabel: string;
  fields: ReadonlyArray<EvidenceIdentityField>;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className={
          className ??
          'app-button-secondary inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold'
        }
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {triggerLabel}
      </button>
      <EvidenceDrawer
        open={open}
        onClose={() => setOpen(false)}
        title={title}
        description={description}
        closeLabel={closeLabel}
      >
        <dl className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {fields.map((field, index) => (
            <div
              key={`${String(field.label)}-${index}`}
              className="grid min-w-0 gap-1 py-3 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)] sm:gap-4"
            >
              <dt className="text-xs font-medium text-[var(--app-text-secondary)]">
                {field.label}
              </dt>
              <dd
                className={`min-w-0 break-all text-xs leading-5 text-[var(--app-text)] ${field.mono ? 'font-mono tabular-nums' : ''}`}
              >
                {field.value}
              </dd>
            </div>
          ))}
        </dl>
      </EvidenceDrawer>
    </>
  );
}
