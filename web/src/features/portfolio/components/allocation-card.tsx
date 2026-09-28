import { useMemo } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { DataTable } from '../../../shared/ui/workbench';
import { formatCurrency, formatPercent } from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import type { AllocationItem } from '../api';

export type AllocationSectorGroup = {
  assetClass: string;
  label: string;
  color: string;
  value: number;
  weight: number;
  count: number;
};

const ASSET_CLASS_COLORS: Record<string, string> = {
  stock: 'var(--app-accent)',
  fund: 'var(--app-info-indicator)',
  etf: 'var(--app-success-indicator)',
  gold: 'var(--app-warning-indicator)',
  bond: 'var(--app-chart-sell)',
  cash: 'var(--app-text-tertiary)',
};

function getAssetClassColor(assetClass: string) {
  return ASSET_CLASS_COLORS[assetClass.toLowerCase()] ?? 'var(--app-border)';
}

export function useAllocationGroups(items: AllocationItem[]) {
  const copy = useCopy();
  return useMemo(() => {
    const map = new Map<
      string,
      { value: number; weight: number; count: number }
    >();
    for (const item of items) {
      const key = (item.asset_class || 'other').toLowerCase();
      const existing = map.get(key) || { value: 0, weight: 0, count: 0 };
      existing.value += item.value;
      existing.weight += item.weight;
      existing.count += 1;
      map.set(key, existing);
    }
    return Array.from(map.entries())
      .map(([assetClass, data]) => ({
        assetClass,
        label: formatAssetClassLabel(assetClass, {
          assetClassStock: copy.common.assetClassStock,
          assetClassEtf: copy.common.assetClassEtf,
          assetClassFund: copy.common.assetClassFund,
          assetClassGold: copy.common.assetClassGold,
          assetClassBond: copy.common.assetClassBond,
          assetClassCash: copy.common.assetClassCash,
        }),
        color: getAssetClassColor(assetClass),
        value: data.value,
        weight: data.weight,
        count: data.count,
      }))
      .sort((a, b) => b.weight - a.weight);
  }, [items, copy.common]);
}

export function PortfolioAllocationBar({
  items,
  testId = 'portfolio-allocation-bar',
  className = 'mb-4 space-y-2',
}: {
  items: AllocationItem[];
  testId?: string;
  className?: string;
}) {
  const copy = useCopy();
  const groups = useAllocationGroups(items);

  if (items.length === 0) {
    return null;
  }

  return (
    <div
      data-testid={testId}
      className={className}
      role="region"
      aria-label={copy.portfolio.allocation.title}
    >
      <div className="flex h-2.5 w-full overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[var(--app-surface-overlay)]">
        {groups.map((group) => {
          const pct = Math.max(0, group.weight * 100);
          if (pct <= 0) return null;
          return (
            <div
              key={group.assetClass}
              data-testid={`allocation-bar-segment-${group.assetClass}`}
              style={{
                width: `${pct}%`,
                backgroundColor: group.color,
              }}
              className="h-full transition-all motion-reduce:transition-none first:rounded-l-full last:rounded-r-full"
              title={`${group.label}: ${formatPercent(group.weight)} (${formatCurrency(group.value)})`}
            />
          );
        })}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[length:var(--app-font-size-micro)] font-mono text-[var(--app-text-secondary)]">
        {groups.map((group) => (
          <span
            key={group.assetClass}
            data-testid={`allocation-legend-${group.assetClass}`}
            className="flex items-center gap-1.5"
          >
            <span
              className="inline-block h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: group.color }}
            />
            <span className="font-sans font-medium text-[var(--app-text)]">
              {group.label}
            </span>
            <span className="tabular-nums text-[var(--app-muted)]">
              {formatPercent(group.weight)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function AllocationCard({
  items,
  onOpenPosition,
}: {
  items: AllocationItem[];
  onOpenPosition?: (symbol: string) => void;
}) {
  const copy = useCopy();

  if (items.length === 0) {
    return (
      <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
        {copy.portfolio.allocation.empty}
      </div>
    );
  }

  return (
    <section className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-4 sm:p-5 space-y-3 shadow-xs">
      <h3 className="app-type-subsection-title font-semibold text-[var(--app-text)]">
        {copy.portfolio.allocation.title}
      </h3>
      <PortfolioAllocationBar items={items} />
      <DataTable
        data={items}
        caption={copy.portfolio.allocation.title}
        emptyState={copy.portfolio.allocation.empty}
        getRowId={(item) => item.symbol}
        columns={[
          {
            id: 'instrument',
            header: copy.portfolio.allocation.asset,
            cell: ({ row }) => {
              if (row.original.asset_class === 'cash') {
                return (
                  <span
                    className="font-semibold text-[var(--app-text)]"
                    data-allocation-kind="cash"
                  >
                    {copy.portfolio.allocation.cashBalance}
                  </span>
                );
              }

              return (
                <a
                  href={`/portfolio/${encodeURIComponent(row.original.symbol)}`}
                  onClick={(event) => {
                    if (
                      !onOpenPosition ||
                      event.defaultPrevented ||
                      event.button !== 0 ||
                      event.metaKey ||
                      event.ctrlKey ||
                      event.shiftKey ||
                      event.altKey
                    ) {
                      return;
                    }
                    event.preventDefault();
                    onOpenPosition(row.original.symbol);
                  }}
                  className="font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)]"
                >
                  {row.original.name} ·{' '}
                  <span className="font-mono text-[var(--app-text-tertiary)]">
                    {row.original.symbol}
                  </span>
                </a>
              );
            },
          },
          {
            id: 'value',
            header: () => (
              <span className="block text-right">
                {copy.portfolio.allocation.valuationAmount}
              </span>
            ),
            cell: ({ row }) => (
              <span className="block text-right font-mono font-semibold tabular-nums">
                {formatCurrency(row.original.value)}
              </span>
            ),
          },
          {
            id: 'weight',
            header: () => (
              <span className="block text-right">
                {copy.portfolio.allocation.navShare}
              </span>
            ),
            cell: ({ row }) => (
              <span className="block text-right font-mono font-semibold tabular-nums">
                {formatPercent(row.original.weight)}
              </span>
            ),
          },
        ]}
      />
    </section>
  );
}
