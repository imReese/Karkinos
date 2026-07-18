import {
  useMemo,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react';

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowData,
} from '@tanstack/react-table';

import { cn } from '../../../lib/utils/cn';

export function DataTable<TData extends RowData>({
  data,
  columns,
  caption,
  emptyState,
  getRowId,
  rowLabel,
  rowHref,
  rowTestId,
  scrollTestId,
  tableTestId,
  className,
}: {
  data: ReadonlyArray<TData>;
  columns: ReadonlyArray<ColumnDef<TData, unknown>>;
  caption: string;
  emptyState: ReactNode;
  getRowId?: (row: TData, index: number) => string;
  rowLabel?: (row: TData) => string;
  rowHref?: (row: TData) => string;
  rowTestId?: (row: TData) => string;
  scrollTestId?: string;
  tableTestId?: string;
  className?: string;
}) {
  const stableData = useMemo(() => [...data], [data]);
  const stableColumns = useMemo(() => [...columns], [columns]);
  const table = useReactTable({
    data: stableData,
    columns: stableColumns,
    getCoreRowModel: getCoreRowModel(),
    getRowId,
  });

  return (
    <div
      className={cn(
        'min-w-0 overflow-hidden rounded-[var(--app-radius-surface)] border border-[var(--app-border)] bg-[var(--app-surface)]',
        className,
      )}
    >
      {data.length === 0 ? (
        <div className="px-3 py-5 text-sm text-[var(--app-text-secondary)]">
          {emptyState}
        </div>
      ) : (
        <div
          data-testid={scrollTestId}
          className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain"
        >
          <table
            data-testid={tableTestId}
            className="w-full min-w-max border-collapse text-left text-xs"
          >
            <caption className="sr-only">{caption}</caption>
            <thead className="sticky top-0 z-10 bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)] shadow-[var(--app-shadow-sticky)]">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      scope="col"
                      className="h-8 whitespace-nowrap border-b border-[var(--app-divider)] px-3 font-semibold"
                    >
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
            <tbody className="divide-y divide-[var(--app-divider)] tabular-nums">
              {table.getRowModel().rows.map((row) => {
                const href = rowHref?.(row.original);
                const openRow = () => {
                  if (href) {
                    window.location.assign(href);
                  }
                };
                const handleClick = (
                  event: MouseEvent<HTMLTableRowElement>,
                ) => {
                  if (
                    href &&
                    !(event.target as HTMLElement).closest(
                      'a,button,input,select,textarea',
                    )
                  ) {
                    openRow();
                  }
                };
                const handleKeyDown = (
                  event: KeyboardEvent<HTMLTableRowElement>,
                ) => {
                  if (href && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault();
                    openRow();
                  }
                };
                return (
                  <tr
                    key={row.id}
                    data-testid={rowTestId?.(row.original)}
                    aria-label={rowLabel?.(row.original)}
                    tabIndex={href ? 0 : undefined}
                    onClick={handleClick}
                    onKeyDown={handleKeyDown}
                    className={cn(
                      'h-9 text-[var(--app-text)] hover:bg-[var(--app-accent-bg)]',
                      href && 'cursor-pointer',
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td
                        key={cell.id}
                        className="whitespace-nowrap px-3 py-2 align-middle"
                      >
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext(),
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
