import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useAccountStateQuery,
  useEquityCurveSeriesQuery,
  useExplainabilityQuery,
  useDailyTradingPlanQuery,
  type EquityCurveRange,
} from '../overview-feature-boundary';

export type OverviewAnalysisView = 'curve' | 'calendar';

export function useOverviewPageController() {
  const copy = useCopy();
  const [analysisView, setAnalysisView] =
    useState<OverviewAnalysisView>('curve');
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('ytd');
  const account = useAccountStateQuery();
  const accountReady = Boolean(account.data);
  const equityCurve = useEquityCurveSeriesQuery(equityCurveRange, accountReady);
  const explainability = useExplainabilityQuery(
    undefined,
    accountReady && analysisView === 'calendar',
  );
  const tradingPlan = useDailyTradingPlanQuery(accountReady);
  return {
    copy,
    account,
    equityCurve,
    explainability,
    tradingPlan,
    analysisView,
    setAnalysisView,
    equityCurveRange,
    setEquityCurveRange,
  };
}
