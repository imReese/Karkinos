import { useCopy } from '../../../shared/i18n/context';
import { DataTable } from '../../../shared/ui/workbench';
import { formatCurrency, formatPercent } from '../../../shared/format';
import type { AllocationItem } from '../api';

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
    <section className="min-w-0">
      <h3 className="app-type-subsection-title mb-2 text-[var(--app-text)]">
        {copy.portfolio.allocation.title}
      </h3>
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
