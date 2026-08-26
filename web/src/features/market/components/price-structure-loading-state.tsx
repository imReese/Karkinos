import { EvidenceState } from '../../../shared/ui/workbench';
import { cn } from '../../../shared/utils/cn';

export function PriceStructureLoadingState({
  title,
  description,
  className,
  compact = false,
}: {
  title: string;
  description: string;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      aria-busy="true"
      className={cn('min-w-0', className)}
      data-testid="price-structure-loading-state"
    >
      <EvidenceState kind="loading" title={title} description={description} />
      <div
        aria-hidden="true"
        className="mt-3 border-y border-[var(--app-divider)] py-3"
        data-testid="price-structure-loading-chart"
      >
        <div className="flex min-w-0 items-center justify-between gap-3">
          <span className="block h-2 w-24 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
          <span className="flex shrink-0 gap-1.5">
            {Array.from({ length: compact ? 3 : 5 }, (_, index) => (
              <span
                className="block h-5 w-8 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]"
                key={index}
              />
            ))}
          </span>
        </div>
        <div
          className={cn(
            'mt-3 border-y border-[var(--app-divider)] bg-[linear-gradient(to_right,var(--app-divider)_1px,transparent_1px),linear-gradient(to_bottom,var(--app-divider)_1px,transparent_1px)] bg-[size:25%_100%,100%_25%] opacity-70',
            compact ? 'h-28 sm:h-36' : 'h-44 sm:h-56 xl:h-64',
          )}
        />
      </div>
    </div>
  );
}
