import { useCopy } from '../../../app/copy';
import { DataTable } from '../../../app/components/workbench';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { AllocationItem } from '../api';

export function AllocationCard({ items }: { items: AllocationItem[] }) {
  const copy = useCopy();

  if (items.length === 0) {
    return (
      <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
        {copy.portfolio.allocation.empty}
      </div>
    );
  }

  return (
    <section className="min-w-0">
      <h2 className="mb-2 text-sm font-semibold text-[var(--app-text)]">
        {copy.portfolio.allocation.title}
      </h2>
      <DataTable
        data={items}
        caption={copy.portfolio.allocation.title}
        emptyState={copy.portfolio.allocation.empty}
        getRowId={(item) => item.symbol}
        columns={[
          {
            id: 'instrument',
            header: copy.portfolio.table.symbol,
            cell: ({ row }) => (
              <a
                href={`/portfolio/${encodeURIComponent(row.original.symbol)}`}
                className="font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)]"
              >
                {row.original.name} ·{' '}
                <span className="font-mono text-[var(--app-text-tertiary)]">
                  {row.original.symbol}
                </span>
              </a>
            ),
          },
          {
            id: 'value',
            header: () => (
              <span className="block text-right">
                {copy.portfolio.table.marketValue}
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
                {copy.portfolio.table.weight}
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
