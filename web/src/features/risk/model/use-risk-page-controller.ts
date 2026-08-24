import { useMemo, useState } from 'react';

import { getErrorMessage } from '../../../shared/error-message';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { ExceptionItem } from '../../../shared/ui/workbench';
import {
  useAccountStateQuery,
  useBatchPreTradeRiskMutation,
  useExplainabilityQuery,
  useRiskWorkspaceQuery,
  useTodayDecisionQuery,
} from '../risk-feature-boundary';
import {
  formatRiskAlertDetail,
  formatRiskAlertLevel,
  formatRiskAlertTitle,
  getRiskAlertKindLabel,
  getRiskMetricDetail,
  getRiskMetricLabel,
} from './risk-presentation';

export function useRiskPageController() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const state = useAccountStateQuery();
  const workspace = useRiskWorkspaceQuery();
  const primaryRiskQueriesReady = Boolean(state.data && workspace.data);
  const todayDecision = useTodayDecisionQuery(primaryRiskQueriesReady);
  const batchPreTradeRisk = useBatchPreTradeRiskMutation();
  const [timelineFromDate, setTimelineFromDate] = useState('');
  const [timelineToDate, setTimelineToDate] = useState('');
  const [timelineEventKind, setTimelineEventKind] = useState('');
  const [batchRiskMessage, setBatchRiskMessage] = useState<string | null>(null);
  const [batchRiskBlockedMessage, setBatchRiskBlockedMessage] = useState<
    string | null
  >(null);
  const [batchRiskError, setBatchRiskError] = useState<string | null>(null);
  const explainability = useExplainabilityQuery(
    {
      from_date: timelineFromDate || undefined,
      to_date: timelineToDate || undefined,
      event_kind: timelineEventKind || undefined,
    },
    primaryRiskQueriesReady,
  );
  const instrumentNames = useMemo(() => {
    const names = new Map<string, string>();
    const remember = (
      symbol: string | null | undefined,
      displayName: string | null | undefined,
    ) => {
      const normalizedSymbol = symbol?.trim();
      const normalizedName = displayName?.trim();
      if (!normalizedSymbol || !normalizedName) return;
      names.set(normalizedSymbol.toLowerCase(), normalizedName);
    };
    const snapshot = state.data?.snapshot;
    snapshot?.allocation.forEach((item) => remember(item.symbol, item.name));
    snapshot?.allocation_grouped.forEach((group) =>
      group.items.forEach((item) => remember(item.symbol, item.name)),
    );
    snapshot?.positions.forEach((position) =>
      remember(position.symbol, position.display_name ?? position.name),
    );
    return names;
  }, [state.data?.snapshot]);
  const riskReviewTask = todayDecision.data?.summary.workflow_tasks?.find(
    (task) =>
      task.id === 'risk_review' &&
      task.required_actions.includes('run_pre_trade_risk_gate') &&
      task.status !== 'pass' &&
      task.status !== 'passed',
  );
  const riskReviewEvidence = riskReviewTask?.evidence as
    | {
        total_action_count?: number;
        risk_checked_count?: number;
        risk_blocked_count?: number;
      }
    | undefined;
  const riskCandidateCount =
    riskReviewEvidence?.total_action_count ??
    todayDecision.data?.summary.candidate_count ??
    0;
  const riskCheckedCount = riskReviewEvidence?.risk_checked_count ?? 0;
  const representedRiskMetricKeys = new Set<string>();
  const activeRiskItems: ExceptionItem[] = [];
  for (const item of state.data?.risks ?? []) {
    if (item.level !== 'high' && item.level !== 'medium') continue;
    switch (item.kind) {
      case 'cash_buffer':
        representedRiskMetricKeys.add('cash_ratio');
        break;
      case 'concentration':
        representedRiskMetricKeys.add('largest_weight');
        representedRiskMetricKeys.add('top3_weight');
        break;
      case 'largest_weight':
      case 'gross_exposure':
      case 'current_drawdown':
      case 'max_drawdown':
        representedRiskMetricKeys.add(item.kind);
        break;
      case 'capital_deployment':
        representedRiskMetricKeys.add('gross_exposure');
        break;
    }
    activeRiskItems.push({
      id: `${item.kind}-${item.title}`,
      severity: item.level === 'high' ? 'danger' : 'warning',
      statusLabel: formatRiskAlertLevel(item.level, locale),
      title: formatRiskAlertTitle(item.title, locale),
      reason: formatRiskAlertDetail(item.detail, locale),
      evidence: `${getRiskAlertKindLabel(copy, item.kind)} · ${formatRiskAlertLevel(item.level, locale)}`,
    });
  }
  for (const metric of workspace.data?.metrics ?? []) {
    if (
      (metric.level !== 'high' && metric.level !== 'medium') ||
      representedRiskMetricKeys.has(metric.key)
    ) {
      continue;
    }
    activeRiskItems.push({
      id: `metric-${metric.key}`,
      severity: metric.level === 'high' ? 'danger' : 'warning',
      statusLabel: formatRiskAlertLevel(metric.level, locale),
      title: getRiskMetricLabel(copy, metric.key),
      reason: `${metric.display_value} · ${getRiskMetricDetail(copy, metric.key)}`,
      evidence: `${getRiskMetricLabel(copy, metric.key)} · ${formatRiskAlertLevel(metric.level, locale)}`,
    });
  }
  activeRiskItems.sort(
    (left, right) =>
      Number(left.severity !== 'danger') - Number(right.severity !== 'danger'),
  );

  const hasAnyRiskProjection = Boolean(state.data || workspace.data);
  const isRiskWorkspacePending = !workspace.data && workspace.isLoading;
  const isInitialRiskLoad =
    (!state.data && state.isLoading) || isRiskWorkspacePending;
  const isRiskWorkspaceUnavailable = !state.data || !workspace.data;

  async function runBatchRiskGate() {
    setBatchRiskMessage(null);
    setBatchRiskBlockedMessage(null);
    setBatchRiskError(null);
    try {
      const result = await batchPreTradeRisk.mutateAsync();
      if (result.status === 'blocked_by_data_quality') {
        setBatchRiskBlockedMessage(
          locale === 'zh'
            ? `批量风控未运行：估值或行情证据尚未完整，已跳过 ${result.skipped_count} 个候选。未写入风险决策、订单或账本；请先处理数据状态后重试。`
            : `Batch risk did not run: valuation or market evidence is incomplete, so ${result.skipped_count} candidates were skipped. No risk decisions, orders, or ledger entries were written; resolve the data status before retrying.`,
        );
        return;
      }
      setBatchRiskMessage(
        copy.riskPage.batchRiskGateDone(
          result.passed_count,
          result.blocked_count,
        ),
      );
    } catch (error) {
      setBatchRiskError(
        `${copy.riskPage.batchRiskGateFailed} ${getErrorMessage(error)}`,
      );
    }
  }

  return {
    activeRiskItems,
    batchPreTradeRisk,
    batchRiskBlockedMessage,
    batchRiskError,
    batchRiskMessage,
    copy,
    explainability,
    hasAnyRiskProjection,
    hasRiskRefreshError:
      !isRiskWorkspaceUnavailable && (state.isError || workspace.isError),
    instrumentNames,
    isInitialRiskLoad,
    isRiskWorkspaceUnavailable,
    locale,
    riskCandidateCount,
    riskCheckedCount,
    riskHistoryImpactCount: explainability.data?.recent_drivers.length ?? 0,
    riskHistoryValuationDayCount: explainability.data?.timeline.length ?? 0,
    riskReviewTask,
    runBatchRiskGate,
    setTimelineEventKind,
    setTimelineFromDate,
    setTimelineToDate,
    state,
    timelineEventKind,
    timelineFromDate,
    timelineToDate,
    workspace,
  };
}

export type RiskPageController = ReturnType<typeof useRiskPageController>;
