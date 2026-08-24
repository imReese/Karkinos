import { useCopy } from '../../../app/copy';
import { MetricStrip } from '../../../shared/ui/workbench';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { AllocationGroup } from '../api';

export function AllocationGroupsCard({
  groups,
}: {
  groups: AllocationGroup[];
}) {
  const copy = useCopy();

  if (groups.length === 0) {
    return (
      <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
        {copy.portfolio.allocationGroups.empty}
      </div>
    );
  }

  return (
    <section className="min-w-0">
      <h3 className="app-type-subsection-title mb-2 text-[var(--app-text)]">
        {copy.portfolio.allocationGroups.title}
      </h3>
      <MetricStrip
        ariaLabel={copy.portfolio.allocationGroups.title}
        items={groups.map((group) => ({
          id: group.asset_class,
          label: formatAssetClassLabel(group.name, copy.common),
          value: formatPercent(group.weight),
          detail: `${formatCurrency(group.value)} · ${group.items.length}`,
        }))}
        className="sm:grid-flow-row sm:grid-cols-2 xl:grid-flow-col xl:grid-cols-none"
      />
    </section>
  );
}
