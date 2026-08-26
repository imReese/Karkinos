import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { buildPositionColumns } from './positions-table-columns';
import {
  buildPositionsTableModel,
  type PositionsTableProps,
} from './positions-table-model';
import { PositionsTableView } from './positions-table-view';

export function PositionsTable(props: PositionsTableProps) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const model = buildPositionsTableModel(props);
  const columns = buildPositionColumns({ copy, locale, model });
  return (
    <PositionsTableView
      columns={columns}
      copy={copy}
      locale={locale}
      model={model}
    />
  );
}
