import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useAccountStateQuery,
  useEquityCurveSeriesQuery,
  type EquityCurveRange,
} from '../overview-feature-boundary';

export function useOverviewPageController() {
  const copy = useCopy();
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('1m');
  const account = useAccountStateQuery();
  const equityCurve = useEquityCurveSeriesQuery(
    equityCurveRange,
    Boolean(account.data),
  );
  return { copy, account, equityCurve, equityCurveRange, setEquityCurveRange };
}
