import { StatusBadge } from '../../../shared/ui/workbench';
import type { OperationsPageLabels } from './use-operations-page-controller';

export function OperationsModeBanner({
  labels,
}: {
  labels: OperationsPageLabels;
}) {
  return (
    <div
      className="app-operations-mode-banner rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-3.5 sm:p-4"
      data-testid="operations-mode-banner"
    >
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex h-2 w-2 shrink-0 rounded-full bg-[var(--app-accent)]" />
          <span className="text-sm font-semibold text-[var(--app-text)]">
            {labels.modeResearch}
          </span>
          <StatusBadge tone="success">{labels.safetyLockActive}</StatusBadge>
        </div>
      </div>
      <details className="mt-2">
        <summary className="flex min-h-11 cursor-pointer items-center text-xs text-[var(--app-text-secondary)]">
          {labels.safetyPillCapital} · {labels.safetyPillResearch}
        </summary>
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 text-[var(--app-text-secondary)]">
              {labels.safetyPillCapital}
            </span>
            <span className="rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 text-[var(--app-text-secondary)]">
              {labels.safetyPillResearch}
            </span>
            <span className="rounded-full border border-[var(--app-divider)] bg-[var(--app-surface)] px-2.5 py-0.5 text-[var(--app-text-tertiary)]">
              {labels.safetyPillSnapshot}
            </span>
          </div>
          <p className="text-xs leading-relaxed text-[var(--app-text-secondary)]">
            {labels.modeResearchDesc}
          </p>
        </div>
      </details>
    </div>
  );
}
