import { useMemo, type MouseEvent, type ReactNode } from 'react';

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowData,
  type SortingState,
} from '@tanstack/react-table';

import { cn } from '../../utils/cn';

export function DataTable<TData extends RowData>({
  data,
  columns,
  caption,
  emptyState,
  getRowId,
  rowLabel,
  rowHref,
  sorting = [],
  rowTestId,
  scrollTestId,
  tableTestId,
  className,
}: {
  data: ReadonlyArray<TData>;
  columns: ReadonlyArray<ColumnDef<TData, any>>;
  caption: string;
  emptyState: ReactNode;
  getRowId?: (row: TData, index: number) => string;
  rowLabel?: (row: TData) => string;
  rowHref?: (row: TData) => string;
  sorting?: SortingState;
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
    state: { sorting },
    manualSorting: true,
  });

  return (
    <div
      data-workbench-primitive="data-table"
      className={cn(
        'app-data-table-shell min-w-0 overflow-hidden border-y border-[var(--app-divider)] bg-transparent',
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
            className="app-data-table app-type-compact w-full min-w-max border-collapse text-left"
          >
            <caption className="sr-only">{caption}</caption>
            <thead className="sticky top-0 z-10 bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)] shadow-[var(--app-shadow-sticky)]">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={
                        header.column.getIsSorted() === 'asc'
                          ? 'ascending'
                          : header.column.getIsSorted() === 'desc'
                            ? 'descending'
                            : undefined
                      }
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
                const handleClick = (
                  event: MouseEvent<HTMLTableRowElement>,
                ) => {
                  if (
                    href &&
                    !event.defaultPrevented &&
                    !window.getSelection()?.toString() &&
                    (event.button === 0 || event.button === 1) &&
                    !(event.target as HTMLElement).closest(
                      'a,button,input,select,textarea,[role="button"],[contenteditable="true"]',
                    )
                  ) {
                    if (
                      event.metaKey ||
                      event.ctrlKey ||
                      event.shiftKey ||
                      event.button === 1
                    ) {
                      window.open(href, '_blank', 'noopener,noreferrer');
                      return;
                    }
                    if (event.altKey) return;
                    // Reuse the cell link's router handler for ordinary row clicks.
                    const link = Array.from(
                      event.currentTarget.querySelectorAll<HTMLAnchorElement>(
                        'a[href]',
                      ),
                    ).find((anchor) => anchor.getAttribute('href') === href);
                    link?.click();
                  }
                };
                return (
                  <tr
                    key={row.id}
                    data-testid={rowTestId?.(row.original)}
                    aria-label={rowLabel?.(row.original)}
                    onClick={handleClick}
                    onAuxClick={handleClick}
                    className={cn(
                      'h-9 text-[var(--app-text)] hover:bg-[var(--app-accent-bg)]',
                      href && 'cursor-pointer',
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td
                        key={cell.id}
                        className="whitespace-nowrap px-3 py-1.5 align-middle"
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
