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
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {title}
          </h2>
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
  badge,
  children,
  variant = 'card',
}: {
  testId: string;
  title: string;
  detail: string;
  badge?: ReactNode;
  children: ReactNode;
  variant?: 'card' | 'section';
}) {
  if (variant === 'section') {
    return (
      <section
        className="min-w-0 space-y-4 pt-2"
        id={testId}
        data-testid={testId}
      >
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--app-divider)] pb-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="app-type-section-title text-[var(--app-text)]">
                {title}
              </h2>
              {badge ? <span className="shrink-0">{badge}</span> : null}
            </div>
            <p className="app-muted mt-1 text-xs leading-5">{detail}</p>
          </div>
        </div>
        <div className="space-y-4">{children}</div>
      </section>
    );
  }

  return (
    <section
      className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-4 sm:p-5"
      id={testId}
      data-testid={testId}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--app-divider)] pb-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--app-text)]">
              {title}
            </h3>
            {badge ? <span className="shrink-0">{badge}</span> : null}
          </div>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {detail}
          </p>
        </div>
      </div>
      <div className="space-y-4 pt-4">{children}</div>
    </section>
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

export function PreferenceGroup({
  label,
  helper,
  options,
  value,
  onChange,
}: {
  label: string;
  helper?: string;
  options: Array<[string, string]>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-2 border-b border-[var(--app-divider)] last:border-b-0">
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-semibold text-[var(--app-text)]">
          {label}
        </span>
        {helper ? (
          <span className="app-muted app-type-micro">({helper})</span>
        ) : null}
      </div>
      <div className="inline-flex items-center rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-0.5">
        {options.map(([optionValue, optionLabel]) => (
          <button
            key={optionValue}
            type="button"
            className={`rounded-[calc(var(--app-radius-control)-2px)] px-2.5 py-0.5 text-xs font-medium transition-all ${
              value === optionValue
                ? 'border border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent-text)] shadow-xs'
                : 'border border-transparent text-[var(--app-soft)] hover:text-[var(--app-text)]'
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
      className={`rounded-[var(--app-radius-control)] border px-3.5 py-2.5 ${getStatusToneClasses(tone)}`}
    >
      <div className="text-xs font-semibold">{title}</div>
      <div className="mt-0.5 text-xs leading-5 opacity-90">{detail}</div>
    </div>
  );
}

export type BeaconTone = 'success' | 'warning' | 'danger' | 'neutral';

export function BeaconDot({
  tone = 'success',
  ariaLabel,
  pulse = true,
}: {
  tone?: BeaconTone;
  ariaLabel?: string;
  pulse?: boolean;
}) {
  const colorMap: Record<BeaconTone, { bg: string; ping: string }> = {
    success: {
      bg: 'bg-[var(--app-success-indicator)]',
      ping: 'bg-[var(--app-success-indicator)]',
    },
    warning: {
      bg: 'bg-[var(--app-warning-indicator)]',
      ping: 'bg-[var(--app-warning-indicator)]',
    },
    danger: {
      bg: 'bg-[var(--app-danger-indicator)]',
      ping: 'bg-[var(--app-danger-indicator)]',
    },
    neutral: {
      bg: 'bg-[var(--app-muted)]',
      ping: 'bg-[var(--app-muted)]',
    },
  };
  const colors = colorMap[tone] || colorMap.neutral;

  return (
    <span
      className="app-beacon-dot"
      aria-label={ariaLabel}
      title={ariaLabel}
      role="status"
    >
      {pulse ? (
        <span
          className={`app-beacon-dot-ping ${colors.ping}`}
          aria-hidden="true"
        />
      ) : null}
      <span className={`app-beacon-dot-core ${colors.bg}`} aria-hidden="true" />
    </span>
  );
}
