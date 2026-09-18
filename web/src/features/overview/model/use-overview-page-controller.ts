import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useAccountStateQuery,
  useEquityCurveSeriesQuery,
  useDailyTradingPlanQuery,
  useTodayDecisionQuery,
  type EquityCurveRange,
} from '../overview-feature-boundary';

export function useOverviewPageController() {
  const copy = useCopy();
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('1m');
  const account = useAccountStateQuery();
  const accountReady = Boolean(account.data);
  const equityCurve = useEquityCurveSeriesQuery(equityCurveRange, accountReady);
  const todayDecision = useTodayDecisionQuery(accountReady);
  const tradingPlan = useDailyTradingPlanQuery(accountReady);
  return {
    copy,
    account,
    equityCurve,
    todayDecision,
    tradingPlan,
    equityCurveRange,
    setEquityCurveRange,
  };
}
