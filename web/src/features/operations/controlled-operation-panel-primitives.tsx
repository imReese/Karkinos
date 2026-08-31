export type OperationsLocale = 'en' | 'zh';

export function mutationError(error: unknown) {
  return error instanceof Error
    ? error.message
    : String(error || 'unknown_error');
}

export function shortenedIdentity(value: string) {
  if (value.length <= 20) {
    return value || '—';
  }
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

export function EvidenceMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] px-3 py-2">
      <div className="app-muted app-type-micro">{label}</div>
      <div
        className="mt-1 min-w-0 truncate font-mono text-xs text-[var(--app-text)]"
        title={value}
      >
        {value || '—'}
      </div>
    </div>
  );
}
