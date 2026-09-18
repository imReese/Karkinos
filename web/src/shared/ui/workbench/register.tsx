import type { ReactNode } from 'react';

import { cn } from '../../utils/cn';

export type RegisterTone =
  'neutral' | 'pnl-positive' | 'pnl-negative' | 'warning' | 'danger';

const REGISTER_TONE_CLASSES: Record<RegisterTone, string> = {
  neutral: 'text-[var(--app-text)]',
  'pnl-positive': 'text-[var(--app-pnl-positive)]',
  'pnl-negative': 'text-[var(--app-pnl-negative)]',
  warning: 'text-[var(--app-warning-text)]',
  danger: 'text-[var(--app-danger-text)]',
};

export function Register({
  ariaLabel,
  children,
  className,
}: {
  ariaLabel: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <dl
      aria-label={ariaLabel}
      data-workbench-primitive="register"
      className={cn(
        'app-register min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]',
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function RegisterRow({
  label,
  value,
  detail,
  tone = 'neutral',
  mono = false,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: RegisterTone;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div
      data-workbench-primitive="register-row"
      className={cn(
        'app-register-row grid min-w-0 gap-1 py-2.5 sm:grid-cols-[minmax(9rem,0.5fr)_minmax(0,1fr)] sm:items-baseline sm:gap-x-4',
        className,
      )}
    >
      <dt className="app-type-label text-[var(--app-text-secondary)]">
        {label}
      </dt>
      <dd className="min-w-0">
        <div
          className={cn(
            'app-type-compact font-medium tabular-nums [overflow-wrap:anywhere]',
            mono && 'font-mono',
            REGISTER_TONE_CLASSES[tone],
          )}
        >
          {value}
        </div>
        {detail ? (
          <div className="app-type-micro mt-1 text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
            {detail}
          </div>
        ) : null}
      </dd>
    </div>
  );
}
