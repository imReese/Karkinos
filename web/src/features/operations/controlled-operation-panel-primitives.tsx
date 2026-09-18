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
    <div className="grid min-w-0 gap-1 border-b border-[var(--app-divider)] px-1 py-2.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:items-baseline sm:gap-3">
      <div className="app-muted app-type-micro">{label}</div>
      <div
        className="min-w-0 truncate font-mono text-xs text-[var(--app-text)]"
        title={value}
      >
        {value || '—'}
      </div>
    </div>
  );
}
