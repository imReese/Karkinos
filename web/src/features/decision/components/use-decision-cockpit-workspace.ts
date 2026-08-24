import { useMemo, useState } from 'react';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useAutomationCockpitQuery,
  useBrokerConnectorHealthQuery,
  useBrokerGatewayAccountFactsQuery,
  useBrokerGatewayFillsQuery,
  useBrokerGatewayOrderQuery,
  useBrokerGatewayStatusQuery,
  useExecutionReconciliationRunDetailQuery,
  useExecutionReconciliationRunsQuery,
  useOperationsTodayQuery,
  useRunPaperShadowMutation,
} from '../decision-feature-boundary';
import {
  useDailyTradingPlanQuery,
  useIntradayDecisionQuery,
  useSignalActionsQuery,
  useSignalJournalQuery,
  useTodayDecisionQuery,
  type DecisionResponse,
} from '../api';
import { primaryExecutionReconciliationItemForRun } from './decision-execution-evidence-model';
import { decisionGateMatrixItems } from './decision-gate-model';

export function useDecisionCockpitWorkspace() {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const today = useTodayDecisionQuery();
  const primaryDecisionReady = Boolean(today.data);
  const intraday = useIntradayDecisionQuery(primaryDecisionReady);
  const tradingPlan = useDailyTradingPlanQuery(primaryDecisionReady);
  const operationsToday = useOperationsTodayQuery(primaryDecisionReady);
  const automationCockpit = useAutomationCockpitQuery(primaryDecisionReady);
  const brokerGatewayStatus = useBrokerGatewayStatusQuery(primaryDecisionReady);
  const brokerConnectorHealth =
    useBrokerConnectorHealthQuery(primaryDecisionReady);
  const brokerAccountFacts =
    useBrokerGatewayAccountFactsQuery(primaryDecisionReady);
  const brokerFills = useBrokerGatewayFillsQuery(primaryDecisionReady);
  const executionReconciliationRuns =
    useExecutionReconciliationRunsQuery(primaryDecisionReady);
  const latestExecutionReconciliationRunId =
    executionReconciliationRuns.data?.[0]?.run_id;
  const executionReconciliationRunDetail =
    useExecutionReconciliationRunDetailQuery(
      latestExecutionReconciliationRunId,
    );
  const latestExecutionReconciliationRun =
    executionReconciliationRunDetail.data ??
    executionReconciliationRuns.data?.[0];
  const primaryExecutionReconciliationItem =
    primaryExecutionReconciliationItemForRun(latestExecutionReconciliationRun);
  const brokerOrderQuery = useBrokerGatewayOrderQuery(
    primaryExecutionReconciliationItem?.order_id,
  );
  const runPaperShadow = useRunPaperShadowMutation();
  const signalActions = useSignalActionsQuery(primaryDecisionReady);
  const signalJournal = useSignalJournalQuery(primaryDecisionReady);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [healthyGateMatrixExpanded, setHealthyGateMatrixExpanded] =
    useState(false);
  const loading = !today.data && today.isLoading;
  const error = today.data ? null : today.error;
  const lanes = useMemo(
    () =>
      [today.data, intraday.data].filter((item): item is DecisionResponse =>
        Boolean(item),
      ),
    [intraday.data, today.data],
  );
  const denseCandidateCount = useMemo(
    () =>
      lanes.reduce((total, lane) => total + lane.summary.candidate_count, 0),
    [lanes],
  );
  const collapseDecisionEvidence = denseCandidateCount > 0;
  const gateItems = useMemo(
    () => decisionGateMatrixItems(today.data, labels, locale),
    [labels, locale, today.data],
  );
  const allDecisionGatesPass =
    gateItems.length > 0 && gateItems.every((item) => item.state === 'pass');
  const decisionGateAttentionCount = gateItems.filter(
    (item) => item.state !== 'pass',
  ).length;
  const idleTradingPlan =
    !tradingPlan.isLoading &&
    !tradingPlan.isError &&
    tradingPlan.data?.order_intent_count === 0 &&
    tradingPlan.data.candidate_pool_count === 0
      ? tradingPlan.data
      : null;
  return {
    copy,
    labels,
    locale,
    today,
    intraday,
    tradingPlan,
    operationsToday,
    automationCockpit,
    brokerGatewayStatus,
    brokerConnectorHealth,
    brokerAccountFacts,
    brokerFills,
    executionReconciliationRuns,
    executionReconciliationRunDetail,
    brokerOrderQuery,
    runPaperShadow,
    signalActions,
    signalJournal,
    summaryExpanded,
    setSummaryExpanded,
    healthyGateMatrixExpanded,
    setHealthyGateMatrixExpanded,
    loading,
    error,
    lanes,
    denseCandidateCount,
    collapseDecisionEvidence,
    gateItems,
    allDecisionGatesPass,
    decisionGateAttentionCount,
    idleTradingPlan,
  };
}

export type DecisionCockpitWorkspaceModel = ReturnType<
  typeof useDecisionCockpitWorkspace
>;
