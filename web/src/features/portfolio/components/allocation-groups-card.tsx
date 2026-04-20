import { useCopy } from "../../../app/copy";
import type { AllocationGroup } from "../api";

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function AllocationGroupsCard({ groups }: { groups: AllocationGroup[] }) {
  const copy = useCopy();

  if (groups.length === 0) {
    return (
      <div className="app-panel rounded-2xl p-5 text-sm app-muted">
        {copy.portfolio.allocationGroups.empty}
      </div>
    );
  }

  return (
    <div className="app-panel rounded-2xl p-5">
      <div className="app-kicker mb-4 text-xs uppercase tracking-[0.18em]">
        {copy.portfolio.allocationGroups.title}
      </div>
      <div className="space-y-4">
        {groups.map((group) => (
          <div key={group.asset_class} className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span>{group.name}</span>
              <span>{percent.format(group.weight)}</span>
            </div>
            <div className="app-progress-track h-2 overflow-hidden rounded-full">
              <div
                className="app-progress-fill h-full rounded-full"
                style={{ width: `${Math.max(group.weight * 100, 2)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
