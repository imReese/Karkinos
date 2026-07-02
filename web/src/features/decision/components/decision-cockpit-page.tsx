import { useMemo, useState } from 'react';

import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatTimestamp,
} from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  formatStrategyDisplayName,
  type StrategyNameMap,
} from '../../../shared/strategy-display';
import {
  useOperationsTodayQuery,
  type OperationsTodayResponse,
} from '../../operations/api';
import {
  useCreateManualOrderFromActionMutation,
  useDailyTradingPlanQuery,
  useIntradayDecisionQuery,
  useSignalActionsQuery,
  useSignalJournalQuery,
  useTodayDecisionQuery,
  type ActionCard,
  type AccountTruthGateEvidence,
  type DecisionCandidate,
  type DecisionResponse,
  type DecisionWorkflowTask,
  type DailyTradingPlanResponse,
  type SignalJournalEntry,
  type SignalResponse,
  type StrategyAttributionGateEvidence,
} from '../api';

function normalizeStatus(value: string | null | undefined, locale: Locale) {
  return formatPublicStatus(value ?? 'unknown', locale);
}

function decisionTone(value: string) {
  if (
    value === 'pass' ||
    value === 'passed' ||
    value === 'attached' ||
    value === 'live'
  ) {
    return 'success';
  }
  if (
    value === 'blocked' ||
    value === 'failed' ||
    value === 'missing' ||
    value === 'not_attached'
  ) {
    return 'danger';
  }
  return 'warning';
}

function evidenceStatus(candidate: DecisionCandidate) {
  return candidate.evidence.after_cost_oos_validation.status;
}

function manualStatus(candidate: DecisionCandidate, locale: Locale) {
  if (
    candidate.manual_confirmation_status === 'ready_for_manual_confirmation'
  ) {
    return formatPublicStatus(candidate.manual_confirmation_status, locale);
  }
  return normalizeStatus(candidate.manual_confirmation_status, locale);
}

function accountTruthScore(value: AccountTruthGateEvidence | null | undefined) {
  if (value?.score === null || value?.score === undefined) {
    return '--';
  }
  return String(value.score);
}

function accountTruthValue(
  value: AccountTruthGateEvidence | null | undefined,
  locale: Locale,
) {
  const status = value?.gate_status ?? 'not_evaluated';
  return `${normalizeStatus(status, locale)} · ${accountTruthScore(value)}`;
}

function accountTruthTone(value: AccountTruthGateEvidence | null | undefined) {
  const status = value?.gate_status ?? 'not_evaluated';
  return decisionTone(status);
}

function strategyAttributionValue(
  value: StrategyAttributionGateEvidence | null | undefined,
  locale: Locale,
  strategyNames: StrategyNameMap,
) {
  const status = value?.gate_status ?? 'not_configured';
  const strategyLabel = value?.strategy_id
    ? formatStrategyDisplayName(
        { strategy_id: value.strategy_id },
        strategyNames,
      )
    : '--';
  return `${normalizeStatus(status, locale)} · ${strategyLabel}`;
}

function strategyAttributionAuditId(
  value: StrategyAttributionGateEvidence | null | undefined,
  strategyNames: StrategyNameMap,
) {
  if (!value?.strategy_id) {
    return null;
  }
  const strategyLabel = formatStrategyDisplayName(
    { strategy_id: value.strategy_id },
    strategyNames,
  );
  return strategyLabel === value.strategy_id ? null : value.strategy_id;
}

function strategyDisplayNameFromId(
  strategyId: string | null | undefined,
  strategyNames: StrategyNameMap,
) {
  return formatStrategyDisplayName({ strategy_id: strategyId }, strategyNames);
}

function strategyAuditIdFromDisplay(
  strategyId: string | null | undefined,
  strategyNames: StrategyNameMap,
) {
  const normalized = strategyId?.trim();
  if (!normalized) {
    return null;
  }
  const strategyLabel = strategyDisplayNameFromId(normalized, strategyNames);
  return strategyLabel === normalized ? null : normalized;
}

function strategyAttributionTone(
  value: StrategyAttributionGateEvidence | null | undefined,
) {
  const status = value?.gate_status ?? 'not_configured';
  return status === 'not_configured' ? 'neutral' : decisionTone(status);
}

type DecisionCopy = ReturnType<typeof useCopy>['decision'];
type BacktestPageCopy = ReturnType<typeof useCopy>['backtest']['page'];

type CandidateEvidenceChainItem = {
  label: string;
  value: string;
  tone?: 'success' | 'warning' | 'danger' | 'neutral';
};

function numericEvidenceValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nullableCurrency(value: unknown) {
  return formatCurrency(numericEvidenceValue(value));
}

function strategyContributionDetailItems(
  strategyAttribution: StrategyAttributionGateEvidence | null | undefined,
  labels: BacktestPageCopy,
) {
  if (!strategyAttribution) {
    return [];
  }
  const netContribution = numericEvidenceValue(
    strategyAttribution.net_contribution,
  );
  const grossRealizedPnl = numericEvidenceValue(
    strategyAttribution.gross_realized_pnl,
  );
  const grossUnrealizedPnl = numericEvidenceValue(
    strategyAttribution.gross_unrealized_pnl,
  );
  const totalCommission = numericEvidenceValue(
    strategyAttribution.total_commission,
  );
  const totalSlippage = numericEvidenceValue(
    strategyAttribution.total_slippage,
  );
  const totalTax = numericEvidenceValue(strategyAttribution.total_tax);
  const manualUnattributedPnl = numericEvidenceValue(
    strategyAttribution.manual_unattributed_pnl,
  );
  const cashFlowPnl = numericEvidenceValue(strategyAttribution.cash_flow_pnl);
  const unattributedAccountPnl = numericEvidenceValue(
    strategyAttribution.unattributed_account_pnl,
  );

  return [
    netContribution === null
      ? ''
      : `${labels.accountStrategyNetContribution}: ${formatCurrency(netContribution)}`,
    grossRealizedPnl === null
      ? ''
      : `${labels.accountStrategyGrossRealizedPnl}: ${formatCurrency(grossRealizedPnl)}`,
    grossUnrealizedPnl === null
      ? ''
      : `${labels.accountStrategyGrossUnrealizedPnl}: ${formatCurrency(grossUnrealizedPnl)}`,
    totalCommission === null && totalSlippage === null
      ? ''
      : `${labels.accountStrategyCommissionSlippage}: ${nullableCurrency(totalCommission)} / ${nullableCurrency(totalSlippage)}`,
    manualUnattributedPnl === null && cashFlowPnl === null
      ? ''
      : `${labels.accountStrategyManualCashFlowMovement}: ${nullableCurrency(manualUnattributedPnl)} / ${nullableCurrency(cashFlowPnl)}`,
    totalTax === null && unattributedAccountPnl === null
      ? ''
      : `${labels.accountStrategyTaxExcludedMovement}: ${nullableCurrency(totalTax)} / ${nullableCurrency(unattributedAccountPnl)}`,
  ].filter(Boolean);
}

function candidateEvidenceChainItems(
  candidate: DecisionCandidate,
  locale: Locale,
  labels: DecisionCopy,
  strategyNames: StrategyNameMap,
): CandidateEvidenceChainItem[] {
  const paperShadow = candidate.evidence.paper_shadow;
  const paperShadowActions = (paperShadow?.required_actions ?? [])
    .map((action) => formatPublicCode(action, locale))
    .join('；');
  const costImpact = candidate.evidence.cost_impact;
  const commission = numericEvidenceValue(costImpact?.total_commission);
  const slippage = numericEvidenceValue(costImpact?.total_slippage);
  const costStatus = formatPublicStatus(
    costImpact?.status ?? 'missing',
    locale,
  );
  const costDetail =
    commission === null && slippage === null
      ? costStatus
      : `${costStatus} · ${labels.costImpactSummary(
          formatCurrency(commission),
          formatCurrency(slippage),
        )}`;
  const uncertainty = candidate.evidence.uncertainty;
  const uncertaintyFactors = (uncertainty?.factors ?? []).map((factor) =>
    formatPublicNote(factor, locale),
  );
  const uncertaintyDetail = [
    formatPublicStatus(uncertainty?.status ?? 'pass', locale),
    uncertaintyFactors.length
      ? uncertaintyFactors.join('；')
      : labels.noUncertainty,
  ].join(' · ');
  const certainty = candidate.evidence.certainty;
  const certaintyStatus = certainty?.status ?? 'pass';
  const certaintyHeadline =
    certaintyStatus === 'blocked'
      ? labels.certaintyBlocked
      : certaintyStatus === 'degraded' ||
          certainty?.posture === 'review_required'
        ? labels.certaintyReviewRequired
        : labels.certaintyPass;
  const certaintyActions = (certainty?.required_actions ?? []).map((action) =>
    formatPublicCode(action, locale),
  );
  const certaintyReasons = (certainty?.uncertain_reasons ?? []).map((reason) =>
    formatPublicNote(reason, locale),
  );
  const certaintyDetail = [
    certaintyHeadline,
    ...certaintyActions,
    ...certaintyReasons,
  ].join(' · ');
  const strategyId = candidate.evidence.strategy.strategy_id;
  const strategyAuditId = strategyAuditIdFromDisplay(strategyId, strategyNames);

  return [
    {
      label: labels.strategySource,
      value: strategyDisplayNameFromId(strategyId, strategyNames),
    },
    ...(strategyAuditId
      ? [
          {
            label: labels.strategyAuditId,
            value: strategyAuditId,
            tone: 'neutral' as const,
          },
        ]
      : []),
    {
      label: labels.marketDataStatus,
      value: formatPublicStatus(
        candidate.evidence.data_freshness.status,
        locale,
      ),
      tone: decisionTone(candidate.evidence.data_freshness.status),
    },
    {
      label: labels.accountTruth,
      value: formatPublicStatus(
        candidate.evidence.account_truth?.gate_status ?? 'not_evaluated',
        locale,
      ),
      tone: accountTruthTone(candidate.evidence.account_truth),
    },
    {
      label: labels.riskStatus,
      value: formatPublicStatus(candidate.evidence.risk_gate.status, locale),
      tone: decisionTone(candidate.evidence.risk_gate.status),
    },
    {
      label: labels.researchEvidence,
      value: formatPublicStatus(evidenceStatus(candidate), locale),
      tone: decisionTone(evidenceStatus(candidate)),
    },
    {
      label: labels.paperShadowEvidence,
      value: paperShadowActions
        ? `${formatPublicStatus(
            paperShadow?.status ?? 'not_evaluated',
            locale,
          )} · ${paperShadowActions}`
        : formatPublicStatus(paperShadow?.status ?? 'not_evaluated', locale),
      tone: decisionTone(paperShadow?.status ?? 'not_evaluated'),
    },
    {
      label: labels.costImpact,
      value: costDetail,
      tone: decisionTone(costImpact?.status ?? 'missing'),
    },
    {
      label: labels.certainty,
      value: certaintyDetail,
      tone: decisionTone(certaintyStatus),
    },
    {
      label: labels.uncertainty,
      value: uncertaintyDetail,
      tone: decisionTone(uncertainty?.status ?? 'pass'),
    },
    {
      label: labels.manual,
      value: manualStatus(candidate, locale),
      tone:
        candidate.manual_confirmation_status === 'ready_for_manual_confirmation'
          ? 'success'
          : 'warning',
    },
  ];
}

function gateRequirementLabels(
  values: string[],
  labels: ReturnType<typeof useCopy>['decision'],
) {
  return values.map((value) => labels.gateRequirementLabel(value));
}

function gateBlockingReasonLabels(values: string[], locale: Locale) {
  return values.map((value) => formatPublicNote(value, locale));
}

function decisionGateDetailLabels({
  requiredActions,
  blockingReasons,
  labels,
  locale,
}: {
  requiredActions: string[];
  blockingReasons: string[];
  labels: ReturnType<typeof useCopy>['decision'];
  locale: Locale;
}) {
  return requiredActions.length > 0
    ? gateRequirementLabels(requiredActions, labels)
    : gateBlockingReasonLabels(blockingReasons, locale);
}

function decisionWorkflowTarget(
  taskId: string,
  labels: ReturnType<typeof useCopy>['decision'],
) {
  switch (taskId) {
    case 'data_refresh':
      return { href: '/market', label: labels.workflowOpenMarket };
    case 'risk_review':
      return { href: '/risk', label: labels.workflowOpenRisk };
    case 'strategy_evidence':
    case 'paper_shadow_review':
      return { href: '/backtest', label: labels.workflowOpenBacktest };
    case 'manual_confirmation':
      return { href: '/trading', label: labels.workflowOpenTrading };
    default:
      return null;
  }
}

type DecisionNextActionGuide = {
  title: string;
  detail: string;
  status: string;
  what: string;
  how: string;
  after: string;
  note: string;
  cta: string | null;
  href: string | null;
};

function decisionNeedsAction(task: DecisionWorkflowTask) {
  return task.status !== 'pass' && task.status !== 'passed';
}

function decisionActionRank(task: DecisionWorkflowTask) {
  if (task.status === 'blocked') {
    return 0;
  }
  if (task.status === 'review_required') {
    return 1;
  }
  if (task.status === 'degraded') {
    return 2;
  }
  return 3;
}

function decisionNextActionGuide(
  lanes: DecisionResponse[],
  labels: ReturnType<typeof useCopy>['decision'],
  locale: Locale,
): DecisionNextActionGuide | null {
  const rankedTasks = lanes.flatMap((lane, laneIndex) =>
    (lane.summary.workflow_tasks ?? []).map((task) => ({
      lane,
      laneIndex,
      task,
    })),
  );
  const actionableTasks = rankedTasks
    .filter(({ task }) => decisionNeedsAction(task))
    .sort((left, right) => {
      const actionRank =
        decisionActionRank(left.task) - decisionActionRank(right.task);
      if (actionRank !== 0) {
        return actionRank;
      }
      const priority = left.task.priority - right.task.priority;
      return priority === 0 ? left.laneIndex - right.laneIndex : priority;
    });
  const primary =
    actionableTasks.find(({ task }) => task.id !== 'manual_confirmation') ??
    actionableTasks[0];

  if (!primary) {
    return null;
  }

  const { lane, task } = primary;
  const taskLabel = labels.workflowTaskLabel(task.id);
  const actionLabels = decisionGateDetailLabels({
    requiredActions: task.required_actions,
    blockingReasons: task.blocking_reasons,
    labels,
    locale,
  });
  const actionLabel =
    actionLabels[0] ?? formatPublicStatus(task.status, locale);
  const target = decisionWorkflowTarget(task.id, labels);
  const isRiskGateNext =
    task.id === 'risk_review' &&
    task.required_actions.includes('run_pre_trade_risk_gate');
  const title = isRiskGateNext
    ? labels.nextActionRiskTitle
    : labels.nextActionDefaultTitle(taskLabel);

  return {
    title,
    detail: isRiskGateNext
      ? labels.nextActionRiskDetail(
          lane.summary.candidate_count,
          lane.summary.ready_for_manual_confirmation_count,
        )
      : labels.nextActionDefaultDetail(actionLabel),
    status: formatPublicStatus(task.status, locale),
    what: labels.nextActionWhat(taskLabel),
    how: labels.nextActionHow(actionLabel),
    after: labels.nextActionAfter,
    note:
      lane.summary.candidate_count >
      lane.summary.ready_for_manual_confirmation_count
        ? labels.nextActionCandidatePoolNote
        : labels.nextActionManualReadyNote,
    cta: target ? labels.workflowOpenSurfaceLabel(target.label, title) : null,
    href: target?.href ?? null,
  };
}

function decisionCandidateBacktestHref(candidate: DecisionCandidate) {
  const params = new URLSearchParams();
  const symbol = candidate.symbol.trim();
  const assetClass = candidate.asset_class?.trim() ?? '';
  const strategyId = candidate.evidence.strategy.strategy_id?.trim() ?? '';
  if (symbol) {
    params.set('symbol', symbol);
  }
  if (assetClass) {
    params.set('assetClass', assetClass);
  }
  if (strategyId) {
    params.set('strategy', strategyId);
  }
  const query = params.toString();
  return query ? `/backtest?${query}` : '/backtest';
}

function signalActionBacktestHref(action: ActionCard) {
  const params = new URLSearchParams();
  const symbol = action.symbol.trim();
  const assetClass = action.asset_class.trim();
  const strategyId = action.strategy_id.trim();
  if (symbol) {
    params.set('symbol', symbol);
  }
  if (assetClass) {
    params.set('assetClass', assetClass);
  }
  if (strategyId) {
    params.set('strategy', strategyId);
  }
  const query = params.toString();
  return query ? `/backtest?${query}` : '/backtest';
}

function decisionCandidateHoldingAttributionHref(candidate: DecisionCandidate) {
  return `/portfolio/${encodeURIComponent(
    candidate.symbol,
  )}#holding-strategy-attribution-boundary`;
}

function signalActionHoldingAttributionHref(action: ActionCard) {
  return `/portfolio/${encodeURIComponent(
    action.symbol,
  )}#holding-strategy-attribution-boundary`;
}

function signalBacktestHref(signal: SignalResponse) {
  const params = new URLSearchParams();
  const symbol = signal.symbol.trim();
  const assetClass = signal.asset_class.trim();
  const strategyId = signal.strategy_id.trim();
  if (symbol) {
    params.set('symbol', symbol);
  }
  if (assetClass) {
    params.set('assetClass', assetClass);
  }
  if (strategyId) {
    params.set('strategy', strategyId);
  }
  const query = params.toString();
  return query ? `/backtest?${query}` : '/backtest';
}

function signalHoldingAttributionHref(signal: SignalResponse) {
  return `/portfolio/${encodeURIComponent(
    signal.symbol,
  )}#holding-strategy-attribution-boundary`;
}

function tradingPlanConclusionLabel(
  status: string | null | undefined,
  labels: DecisionCopy,
) {
  if (status === 'manual_confirmation_ready') {
    return labels.tradingPlanManualConfirmationReady;
  }
  if (status === 'account_truth_blocked') {
    return labels.tradingPlanAccountTruthBlocked;
  }
  if (status === 'risk_blocked') {
    return labels.tradingPlanRiskBlocked;
  }
  if (status === 'data_unavailable') {
    return labels.tradingPlanDataUnavailable;
  }
  if (status === 'portfolio_blocked') {
    return labels.tradingPlanPortfolioBlocked;
  }
  if (status === 'market_blocked') {
    return labels.tradingPlanMarketBlocked;
  }
  if (status === 'cash_shortfall') {
    return labels.tradingPlanCashShortfall;
  }
  return labels.tradingPlanNoManualAction;
}

const TRADING_PLAN_CONSTRAINT_LABELS: Record<
  string,
  { en: string; zh: string }
> = {
  trading_unit: { en: 'Trading unit', zh: '交易单位' },
  fee_tax_preview: { en: 'Fee and tax preview', zh: '费用税费预览' },
  cash_buffer: { en: 'Cash buffer', zh: '现金缓冲' },
  concentration: { en: 'Concentration', zh: '集中度' },
  t1_available_quantity: { en: 'T+1 sellable quantity', zh: 'T+1 可卖数量' },
  limit_up: { en: 'Limit up', zh: '涨停' },
  limit_down: { en: 'Limit down', zh: '跌停' },
  limit_move: { en: 'Price-limit status', zh: '涨跌停状态' },
  suspension: { en: 'Suspension', zh: '停牌' },
  special_treatment: { en: 'Special-treatment risk', zh: 'ST 风险' },
  drawdown: { en: 'Drawdown', zh: '回撤' },
  fund_nav_latency: { en: 'Fund NAV latency', zh: '基金净值延迟' },
};

function tradingPlanConstraintLabel(id: string, locale: Locale) {
  const label = TRADING_PLAN_CONSTRAINT_LABELS[id];
  return label?.[locale] ?? formatPublicCode(id, locale);
}

function paperShadowStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    not_required: { en: 'Not required', zh: '无需模拟' },
    not_run: { en: 'Not run', zh: '尚未运行' },
    review_required: { en: 'Review required', zh: '需要复核' },
    within_expectations: { en: 'Within expectations', zh: '符合预期' },
    diverged: { en: 'Diverged', zh: '存在偏差' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function paperShadowNextStepLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    none: { en: 'No additional simulation review', zh: '无需额外模拟复核' },
    run_paper_shadow_daily: {
      en: 'Run paper/shadow simulation before manual confirmation',
      zh: '人工确认前先运行 paper/shadow 模拟',
    },
    review_shadow_divergence: {
      en: 'Review paper/shadow divergence evidence',
      zh: '复核 paper/shadow 偏差证据',
    },
    review_manual_confirmation: {
      en: 'Simulation reviewed; continue with manual confirmation',
      zh: '模拟已复核，可继续人工确认',
    },
    resolve_shadow_divergence: {
      en: 'Resolve simulation divergence before approval',
      zh: '批准前先处理模拟偏差',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function DailyTradingPlanPanel({
  plan,
  operationsToday,
  loading,
  error,
}: {
  plan: DailyTradingPlanResponse | undefined;
  operationsToday: OperationsTodayResponse | undefined;
  loading: boolean;
  error: boolean;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const firstIntent = plan?.order_intents?.[0];
  const constraintChecks = firstIntent?.constraint_checks ?? [];
  const fallbackShadowStatus =
    (plan?.order_intent_count ?? 0) > 0 ? 'not_run' : 'not_required';

  return (
    <section
      data-testid="decision-daily-trading-plan"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.tradingPlanKicker}</div>
            <h2 className="app-card-title mt-1.5">{labels.tradingPlanTitle}</h2>
          </div>
          <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
            {labels.tradingPlanDetail}
          </p>
        </div>

        {loading ? (
          <div className="app-muted mt-4 text-sm">
            {labels.tradingPlanLoading}
          </div>
        ) : error || !plan ? (
          <div className="app-error-text mt-4 text-sm">
            {labels.tradingPlanError}
          </div>
        ) : (
          <div className="mt-4 grid min-w-0 gap-3 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {tradingPlanConclusionLabel(plan.conclusion_status, labels)}
              </div>
              <div className="app-muted mt-2 text-sm">
                {labels.tradingPlanCounts(
                  plan.candidate_pool_count,
                  plan.order_intent_count,
                  plan.blocked_count,
                )}
              </div>
              <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                <span className="app-chip">
                  {labels.tradingPlanDefaultManual}
                </span>
                <span className="app-chip">
                  {labels.tradingPlanBrokerDisabled}
                </span>
              </div>
            </div>

            <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3">
              <div className="flex min-w-0 items-center justify-between gap-3">
                <div className="min-w-0 text-sm font-semibold text-[var(--app-text)]">
                  {labels.tradingPlanOrderIntentPreviews}
                </div>
                <span className="app-chip">{plan.order_intent_count}</span>
              </div>
              {firstIntent ? (
                <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-2">
                  <div className="min-w-0 break-words">
                    {firstIntent.symbol} ·{' '}
                    {formatPublicStatus(firstIntent.side, locale)}
                  </div>
                  <div className="font-mono tabular-nums">
                    {labels.tradingPlanQuantity}:{' '}
                    {firstIntent.estimated_quantity}
                  </div>
                  <div className="font-mono tabular-nums">
                    {labels.targetWeight}:{' '}
                    {formatPercent(firstIntent.target_weight)}
                  </div>
                  <div className="font-mono tabular-nums">
                    {labels.price}: {formatPrice(firstIntent.estimated_price)}
                  </div>
                  <div className="font-mono tabular-nums">
                    {labels.tradingPlanFee}:{' '}
                    {formatCurrency(firstIntent.estimated_total_fee)}
                  </div>
                  <div className="font-mono tabular-nums">
                    {labels.tradingPlanNetCash}:{' '}
                    {formatCurrency(firstIntent.estimated_net_cash_impact)}
                  </div>
                  {firstIntent.cash_shortfall > 0 ? (
                    <div className="font-mono tabular-nums text-[var(--app-warning)]">
                      {labels.tradingPlanCashShortfallAmount}:{' '}
                      {formatCurrency(firstIntent.cash_shortfall)}
                    </div>
                  ) : null}
                  {constraintChecks.length > 0 ? (
                    <div className="sm:col-span-2">
                      <div className="app-muted mb-2 text-xs font-semibold uppercase tracking-[0.16em]">
                        {labels.tradingPlanConstraintChecks}
                      </div>
                      <div className="flex min-w-0 flex-wrap gap-2">
                        {constraintChecks.map((check) => (
                          <span
                            className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
                              check.status === 'blocked'
                                ? 'border-[color-mix(in_srgb,var(--app-danger)_40%,transparent)] text-[var(--app-danger)]'
                                : 'border-[color-mix(in_srgb,var(--app-success)_35%,transparent)] text-[var(--app-success)]'
                            }`}
                            key={check.id}
                          >
                            {tradingPlanConstraintLabel(check.id, locale)} ·{' '}
                            {formatPublicStatus(check.status, locale)}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {firstIntent.position_effect ? (
                    <>
                      <div className="font-mono tabular-nums">
                        {labels.tradingPlanPositionAfter}:{' '}
                        {firstIntent.position_effect.estimated_quantity_after}
                      </div>
                      <div className="font-mono tabular-nums">
                        {labels.tradingPlanCostBasis}:{' '}
                        {firstIntent.position_effect
                          .estimated_avg_cost_after === null
                          ? firstIntent.position_effect.cost_basis_method
                          : `${formatPrice(
                              firstIntent.position_effect
                                .estimated_avg_cost_after,
                            )} · ${firstIntent.position_effect.cost_basis_method}`}
                      </div>
                    </>
                  ) : null}
                  <div className="app-muted sm:col-span-2">
                    {labels.tradingPlanDoesNotSubmit}
                  </div>
                </div>
              ) : (
                <div className="app-muted mt-3 text-sm">
                  {labels.tradingPlanNoOrderIntents}
                </div>
              )}
            </div>

            <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3 xl:col-span-2">
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 text-sm font-semibold text-[var(--app-text)]">
                  {locale === 'zh'
                    ? 'Paper/shadow 模拟复核'
                    : 'Paper/shadow simulation review'}
                </div>
                <span className="app-chip">
                  {paperShadowStatusLabel(
                    operationsToday?.paper_shadow.status ??
                      fallbackShadowStatus,
                    locale,
                  )}
                </span>
              </div>
              <div className="app-muted mt-2 text-sm">
                {paperShadowNextStepLabel(
                  operationsToday?.paper_shadow.next_manual_review_step ??
                    'run_paper_shadow_daily',
                  locale,
                )}
              </div>
              <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
                <div>
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '订单意图' : 'Order intents'}
                  </div>
                  <div className="font-mono tabular-nums">
                    {operationsToday?.paper_shadow.order_intent_count ??
                      plan.order_intent_count}
                  </div>
                </div>
                <div>
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '模拟订单' : 'Sim orders'}
                  </div>
                  <div className="font-mono tabular-nums">
                    {operationsToday?.paper_shadow.simulated_order_count ?? 0}
                  </div>
                </div>
                <div>
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '模拟成交' : 'Sim fills'}
                  </div>
                  <div className="font-mono tabular-nums">
                    {operationsToday?.paper_shadow.simulated_fill_count ?? 0}
                  </div>
                </div>
                <div>
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '偏差复核' : 'Divergence reviews'}
                  </div>
                  <div className="font-mono tabular-nums">
                    {operationsToday?.paper_shadow.divergence_reviewed_count ??
                      0}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export function DecisionCockpitPage() {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const today = useTodayDecisionQuery();
  const intraday = useIntradayDecisionQuery();
  const tradingPlan = useDailyTradingPlanQuery();
  const operationsToday = useOperationsTodayQuery();
  const signalActions = useSignalActionsQuery();
  const signalJournal = useSignalJournalQuery();
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const loading = today.isLoading || intraday.isLoading;
  const error = today.error ?? intraday.error;
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
  const collapseDecisionEvidence = denseCandidateCount > 6;
  const commandRegisterRows = useMemo(() => {
    const totals = lanes.reduce(
      (accumulator, lane) => ({
        candidates: accumulator.candidates + lane.summary.candidate_count,
        manualReady:
          accumulator.manualReady +
          lane.summary.ready_for_manual_confirmation_count,
        riskBlocked: accumulator.riskBlocked + lane.summary.risk_blocked_count,
        signals: accumulator.signals + (lane.summary.audit?.signal_count ?? 0),
        journalEntries:
          accumulator.journalEntries +
          (lane.summary.audit?.journal_entry_count ?? 0),
      }),
      {
        candidates: 0,
        manualReady: 0,
        riskBlocked: 0,
        signals: 0,
        journalEntries: 0,
      },
    );

    return [
      {
        label: labels.candidateActions,
        value: String(totals.candidates),
        tone: totals.candidates > 0 ? 'success' : 'neutral',
      },
      {
        label: labels.manualConfirmations,
        value: labels.readyCount(totals.manualReady),
        tone: totals.manualReady > 0 ? 'success' : 'neutral',
      },
      {
        label: labels.riskBlocks,
        value: labels.blockedCount(totals.riskBlocked),
        tone: totals.riskBlocked > 0 ? 'danger' : 'success',
      },
      {
        label: labels.auditCoverage,
        value: `${totals.journalEntries}/${totals.signals}`,
        tone:
          totals.signals > 0 && totals.journalEntries >= totals.signals
            ? 'success'
            : 'warning',
      },
      {
        label: labels.marketData,
        value: formatPublicStatus(
          today.data?.summary.market_data?.source_health ?? '--',
          locale,
        ),
        tone:
          today.data?.summary.market_data?.source_health === 'live'
            ? 'success'
            : 'warning',
      },
      {
        label: labels.executionDefault,
        value: labels.manualConfirmationRequired,
        tone: 'success',
      },
      {
        label: labels.accountTruthGate,
        value: accountTruthValue(today.data?.summary.account_truth, locale),
        tone: accountTruthTone(today.data?.summary.account_truth),
      },
      {
        label: labels.strategyAttributionGate,
        value: strategyAttributionValue(
          today.data?.summary.strategy_attribution,
          locale,
          copy.backtest.page.strategyNames,
        ),
        tone: strategyAttributionTone(today.data?.summary.strategy_attribution),
      },
    ] satisfies Array<{
      label: string;
      value: string;
      tone: 'success' | 'warning' | 'danger' | 'neutral';
    }>;
  }, [lanes, labels, locale, today.data]);

  if (loading) {
    return (
      <section className="space-y-5">
        <PageHeader title={labels.title} subtitle={labels.subtitle} />
        <StatePanel title={copy.states.loading} detail={labels.loading} />
      </section>
    );
  }

  if (error) {
    return (
      <section className="space-y-5">
        <PageHeader title={labels.title} subtitle={labels.subtitle} />
        <StatePanel
          title={copy.states.error}
          detail={error instanceof Error ? error.message : labels.error}
        />
      </section>
    );
  }

  return (
    <section className="min-w-0 space-y-5 sm:space-y-6">
      <PageHeader title={labels.title} subtitle={labels.subtitle} />

      <DecisionNextActionGuidePanel lanes={lanes} />

      <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
        <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="app-product-mark">{labels.commandRegister}</div>
              <h2 className="app-card-title mt-1.5">
                {labels.commandRegisterTitle}
              </h2>
            </div>
            <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
              {labels.commandRegisterDetail}
            </p>
          </div>
          <div className="mt-4 grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {commandRegisterRows.map((row) => (
              <DecisionRegisterRow
                key={row.label}
                label={row.label}
                value={row.value}
                tone={row.tone}
              />
            ))}
          </div>
        </div>
      </section>

      <DailyTradingPlanPanel
        plan={tradingPlan.data}
        operationsToday={operationsToday.data}
        loading={tradingPlan.isLoading}
        error={tradingPlan.isError}
      />

      <DecisionWorkflowPanel lanes={lanes} />

      <SignalQueuePanel
        actions={signalActions.data ?? []}
        journal={signalJournal.data ?? []}
        loading={signalActions.isLoading || signalJournal.isLoading}
        error={signalActions.isError || signalJournal.isError}
      />

      {collapseDecisionEvidence && !summaryExpanded ? (
        <DecisionSummaryCollapsedPanel
          candidateCount={denseCandidateCount}
          onExpand={() => setSummaryExpanded(true)}
        />
      ) : (
        <div
          data-testid="decision-summary-grid"
          className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4"
        >
          {lanes.map((lane) => (
            <LaneStatusTile key={lane.lane} lane={lane} />
          ))}
          {lanes.map((lane) => (
            <AccountTruthGateTile
              key={`${lane.lane}-account-truth`}
              lane={lane}
            />
          ))}
          {lanes.map((lane) => (
            <StrategyAttributionGateTile
              key={`${lane.lane}-strategy-attribution`}
              lane={lane}
            />
          ))}
          <SummaryTile
            label={labels.marketHealth}
            value={`${labels.marketHealth}: ${formatPublicStatus(
              today.data?.summary.market_data?.source_health ?? '--',
              locale,
            )}`}
            detail={labels.quotesDetail(
              today.data?.summary.market_data?.live_quote_count ?? 0,
              today.data?.summary.market_data?.stale_quote_count ?? 0,
            )}
          />
          <SummaryTile
            label={labels.portfolio}
            value={`${labels.portfolioEquity}: ${formatCurrency(
              today.data?.summary.portfolio?.total_equity,
            )}`}
            detail={labels.positionCount(
              today.data?.summary.portfolio?.position_count ?? 0,
            )}
          />
        </div>
      )}

      <div
        data-testid="decision-lane-grid"
        className="grid min-w-0 gap-5 xl:grid-cols-2"
      >
        {lanes.map((lane) => (
          <DecisionLanePanel key={lane.lane} lane={lane} />
        ))}
      </div>
    </section>
  );
}

function DecisionNextActionGuidePanel({
  lanes,
}: {
  lanes: DecisionResponse[];
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const guide = useMemo(
    () => decisionNextActionGuide(lanes, labels, locale),
    [lanes, labels, locale],
  );

  if (!guide) {
    return null;
  }

  return (
    <section
      data-testid="decision-next-action-guide"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.nextActionKicker}</div>
            <h2 className="app-card-title mt-1.5">{guide.title}</h2>
            <p className="app-muted mt-2 max-w-3xl break-words text-sm leading-6">
              {guide.detail}
            </p>
          </div>
          <div className="inline-flex min-h-9 items-center justify-center rounded-full border border-[color-mix(in_srgb,var(--app-warning)_45%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_12%,transparent)] px-3 py-1 text-sm font-semibold text-[var(--app-warning)]">
            {guide.status}
          </div>
        </div>

        <div className="mt-4 grid min-w-0 gap-2 md:grid-cols-3">
          {[guide.what, guide.how, guide.after].map((item, index) => (
            <div
              key={`${index}-${item}`}
              className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5 text-sm font-semibold leading-6 text-[var(--app-text)]"
            >
              {item}
            </div>
          ))}
        </div>

        <div className="mt-4 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0 rounded-full border border-[color-mix(in_srgb,var(--app-accent)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] px-3 py-1.5 text-sm font-semibold text-[var(--app-accent)]">
            {guide.note}
          </div>
          {guide.href && guide.cta ? (
            <a
              className="inline-flex min-h-10 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-4 py-2 text-sm font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
              href={guide.href}
            >
              {guide.cta}
            </a>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function DecisionSummaryCollapsedPanel({
  candidateCount,
  onExpand,
}: {
  candidateCount: number;
  onExpand: () => void;
}) {
  const labels = useCopy().decision;
  return (
    <section
      data-testid="decision-summary-collapsed"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner flex min-w-0 flex-col gap-3 rounded-[27px] p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="min-w-0">
          <div className="app-product-mark">
            {labels.summaryCollapsedKicker}
          </div>
          <h2 className="app-card-title mt-1.5">
            {labels.summaryCollapsedTitle(candidateCount)}
          </h2>
          <p className="app-muted mt-2 break-words text-sm leading-6">
            {labels.summaryCollapsedDetail}
          </p>
        </div>
        <button
          className="inline-flex min-h-10 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-4 py-2 text-sm font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
          type="button"
          onClick={onExpand}
        >
          {labels.expandSummary}
        </button>
      </div>
    </section>
  );
}

function DecisionWorkflowPanel({ lanes }: { lanes: DecisionResponse[] }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const lanesWithTasks = lanes.filter(
    (lane) => (lane.summary.workflow_tasks ?? []).length > 0,
  );
  const denseCandidateCount = lanesWithTasks.reduce(
    (total, lane) => total + lane.summary.candidate_count,
    0,
  );
  const [expanded, setExpanded] = useState(denseCandidateCount <= 6);

  if (lanesWithTasks.length === 0) {
    return null;
  }

  return (
    <section
      data-testid="decision-workflow-tasks"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.workflowKicker}</div>
            <h2 className="app-card-title mt-1.5">{labels.workflowTitle}</h2>
          </div>
          <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
            {labels.workflowDetail}
          </p>
        </div>

        {!expanded ? (
          <div className="mt-4 flex min-w-0 flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.workflowCollapsedTitle(denseCandidateCount)}
              </div>
              <p className="app-muted mt-1 break-words text-xs leading-5">
                {labels.workflowCollapsedDetail}
              </p>
            </div>
            <button
              className="inline-flex min-h-9 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
              type="button"
              onClick={() => setExpanded(true)}
            >
              {labels.expandWorkflow}
            </button>
          </div>
        ) : (
          <div className="mt-4 grid gap-4">
            {lanesWithTasks.map((lane) => {
              const laneLabel =
                lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane;
              const tasks = [...(lane.summary.workflow_tasks ?? [])].sort(
                (left, right) => left.priority - right.priority,
              );
              return (
                <div key={`${lane.lane}-workflow`} className="min-w-0">
                  <div className="app-product-mark mb-2">{laneLabel}</div>
                  <div className="grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {tasks.map((task) => (
                      <DecisionWorkflowTaskCard
                        key={`${lane.lane}-${task.id}`}
                        task={task}
                        locale={locale}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function DecisionWorkflowTaskCard({
  task,
  locale,
}: {
  task: DecisionWorkflowTask;
  locale: Locale;
}) {
  const labels = useCopy().decision;
  const actionLabels = decisionGateDetailLabels({
    requiredActions: task.required_actions,
    blockingReasons: task.blocking_reasons,
    labels,
    locale,
  });
  const taskLabel = labels.workflowTaskLabel(task.id);
  const target = decisionWorkflowTarget(task.id, labels);

  return (
    <article className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-3.5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-words text-sm font-semibold text-[var(--app-text)]">
            {taskLabel}
          </div>
          <div className="app-muted mt-1 text-xs">
            {formatPublicStatus(task.status, locale)}
          </div>
        </div>
        <span
          className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full border ${
            decisionTone(task.status) === 'success'
              ? 'border-[var(--app-success-border)] bg-[var(--app-success)]'
              : decisionTone(task.status) === 'danger'
                ? 'border-[var(--app-danger-border)] bg-[var(--app-danger)]'
                : 'border-[color-mix(in_srgb,var(--app-warning)_45%,transparent)] bg-[var(--app-warning)]'
          }`}
          aria-hidden="true"
        />
      </div>
      <div className="mt-3 flex min-w-0 flex-wrap gap-1.5">
        {(actionLabels.length > 0 ? actionLabels : [labels.none]).map(
          (label, index) => (
            <span
              key={`${index}-${label}`}
              className="min-w-0 rounded-full border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-mantle)_28%,transparent)] px-2.5 py-1 text-xs text-[var(--app-soft)]"
            >
              {label}
            </span>
          ),
        )}
      </div>
      {target ? (
        <a
          aria-label={labels.workflowOpenSurfaceLabel(target.label, taskLabel)}
          className="mt-3 inline-flex min-h-8 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
          href={target.href}
        >
          {target.label}
        </a>
      ) : null}
    </article>
  );
}

function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  const labels = useCopy().decision;
  return (
    <header className="app-page-header min-w-0 pb-1">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">{labels.kicker}</div>
          <h1 className="app-page-title mt-2">{title}</h1>
        </div>
        <p className="app-page-subtitle min-w-0 break-words sm:max-w-xl sm:text-right">
          {subtitle}
        </p>
      </div>
    </header>
  );
}

function StatePanel({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-5">
        <h2 className="app-card-title">{title}</h2>
        <p className="app-muted mt-2 text-sm">{detail}</p>
      </div>
    </section>
  );
}

function SignalQueuePanel({
  actions,
  journal,
  loading,
  error,
}: {
  actions: ActionCard[];
  journal: SignalJournalEntry[];
  loading: boolean;
  error: boolean;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const createManualOrder = useCreateManualOrderFromActionMutation();
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [signalQueueExpanded, setSignalQueueExpanded] = useState(false);
  const latestJournal = journal.slice(0, 4);
  const collapseSignalQueue = actions.length > 3 && !signalQueueExpanded;

  const prepareManualOrder = async (action: ActionCard) => {
    if (action.id === null) {
      return;
    }
    const quantity = Number(quantities[action.id] ?? '100');
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return;
    }
    await createManualOrder.mutateAsync({
      actionId: action.id,
      quantity,
      price: action.price,
    });
  };

  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.signalQueue}</div>
            <h2 className="app-card-title mt-1.5">{labels.signalQueueTitle}</h2>
          </div>
          <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
            {labels.signalQueueDetail}
          </p>
        </div>

        {loading ? (
          <div className="app-muted mt-4 text-sm">{labels.loading}</div>
        ) : error ? (
          <div className="app-error-text mt-4 text-sm">{labels.error}</div>
        ) : collapseSignalQueue ? (
          <div
            data-testid="signal-queue-collapsed"
            className="mt-4 flex min-w-0 flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.signalQueueCollapsedTitle(actions.length)}
              </div>
              <p className="app-muted mt-1 break-words text-xs leading-5">
                {labels.signalQueueCollapsedDetail}
              </p>
            </div>
            <button
              className="inline-flex min-h-9 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
              type="button"
              onClick={() => setSignalQueueExpanded(true)}
            >
              {labels.expandSignalQueue}
            </button>
          </div>
        ) : (
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
            <div className="grid min-w-0 gap-2">
              {actions.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
                  {labels.noSignalActions}
                </div>
              ) : (
                actions.slice(0, 4).map((action) => {
                  const instrumentLabel = formatInstrumentDisplayLabel(action);
                  const actionId = action.id;
                  return (
                    <div
                      key={action.id ?? action.symbol}
                      data-testid={`signal-action-card-${action.id ?? action.symbol}`}
                      className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4"
                    >
                      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="font-semibold text-[var(--app-text)]">
                            {instrumentLabel}
                          </div>
                          <div className="app-muted mt-1 break-words text-xs">
                            {formatPublicStatus(action.direction, locale)} ·{' '}
                            {formatPublicStatus(
                              action.risk_gate_status,
                              locale,
                            )}{' '}
                            ·{' '}
                            {formatPublicStatus(
                              action.manual_confirmation_status,
                              locale,
                            )}
                          </div>
                          <div className="app-muted mt-2 break-words text-xs leading-5">
                            {formatPublicNote(action.detail, locale)}
                          </div>
                        </div>
                        <div className="grid shrink-0 gap-2 sm:grid-cols-2 lg:min-w-[280px]">
                          <a
                            className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-2xl px-3 py-2 text-center text-xs font-semibold whitespace-normal"
                            href={signalActionBacktestHref(action)}
                            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
                          >
                            {labels.openBacktestEvidence}
                          </a>
                          <a
                            className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-2xl px-3 py-2 text-center text-xs font-semibold whitespace-normal"
                            href={signalActionHoldingAttributionHref(action)}
                            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
                          >
                            {labels.openAttributionReview}
                          </a>
                          {actionId !== null &&
                          action.manual_confirmation_status ===
                            'ready_for_manual_confirmation' ? (
                            <>
                              <input
                                className="app-field rounded-2xl px-3 py-2 text-xs tabular-nums"
                                type="number"
                                min="1"
                                value={quantities[actionId] ?? '100'}
                                aria-label={`${labels.orderQuantity}: ${instrumentLabel}`}
                                onChange={(event) =>
                                  setQuantities((current) => ({
                                    ...current,
                                    [actionId]: event.target.value,
                                  }))
                                }
                              />
                              <button
                                type="button"
                                className="app-button-primary rounded-2xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={createManualOrder.isPending}
                                onClick={() => void prepareManualOrder(action)}
                              >
                                {labels.prepareManualOrder}
                              </button>
                            </>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div
              data-testid="signal-journal-panel"
              className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-4"
            >
              <div className="app-product-mark">{labels.signalJournal}</div>
              <div className="mt-3 grid gap-2">
                {latestJournal.length === 0 ? (
                  <div className="app-muted text-sm">
                    {labels.noSignalJournal}
                  </div>
                ) : (
                  latestJournal.map((entry) => {
                    const strategyNames = copy.backtest.page.strategyNames;
                    const instrumentLabel = formatInstrumentDisplayLabel(
                      entry.signal,
                    );
                    const strategyLabel = strategyDisplayNameFromId(
                      entry.signal.strategy_id,
                      strategyNames,
                    );
                    const strategyAuditId = strategyAuditIdFromDisplay(
                      entry.signal.strategy_id,
                      strategyNames,
                    );
                    const latestSourceRef = entry.latest_event?.source_ref;
                    const publicSourceRef =
                      latestSourceRef && latestSourceRef.includes(':')
                        ? formatPublicEvidenceReference(latestSourceRef, locale)
                        : null;
                    return (
                      <div
                        key={`${entry.signal.id}-${entry.signal.timestamp}`}
                        className="rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] px-3 py-2 text-xs"
                      >
                        <div className="font-semibold text-[var(--app-soft)]">
                          {instrumentLabel} · {strategyLabel}
                        </div>
                        {strategyAuditId ? (
                          <div className="app-muted mt-1 break-words">
                            {labels.strategyAuditId}: {strategyAuditId}
                          </div>
                        ) : null}
                        <div className="app-muted mt-1 break-words">
                          {formatPublicCode(
                            entry.latest_event?.event_type ??
                              entry.review?.outcome ??
                              entry.action_task?.status ??
                              '--',
                            locale,
                          )}
                        </div>
                        {publicSourceRef ? (
                          <div className="mt-1 break-words text-[var(--app-soft)]">
                            {publicSourceRef}
                          </div>
                        ) : null}
                        <div className="app-muted mt-1 font-mono tabular-nums">
                          {formatTimestamp(
                            entry.latest_event?.timestamp ??
                              entry.review?.reviewed_at ??
                              entry.signal.timestamp,
                          )}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <a
                            className="app-button-secondary inline-flex min-h-8 items-center justify-center rounded-xl px-2.5 py-1.5 text-center text-[11px] font-semibold whitespace-normal"
                            href={signalBacktestHref(entry.signal)}
                            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
                          >
                            {labels.openBacktestEvidence}
                          </a>
                          <a
                            className="app-button-secondary inline-flex min-h-8 items-center justify-center rounded-xl px-2.5 py-1.5 text-center text-[11px] font-semibold whitespace-normal"
                            href={signalHoldingAttributionHref(entry.signal)}
                            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
                          >
                            {labels.openAttributionReview}
                          </a>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function SummaryTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="app-card min-w-0 rounded-[22px] p-4">
      <div className="app-product-mark">{label}</div>
      <div className="mt-2 break-words text-base font-semibold text-[var(--app-text)]">
        {value}
      </div>
      <div className="app-muted mt-1 break-words text-xs">{detail}</div>
    </div>
  );
}

function DecisionRegisterRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'success' | 'warning' | 'danger' | 'neutral';
}) {
  const toneClass =
    tone === 'success'
      ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]'
      : tone === 'danger'
        ? 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]'
        : tone === 'warning'
          ? 'border-[color-mix(in_srgb,var(--app-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] text-[var(--app-warning)]'
          : 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] text-[var(--app-soft)]';
  return (
    <div
      className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
      aria-label={`Decision register item: ${label} ${value}`}
    >
      <div className="min-w-0 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--app-muted)]">
        {label}
      </div>
      <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 justify-self-end">
        <span
          className={`h-2 w-2 rounded-full border ${toneClass}`}
          aria-hidden="true"
        />
        <span className="min-w-0 text-right font-mono text-sm font-semibold tabular-nums text-[var(--app-text)]">
          {value}
        </span>
      </div>
    </div>
  );
}

function LaneStatusTile({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  return (
    <SummaryTile
      label={lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane}
      value={`${labels.decision}: ${formatPublicStatus(lane.decision, locale)}`}
      detail={labels.candidateCount(lane.summary.candidate_count)}
    />
  );
}

function AccountTruthGateTile({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const accountTruth = lane.summary.account_truth;
  const requiredActions = accountTruth?.required_actions ?? [];
  const blockingReasons = accountTruth?.blocking_reasons ?? [];
  const unresolvedDetail = labels.accountTruthUnresolved(
    accountTruth?.unresolved_mismatch_count ?? 0,
  );
  const actionDetail = decisionGateDetailLabels({
    requiredActions,
    blockingReasons,
    labels,
    locale,
  }).join(' · ');
  const detail =
    actionDetail.length > 0
      ? `${unresolvedDetail} · ${actionDetail}`
      : unresolvedDetail;

  return (
    <SummaryTile
      label={labels.accountTruthGate}
      value={accountTruthValue(accountTruth, locale)}
      detail={detail}
    />
  );
}

function StrategyAttributionGateTile({ lane }: { lane: DecisionResponse }) {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const strategyAttribution = lane.summary.strategy_attribution;
  const requiredActions = strategyAttribution?.required_actions ?? [];
  const blockingReasons = strategyAttribution?.blocking_reasons ?? [];
  const auditId = strategyAttributionAuditId(
    strategyAttribution,
    copy.backtest.page.strategyNames,
  );
  const detailItems = [
    auditId ? `${labels.strategyAuditId}: ${auditId}` : '',
    strategyAttribution?.attribution_status
      ? `${labels.strategyAttributionStatus}: ${formatPublicCode(
          strategyAttribution.attribution_status,
          locale,
        )}`
      : '',
    strategyAttribution?.contribution_status
      ? `${labels.strategyContributionStatus}: ${formatPublicCode(
          strategyAttribution.contribution_status,
          locale,
        )}`
      : '',
    ...strategyContributionDetailItems(strategyAttribution, copy.backtest.page),
    decisionGateDetailLabels({
      requiredActions,
      blockingReasons,
      labels,
      locale,
    }).join(' · '),
  ].filter(Boolean);

  return (
    <SummaryTile
      label={labels.strategyAttributionGate}
      value={strategyAttributionValue(
        strategyAttribution,
        locale,
        copy.backtest.page.strategyNames,
      )}
      detail={detailItems.length > 0 ? detailItems.join(' · ') : labels.none}
    />
  );
}

function DecisionLanePanel({ lane }: { lane: DecisionResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const defaultExpanded = lane.summary.candidate_count <= 3;
  const [expanded, setExpanded] = useState(defaultExpanded);
  const laneLabel =
    lane.lane === 'daily' ? labels.dailyLane : labels.intradayLane;
  const hasCandidates = lane.candidates.length > 0;
  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{laneLabel}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.decision}: {formatPublicStatus(lane.decision, locale)}
            </h2>
            <p className="app-muted mt-2 break-words text-sm">
              {labels.generatedAt}: {formatTimestamp(lane.generated_at)}
            </p>
          </div>
          <div className="grid min-w-0 gap-1 text-left text-xs sm:text-right">
            <span>
              {labels.riskBlocked}: {lane.summary.risk_blocked_count}
            </span>
            <span>
              {labels.manualReady}:{' '}
              {lane.summary.ready_for_manual_confirmation_count}
            </span>
            {lane.summary.excluded_daily_count !== undefined ? (
              <span>
                {labels.excludedDaily}: {lane.summary.excluded_daily_count}
              </span>
            ) : null}
          </div>
        </div>

        {hasCandidates ? (
          <div className="mt-5 grid min-w-0 gap-3">
            <div className="flex min-w-0 flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-semibold text-[var(--app-text)]">
                  {labels.candidateEvidenceCollapsedTitle(
                    lane.summary.candidate_count,
                  )}
                </div>
                <p className="app-muted mt-1 break-words text-xs leading-5">
                  {labels.candidateEvidenceCollapsedDetail}
                </p>
              </div>
              <button
                className="inline-flex min-h-9 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
                type="button"
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded
                  ? labels.collapseCandidateEvidence
                  : labels.expandCandidateEvidence}
              </button>
            </div>

            {expanded ? (
              <div className="grid min-w-0 gap-3">
                {lane.candidates.map((candidate) => (
                  <DecisionCandidateCard
                    key={`${lane.lane}-${candidate.action_id ?? candidate.symbol}`}
                    candidate={candidate}
                  />
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <NoActionReasons reasons={lane.no_action_reasons} />
        )}
      </div>
    </section>
  );
}

function NoActionReasons({ reasons }: { reasons: string[] }) {
  const labels = useCopy().decision;
  return (
    <div className="mt-5 min-w-0 rounded-[20px] border border-[color-mix(in_srgb,var(--app-border)_50%,transparent)] p-4">
      <div className="text-sm font-semibold">{labels.noActionReasons}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {(reasons.length ? reasons : [labels.noActionUnavailable]).map(
          (reason) => (
            <span
              key={reason}
              className="min-w-0 rounded-full border border-[var(--app-accent-border)] px-3 py-1 text-xs text-[var(--app-muted)]"
            >
              {labels.gateRequirementLabel(reason)}
            </span>
          ),
        )}
      </div>
    </div>
  );
}

function DecisionCandidateCard({
  candidate,
}: {
  candidate: DecisionCandidate;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const strategyNames = copy.backtest.page.strategyNames;
  const { locale } = usePreferences();
  const readyForManual =
    candidate.manual_confirmation_status === 'ready_for_manual_confirmation';
  const instrumentLabel = formatInstrumentDisplayLabel(candidate);
  const publicDetail = formatPublicNote(
    candidate.detail || candidate.title || labels.noDetail,
    locale,
  );
  const strategyId = candidate.evidence.strategy.strategy_id;
  const strategyAuditId = strategyAuditIdFromDisplay(strategyId, strategyNames);
  const backtestHref = decisionCandidateBacktestHref(candidate);
  const holdingDetailHref = `/portfolio/${encodeURIComponent(candidate.symbol)}`;
  const holdingAttributionHref =
    decisionCandidateHoldingAttributionHref(candidate);
  const riskGateReasons = candidate.evidence.risk_gate.reasons.map((reason) =>
    formatPublicNote(reason, locale),
  );
  return (
    <article
      data-testid={`decision-candidate-card-${candidate.symbol}`}
      className="min-w-0 break-words rounded-[22px] border border-[color-mix(in_srgb,var(--app-border)_55%,transparent)] bg-[color-mix(in_srgb,var(--app-panel)_58%,transparent)] p-4"
    >
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="break-all font-semibold text-[var(--app-text)]">
              {instrumentLabel}
            </span>
            <StatusPill value={candidate.action} />
            <StatusPill
              value={candidate.risk_gate_status}
              prefix={labels.riskGate}
            />
          </div>
          <p className="app-muted mt-2 break-words text-sm">{publicDetail}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2 lg:justify-end">
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-2xl px-4 text-center text-sm font-semibold whitespace-normal"
            href={backtestHref}
            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
          >
            {labels.openBacktestEvidence}
          </a>
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-2xl px-4 text-center text-sm font-semibold whitespace-normal"
            href={holdingDetailHref}
            aria-label={`${labels.openHoldingDetail}: ${instrumentLabel}`}
          >
            {labels.openHoldingDetail}
          </a>
          <a
            className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-2xl px-4 text-center text-sm font-semibold whitespace-normal"
            href={holdingAttributionHref}
            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
          >
            {labels.openAttributionReview}
          </a>
          {readyForManual ? (
            <a
              className="app-button-secondary inline-flex min-h-10 shrink-0 items-center justify-center rounded-2xl px-4 text-center text-sm font-semibold whitespace-normal"
              href="/trading"
              aria-label={`${labels.openTradingApprovals}: ${instrumentLabel}`}
            >
              {labels.openTradingApprovals}
            </a>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid min-w-0 gap-2 text-sm sm:grid-cols-2">
        <EvidenceLine
          label={labels.manual}
          value={manualStatus(candidate, locale)}
          tone={readyForManual ? 'success' : 'warning'}
        />
        <EvidenceLine
          label={labels.afterCostOos}
          value={formatPublicStatus(evidenceStatus(candidate), locale)}
          tone={decisionTone(evidenceStatus(candidate))}
        />
        <EvidenceLine
          label={labels.dataFreshness}
          value={formatPublicStatus(
            candidate.evidence.data_freshness.status,
            locale,
          )}
          tone={decisionTone(candidate.evidence.data_freshness.status)}
        />
        <EvidenceLine
          label={labels.accountTruth}
          value={formatPublicStatus(
            candidate.evidence.account_truth?.gate_status ?? 'not_evaluated',
            locale,
          )}
          tone={accountTruthTone(candidate.evidence.account_truth)}
        />
        <EvidenceLine
          label={labels.accountTruthScore}
          value={accountTruthScore(candidate.evidence.account_truth)}
          tone={accountTruthTone(candidate.evidence.account_truth)}
        />
        <EvidenceLine
          label={labels.strategyAttribution}
          value={formatPublicStatus(
            candidate.evidence.strategy_attribution?.gate_status ??
              'not_configured',
            locale,
          )}
          tone={strategyAttributionTone(
            candidate.evidence.strategy_attribution,
          )}
        />
        <EvidenceLine
          label={labels.journal}
          value={formatPublicCode(
            candidate.evidence.journal.latest_event_type ?? '--',
            locale,
          )}
          tone={
            candidate.evidence.journal.has_journal_entry ? 'success' : 'warning'
          }
        />
        <EvidenceLine
          label={labels.strategy}
          value={strategyDisplayNameFromId(strategyId, strategyNames)}
        />
        {strategyAuditId ? (
          <EvidenceLine
            label={labels.strategyAuditId}
            value={strategyAuditId}
          />
        ) : null}
        <EvidenceLine
          label={labels.targetWeight}
          value={formatPercent(candidate.target_weight)}
        />
        <EvidenceLine
          label={labels.price}
          value={formatPrice(candidate.price)}
        />
        <EvidenceLine
          label={labels.riskDecision}
          value={String(candidate.evidence.risk_gate.decision_id ?? '--')}
        />
        {riskGateReasons.length > 0 ? (
          <EvidenceLine
            label={formatPublicCode('risk_block_evidence', locale)}
            value={riskGateReasons.join('；')}
            tone={decisionTone(candidate.evidence.risk_gate.status)}
          />
        ) : null}
      </div>

      <CandidateEvidenceChain candidate={candidate} />
    </article>
  );
}

function CandidateEvidenceChain({
  candidate,
}: {
  candidate: DecisionCandidate;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const strategyNames = copy.backtest.page.strategyNames;
  const { locale } = usePreferences();
  const items = candidateEvidenceChainItems(
    candidate,
    locale,
    labels,
    strategyNames,
  );
  return (
    <div className="mt-4 min-w-0 rounded-[18px] border border-[color-mix(in_srgb,var(--app-border)_45%,transparent)] bg-[color-mix(in_srgb,var(--app-mantle)_32%,transparent)] p-3">
      <div className="text-xs font-semibold tracking-[0.08em] text-[var(--app-muted)] uppercase">
        {labels.candidateEvidenceChain}
      </div>
      <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-3">
        {items.map((item) => (
          <EvidenceChainCell key={item.label} item={item} />
        ))}
      </div>
    </div>
  );
}

function EvidenceChainCell({ item }: { item: CandidateEvidenceChainItem }) {
  const textColor =
    item.tone === 'success'
      ? 'text-[var(--app-success)]'
      : item.tone === 'danger'
        ? 'text-[var(--app-danger)]'
        : item.tone === 'warning'
          ? 'text-[var(--app-warning)]'
          : 'text-[var(--app-text)]';
  return (
    <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_38%,transparent)] px-3 py-2">
      <div className="app-muted text-[11px]">{item.label}</div>
      <div className={`mt-1 break-words text-sm font-semibold ${textColor}`}>
        {item.value}
      </div>
    </div>
  );
}

function StatusPill({ value, prefix }: { value: string; prefix?: string }) {
  const { locale } = usePreferences();
  const tone = decisionTone(value);
  const label = normalizeStatus(value, locale);
  return (
    <span
      className={`min-w-0 rounded-full border px-2.5 py-1 text-xs font-semibold break-words ${
        tone === 'success'
          ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]'
          : tone === 'danger'
            ? 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]'
            : 'border-[color-mix(in_srgb,var(--app-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] text-[var(--app-warning)]'
      }`}
    >
      {prefix ? `${prefix}: ${label}` : label}
    </span>
  );
}

function EvidenceLine({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'success' | 'warning' | 'danger' | 'neutral';
}) {
  const textColor =
    tone === 'success'
      ? 'text-[var(--app-success)]'
      : tone === 'danger'
        ? 'text-[var(--app-danger)]'
        : tone === 'warning'
          ? 'text-[var(--app-warning)]'
          : 'text-[var(--app-text)]';
  return (
    <div
      data-testid="decision-evidence-line"
      className="min-w-0 rounded-2xl bg-[color-mix(in_srgb,var(--app-mantle)_42%,transparent)] px-3 py-2"
    >
      <div className="app-muted break-words text-[11px] uppercase">{label}</div>
      <div className={`mt-1 break-words text-sm font-semibold ${textColor}`}>
        {label}: {value}
      </div>
    </div>
  );
}
