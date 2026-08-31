import type { ReactNode } from 'react';

import type { StatusTone } from './settings-page-model';

export function getStatusToneClasses(tone: StatusTone) {
  if (tone === 'success') {
    return 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]';
  }
  if (tone === 'warning') {
    return 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]';
  }
  if (tone === 'danger') {
    return 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger-text)]';
  }
  return 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] text-[var(--app-soft)]';
}

export function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function SettingsSection({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children: ReactNode;
}) {
  return (
    <section className="border-y border-[var(--app-divider)]">
      <div className="space-y-4 py-4 sm:py-5">
        <div>
          <div className="app-card-title text-lg">{title}</div>
          <p className="app-muted mt-2 text-sm leading-6">{detail}</p>
        </div>
        {children}
      </div>
    </section>
  );
}

export function SettingsDisclosure({
  testId,
  title,
  detail,
  children,
}: {
  testId: string;
  title: string;
  detail: string;
  children: ReactNode;
}) {
  return (
    <details
      className="min-w-0 border-y border-[var(--app-divider)]"
      id={testId}
      data-testid={testId}
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-start justify-between gap-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-[var(--app-text)]">
            {title}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {detail}
          </span>
        </span>
        <span
          aria-hidden="true"
          className="shrink-0 text-sm text-[var(--app-text-secondary)]"
        >
          +
        </span>
      </summary>
      <div className="space-y-4 py-4">{children}</div>
    </details>
  );
}

export function StatusMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: StatusTone;
}) {
  return (
    <div
      className={`rounded-[var(--app-radius-control)] border px-4 py-3 ${getStatusToneClasses(tone)}`}
      title={`${label}: ${value}`}
      aria-label={`${label}: ${value}`}
    >
      <div className="app-type-overline">{label}</div>
      <div className="mt-2 break-words font-mono text-sm font-semibold tabular-nums">
        {value}
      </div>
    </div>
  );
}

export function RegisterRow({
  label,
  legacyLabel,
  value,
  tone,
  ariaLabelPrefix = 'Register item',
}: {
  label: string;
  legacyLabel?: string;
  value: string | number;
  tone: StatusTone;
  ariaLabelPrefix?: string;
}) {
  return (
    <div
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-[var(--app-divider)] px-1 py-2.5 last:border-b-0"
      aria-label={`${ariaLabelPrefix}: ${label} ${value}`}
    >
      {legacyLabel ? (
        <span className="sr-only" aria-label={`${legacyLabel}: ${value}`} />
      ) : null}
      <div className="app-type-overline min-w-0 text-[var(--app-muted)]">
        {label}
      </div>
      <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 justify-self-end text-right">
        <span
          className={`h-2 w-2 rounded-full border ${getStatusToneClasses(tone)}`}
          aria-hidden="true"
        />
        <span className="min-w-0 font-mono text-sm font-semibold tabular-nums text-[var(--app-text)]">
          {value}
        </span>
      </div>
    </div>
  );
}

export function CapabilityRow({
  label,
  source,
  status,
  tone,
}: {
  label: string;
  source: string;
  status: string;
  tone: StatusTone;
}) {
  return (
    <div className="grid grid-cols-[minmax(10rem,1fr)_minmax(10rem,1fr)_8rem] items-center gap-3 py-3 text-sm">
      <div className="min-w-0 font-semibold text-[var(--app-text)]">
        {label}
      </div>
      <div className="min-w-0 truncate font-mono text-xs text-[var(--app-soft)]">
        {source}
      </div>
      <span
        className={`justify-self-start rounded-full border px-2.5 py-1 text-xs font-semibold ${getStatusToneClasses(
          tone,
        )}`}
      >
        {status}
      </span>
    </div>
  );
}

export function ManualTaskRow({
  label,
  href,
  actionLabel,
  checked,
  onChange,
}: {
  label: string;
  href: string;
  actionLabel: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center border-t border-[var(--app-divider)] first:border-t-0">
      <label className="flex min-h-[var(--app-touch-target)] min-w-0 cursor-pointer items-center gap-3 px-3 py-2">
        <input
          type="checkbox"
          className="h-5 w-5 shrink-0 accent-[var(--app-accent)]"
          checked={checked}
          aria-label={`Manual task: ${label}`}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="min-w-0 text-sm font-medium text-[var(--app-soft)]">
          {label}
        </span>
      </label>
      <a
        className="app-link inline-flex min-h-[var(--app-touch-target)] items-center px-3 py-2 text-xs font-semibold"
        href={href}
        target="_blank"
        rel="noreferrer"
      >
        {actionLabel}
      </a>
    </div>
  );
}

export function PreferenceGroup({
  label,
  helper,
  options,
  value,
  onChange,
}: {
  label: string;
  helper: string;
  options: Array<[string, string]>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold">{label}</div>
        <div className="app-muted text-xs">{helper}</div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map(([optionValue, optionLabel]) => (
          <button
            key={optionValue}
            type="button"
            className={`rounded-[var(--app-radius-control)] border px-3 py-2 text-sm font-semibold transition-colors ${
              value === optionValue
                ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent-text)]'
                : 'border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] text-[var(--app-soft)] hover:border-[color-mix(in_srgb,var(--app-border)_48%,transparent)]'
            }`}
            aria-pressed={value === optionValue}
            onClick={() => onChange(optionValue)}
          >
            {optionLabel}
          </button>
        ))}
      </div>
    </div>
  );
}

export function InlineNotice({
  tone,
  title,
  detail,
}: {
  tone: StatusTone;
  title: string;
  detail: string;
}) {
  return (
    <div
      className={`rounded-[var(--app-radius-control)] border px-4 py-3 ${getStatusToneClasses(tone)}`}
    >
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-1 text-xs leading-5">{detail}</div>
    </div>
  );
}
