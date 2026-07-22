import { useState, type ReactNode } from 'react';

import { Check, Copy } from 'lucide-react';

import { EvidenceDrawer } from './evidence-drawer';

export type EvidenceIdentityField = {
  label: ReactNode;
  value: ReactNode;
  copyValue?: string;
  mono?: boolean;
};

function evidenceIdentityCopyValue(field: EvidenceIdentityField) {
  if (field.copyValue !== undefined) {
    return field.copyValue;
  }
  return typeof field.value === 'string' || typeof field.value === 'number'
    ? String(field.value)
    : null;
}

export function EvidenceIdentityDisclosure({
  triggerLabel,
  title,
  description,
  closeLabel,
  copyLabel,
  copiedLabel,
  fields,
  className,
}: {
  triggerLabel: string;
  title: ReactNode;
  description?: ReactNode;
  closeLabel: string;
  copyLabel: (fieldLabel: string) => string;
  copiedLabel: (fieldLabel: string) => string;
  fields: ReadonlyArray<EvidenceIdentityField>;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [copiedField, setCopiedField] = useState<number | null>(null);

  const close = () => {
    setOpen(false);
    setCopiedField(null);
  };

  const copyField = async (field: EvidenceIdentityField, index: number) => {
    const value = evidenceIdentityCopyValue(field);
    if (value === null || !navigator.clipboard) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setCopiedField(index);
    } catch {
      setCopiedField(null);
    }
  };

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
        onClose={close}
        title={title}
        description={description}
        closeLabel={closeLabel}
      >
        <dl className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {fields.map((field, index) => {
            const fieldLabel =
              typeof field.label === 'string'
                ? field.label
                : `Field ${index + 1}`;
            const copyValue = evidenceIdentityCopyValue(field);
            const copied = copiedField === index;
            return (
              <div
                key={`${String(field.label)}-${index}`}
                className="grid min-w-0 gap-1 py-3 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)] sm:gap-4"
              >
                <dt className="text-xs font-medium text-[var(--app-text-secondary)]">
                  {field.label}
                </dt>
                <dd className="flex min-w-0 items-start justify-between gap-2">
                  <span
                    className={`min-w-0 break-all text-xs leading-5 text-[var(--app-text)] ${field.mono ? 'font-mono tabular-nums' : ''}`}
                  >
                    {field.value}
                  </span>
                  {copyValue !== null ? (
                    <button
                      type="button"
                      className="app-button-ghost inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--app-radius-control)] p-0 text-[var(--app-text-secondary)] sm:h-8 sm:w-8"
                      aria-label={
                        copied ? copiedLabel(fieldLabel) : copyLabel(fieldLabel)
                      }
                      title={
                        copied ? copiedLabel(fieldLabel) : copyLabel(fieldLabel)
                      }
                      onClick={() => void copyField(field, index)}
                    >
                      {copied ? (
                        <Check aria-hidden="true" className="h-3.5 w-3.5" />
                      ) : (
                        <Copy aria-hidden="true" className="h-3.5 w-3.5" />
                      )}
                    </button>
                  ) : null}
                </dd>
              </div>
            );
          })}
        </dl>
      </EvidenceDrawer>
    </>
  );
}
