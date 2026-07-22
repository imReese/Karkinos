import { type ColumnDef } from '@tanstack/react-table';
import { useMemo } from 'react';

import { useCopy } from '../../../app/copy';
import { DataTable } from '../../../app/components/workbench';
import { usePreferences, type Locale } from '../../../app/preferences';
import {
  formatCurrency,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatLedgerOrderSideLabel } from '../../../shared/ledger-format';
import type { BacktestFill } from '../api';

export function FillsTable({ fills }: { fills: BacktestFill[] }) {
  const labels = useCopy().backtest.fills;
  const { locale } = usePreferences();
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
                ? 'text-[var(--app-chart-buy)]'
                : row.original.side === 'sell'
                  ? 'text-[var(--app-chart-sell)]'
                  : 'text-[var(--app-text-secondary)]'
            }
          >
            {formatFillSide(row.original.side, locale)}
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
          <span className="text-[var(--app-pnl-negative)]">
            {formatCurrency(row.original.commission)}
          </span>
        ),
      },
      {
        accessorKey: 'slippage',
        header: labels.slippage,
        cell: ({ row }) => (
          <span className="text-[var(--app-pnl-negative)]">
            {formatCurrency(row.original.slippage)}
          </span>
        ),
      },
    ],
    [labels, locale],
  );

  return (
    <section
      data-backtest-report-section="fills"
      className="app-workbench-section min-w-0 border-t border-[var(--app-divider)] pt-4"
    >
      <div className="flex flex-wrap items-end justify-between gap-3 pb-3">
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
      <DataTable
        data={fills}
        columns={columns}
        caption={labels.title}
        emptyState={labels.empty}
        scrollTestId="backtest-fills-scroll"
        tableTestId="backtest-fills-table"
      />
    </section>
  );
}

function formatFillSide(side: string, locale: Locale) {
  return formatLedgerOrderSideLabel(side, locale);
}
