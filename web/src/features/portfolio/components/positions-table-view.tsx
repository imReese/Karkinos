import type { ColumnDef } from '@tanstack/react-table';

import type { useCopy } from '../../../shared/i18n/context';
import { DataTable, EvidenceState } from '../../../shared/ui/workbench';
import type { Position } from '../api';
import {
  holdingDetailHref,
  resolvePositionName,
  type PositionsTableModel,
} from './positions-table-model';
import { PositionsTableMobileList } from './positions-table-mobile-list';
import type { Locale } from '../../../shared/preferences/context';

type PortfolioCopy = ReturnType<typeof useCopy>;

export function PositionsTableView({
  columns,
  copy,
  locale,
  model,
}: {
  columns: ColumnDef<Position, unknown>[];
  copy: PortfolioCopy;
  locale: Locale;
  model: PositionsTableModel;
}) {
  const labels = copy.portfolio.table;
  return (
    <div className="min-w-0 space-y-2">
      {model.variant === 'dashboard' && model.hasQuotesNeedingReview ? (
        <EvidenceState
          kind="partial"
          title={labels.cachedQuoteNotice}
          evidence={labels.quoteState}
        />
      ) : null}

      <PositionsTableMobileList copy={copy} locale={locale} model={model} />

      <div className="hidden min-w-0 md:block">
        <DataTable
          className={`app-positions-table ${
            model.variant === 'dashboard' ? 'app-positions-table-dashboard' : ''
          }`}
          data={model.positions}
          columns={columns}
          caption={labels.symbol}
          emptyState={copy.portfolio.positionsEmpty}
          getRowId={(position) => position.symbol}
          rowLabel={(position) =>
            `${labels.detailsTitle}: ${resolvePositionName(position)} ${
              position.symbol
            }`
          }
          rowHref={(position) => holdingDetailHref(position.symbol)}
          rowTestId={(position) => `position-row-${position.symbol}`}
          scrollTestId="positions-table-scroll"
          tableTestId="positions-table-desktop"
        />
      </div>
    </div>
  );
}
