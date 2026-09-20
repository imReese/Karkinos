import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useAccountStateQuery,
  useEquityCurveSeriesQuery,
  useDailyTradingPlanQuery,
  type EquityCurveRange,
} from '../overview-feature-boundary';

export function useOverviewPageController() {
  const copy = useCopy();
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('ytd');
  const account = useAccountStateQuery();
  const accountReady = Boolean(account.data);
  const equityCurve = useEquityCurveSeriesQuery(equityCurveRange, accountReady);
  const tradingPlan = useDailyTradingPlanQuery(accountReady);
  return {
    copy,
    account,
    equityCurve,
    tradingPlan,
    equityCurveRange,
    setEquityCurveRange,
  };
}
