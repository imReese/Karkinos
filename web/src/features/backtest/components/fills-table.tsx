import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table';
import { useMemo } from 'react';

import { useCopy } from '../../../app/copy';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import type { BacktestFill } from '../api';

export function FillsTable({ fills }: { fills: BacktestFill[] }) {
  const labels = useCopy().backtest.fills;
  const columns = useMemo<Array<ColumnDef<BacktestFill>>>(
    () => [
      {
        accessorKey: 'timestamp',
        header: labels.time,
        cell: ({ row }) => formatTimestamp(row.original.timestamp),
      },
      {
        accessorKey: 'symbol',
        header: labels.symbol,
      },
      {
        accessorKey: 'side',
        header: labels.side,
        cell: ({ row }) => (
          <span
            className={
              row.original.side === 'buy'
                ? 'text-[#a6e3a1]'
                : 'text-[var(--app-danger)]'
            }
          >
            {row.original.side.toUpperCase()}
          </span>
        ),
      },
      {
        accessorKey: 'fill_price',
        header: labels.fillPrice,
        cell: ({ row }) => formatPrice(row.original.fill_price),
      },
      {
        accessorKey: 'fill_quantity',
        header: labels.quantity,
        cell: ({ row }) => formatQuantity(row.original.fill_quantity),
      },
      {
        accessorKey: 'commission',
        header: labels.commission,
        cell: ({ row }) => (
          <span className="text-[#f9e2af]">
            {formatCurrency(row.original.commission)}
          </span>
        ),
      },
      {
        accessorKey: 'slippage',
        header: labels.slippage,
        cell: ({ row }) => (
          <span className="text-[var(--app-danger)]">
            {formatCurrency(row.original.slippage)}
          </span>
        ),
      },
    ],
    [labels],
  );
  const table = useReactTable({
    data: fills,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <section className="app-panel min-w-0 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-end justify-between gap-3 px-4 py-4 sm:px-5">
        <div>
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <div className="app-card-title mt-1.5">{labels.title}</div>
        </div>
        <div className="app-muted text-xs tabular-nums">
          {labels.rows(fills.length)}
        </div>
      </div>

      {fills.length === 0 ? (
        <div className="border-t border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)] sm:px-5">
          {labels.empty}
        </div>
      ) : (
        <div className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain border-t border-[color-mix(in_srgb,var(--app-border)_22%,transparent)]">
          <table className="min-w-full text-left text-sm">
            <thead className="app-panel-strong app-kicker text-xs uppercase tracking-[0.14em]">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th key={header.id} className="px-4 py-3 font-semibold">
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-[color-mix(in_srgb,var(--app-border)_20%,transparent)] tabular-nums">
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className="transition-colors hover:bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)]"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="whitespace-nowrap px-4 py-3">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
