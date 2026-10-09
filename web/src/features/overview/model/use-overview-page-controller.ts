import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useAccountStateQuery,
  useEquityCurveSeriesQuery,
  useExplainabilityQuery,
  useDailyTradingPlanQuery,
  useTodayDecisionQuery,
  useEtfRotationDashboardQuery,
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
  const marketSession = account.data?.overview.market_session;
  const marketClosed =
    marketSession?.calendar_verified === true &&
    marketSession.status === 'non_trading_day';
  const equityCurve = useEquityCurveSeriesQuery(equityCurveRange, accountReady);
  const explainability = useExplainabilityQuery(
    undefined,
    accountReady && analysisView === 'calendar',
  );
  const tradingPlan = useDailyTradingPlanQuery(accountReady && !marketClosed);
  const todayDecision = useTodayDecisionQuery(accountReady && !marketClosed);
  const etfRotation = useEtfRotationDashboardQuery(
    accountReady && !marketClosed,
  );
  return {
    copy,
    account,
    equityCurve,
    explainability,
    tradingPlan,
    todayDecision,
    etfRotation,
    marketClosed,
    analysisView,
    setAnalysisView,
    equityCurveRange,
    setEquityCurveRange,
  };
}
