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
  type AutomationCockpitResponse,
  type BrokerConnectorHealthResponse,
  type ExecutionReconciliationRun,
  type ExecutionReconciliationItem,
  type BrokerGatewayAccountFactsResponse,
  type BrokerGatewayCapability,
  type BrokerGatewayFillsQueryResponse,
  type BrokerGatewayOrderQueryResponse,
  type BrokerGatewayStatusResponse,
  type OperationsTodayResponse,
  type PaperShadowCostSummary,
  type PaperShadowDivergenceSummary,
  type PaperShadowReviewQueueItem,
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

function numericCostSummaryValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function paperShadowCostSummaryItems(
  costSummary: PaperShadowCostSummary | undefined,
  locale: Locale,
) {
  if (!costSummary) {
    return [];
  }
  const labels =
    locale === 'zh'
      ? {
          estimatedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          simulatedSlippage: '模拟滑点',
          simulatedTotal: '模拟总成本',
          feeRules: '费用规则',
        }
      : {
          estimatedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          simulatedSlippage: 'Sim slippage',
          simulatedTotal: 'Sim total cost',
          feeRules: 'Fee rules',
        };
  const feeRuleIds = (costSummary.fee_rule_ids ?? [])
    .map((item) => String(item).trim())
    .filter(Boolean);
  return [
    {
      label: labels.estimatedFee,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.estimated_total_fee),
      ),
    },
    {
      label: labels.simulatedFeeTax,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.simulated_fee_tax_cost),
      ),
    },
    {
      label: labels.simulatedSlippage,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.simulated_slippage_cost),
      ),
    },
    {
      label: labels.simulatedTotal,
      value: formatCurrency(
        numericCostSummaryValue(costSummary.simulated_total_execution_cost),
      ),
    },
    feeRuleIds.length
      ? {
          label: labels.feeRules,
          value: feeRuleIds.join(' / '),
        }
      : null,
  ].filter((item): item is { label: string; value: string } => item !== null);
}

type PaperShadowDivergenceEvidenceBlock = {
  title: string;
  items: string[];
};

type BrokerTradeCostEvidence = {
  eventCountLabel: string;
  items: Array<{ label: string; value: string }>;
  safetyLabels: string[];
};

type ManualExecutionEvidence = {
  eventCountLabel: string;
  fingerprint: string;
  items: Array<{ label: string; value: string }>;
  safetyLabels: string[];
};

function objectRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatPaperShadowCountKey(value: string, locale: Locale) {
  const normalized = value.trim();
  if (!normalized) {
    return '--';
  }
  return normalized
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .toLocaleLowerCase(locale);
}

function formatPaperShadowCountMap(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  const items = Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(
      ([key, value]) => `${formatPaperShadowCountKey(key, locale)}: ${value}`,
    );
  return items.join(locale === 'zh' ? '；' : '; ');
}

function formatPaperShadowStatusCountMap(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  const items = Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([key, value]) => `${formatPublicStatus(key, locale)}: ${value}`);
  return items.join(locale === 'zh' ? '；' : '; ');
}

function formatPaperShadowValueMap(
  values: Record<string, number | string> | undefined,
) {
  const items = Object.entries(values ?? {})
    .map(([key, value]) => `${key}: ${String(value).trim()}`)
    .filter((value) => value.trim().length > 0);
  return items.join('; ');
}

function formatPaperShadowRefs(values: string[] | undefined, locale: Locale) {
  return (values ?? [])
    .map((value) => formatPublicEvidenceReference(value, locale))
    .filter((value) => value.trim().length > 0)
    .join(locale === 'zh' ? '；' : '; ');
}

function formatPaperShadowCurrencyList(
  values: Array<number | string> | undefined,
) {
  return (values ?? [])
    .map((value) => formatCurrency(numericCostSummaryValue(value)))
    .filter((value) => value !== '--')
    .join(', ');
}

function paperShadowMarketContextItems(
  summary: PaperShadowDivergenceSummary,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          symbolCount: '标的数',
          priceBasis: '价格依据',
          expected: '预期',
          fills: '成交',
          slippage: '滑点',
        }
      : {
          symbolCount: 'Symbols',
          priceBasis: 'Price basis',
          expected: 'expected',
          fills: 'fills',
          slippage: 'slippage',
        };
  const context = summary.realized_market_context;
  const priceBasis = formatPaperShadowCountMap(
    context?.price_basis_counts,
    locale,
  );
  return [
    typeof context?.symbol_count === 'number'
      ? `${labels.symbolCount}: ${context.symbol_count}`
      : '',
    priceBasis ? `${labels.priceBasis}: ${priceBasis}` : '',
    ...(context?.symbols ?? []).map((item) => {
      const symbol = item.symbol?.trim() || '--';
      const expected = formatCurrency(
        numericCostSummaryValue(item.expected_price),
      );
      const fills = formatPaperShadowCurrencyList(item.simulated_fill_prices);
      const slippage = formatCurrency(
        numericCostSummaryValue(item.simulated_slippage_cost),
      );
      return [
        symbol,
        expected !== '--' ? `${labels.expected} ${expected}` : '',
        fills ? `${labels.fills} ${fills}` : '',
        slippage !== '--' ? `${labels.slippage} ${slippage}` : '',
      ]
        .filter(Boolean)
        .join(' · ');
    }),
  ].filter(Boolean);
}

function paperShadowDivergenceEvidenceBlocks(
  summary: PaperShadowDivergenceSummary | undefined,
  locale: Locale,
): PaperShadowDivergenceEvidenceBlock[] {
  if (!summary) {
    return [];
  }
  const labels =
    locale === 'zh'
      ? {
          expectedTitle: '预期策略行为',
          executionTitle: '模拟执行对比',
          marketTitle: '实际行情上下文',
          safetyTitle: '安全边界',
          expectedOrders: '预期订单',
          decision: '决策',
          symbols: '标的',
          sides: '方向',
          strategies: '策略证据',
          risk: '风控证据',
          signals: '信号证据',
          riskGateStatuses: '风控状态',
          manualStatuses: '人工确认状态',
          submissionStatuses: '提交状态',
          matchedOrders: '匹配订单',
          missingIntents: '缺失订单意图',
          divergedOrders: '偏差订单',
          failedOrders: '失败订单',
          simStatuses: '模拟状态',
          fillCounts: '成交笔数',
          filledQty: '已成交数量',
          remainingQty: '剩余数量',
          noBrokerSubmission: '仅模拟证据；不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          expectedTitle: 'Expected strategy behavior',
          executionTitle: 'Execution comparison',
          marketTitle: 'Realized market context',
          safetyTitle: 'Safety boundaries',
          expectedOrders: 'Expected orders',
          decision: 'Decision',
          symbols: 'Symbols',
          sides: 'Sides',
          strategies: 'Strategy refs',
          risk: 'Risk refs',
          signals: 'Signal refs',
          riskGateStatuses: 'Risk gate statuses',
          manualStatuses: 'Manual confirmation statuses',
          submissionStatuses: 'Submission statuses',
          matchedOrders: 'Matched orders',
          missingIntents: 'Missing intents',
          divergedOrders: 'Diverged orders',
          failedOrders: 'Failed orders',
          simStatuses: 'Sim statuses',
          fillCounts: 'Fill counts',
          filledQty: 'Filled qty',
          remainingQty: 'Remaining qty',
          noBrokerSubmission: 'Simulation evidence only; no broker submission',
          noLedgerMutation: 'Does not mutate production ledger',
        };
  const expected = summary.expected_strategy_behavior;
  const execution = summary.execution_comparison;
  const expectedSides = formatPaperShadowStatusCountMap(
    expected?.side_counts,
    locale,
  );
  const riskGateStatuses = formatPaperShadowStatusCountMap(
    expected?.risk_gate_status_counts,
    locale,
  );
  const manualStatuses = formatPaperShadowStatusCountMap(
    expected?.manual_confirmation_status_counts,
    locale,
  );
  const submissionStatuses = formatPaperShadowCountMap(
    expected?.submission_status_counts,
    locale,
  );
  const simStatuses = formatPaperShadowCountMap(
    execution?.simulated_status_counts,
    locale,
  );
  const blocks: PaperShadowDivergenceEvidenceBlock[] = [];
  const expectedItems = [
    typeof expected?.expected_order_count === 'number'
      ? `${labels.expectedOrders}: ${expected.expected_order_count}`
      : '',
    expected?.source_decision
      ? `${labels.decision}: ${formatPublicStatus(
          expected.source_decision,
          locale,
        )}`
      : '',
    expected?.symbols?.length
      ? `${labels.symbols}: ${expected.symbols.join(', ')}`
      : '',
    expectedSides ? `${labels.sides}: ${expectedSides}` : '',
    formatPaperShadowRefs(expected?.strategy_refs, locale)
      ? `${labels.strategies}: ${formatPaperShadowRefs(
          expected?.strategy_refs,
          locale,
        )}`
      : '',
    formatPaperShadowRefs(expected?.risk_refs, locale)
      ? `${labels.risk}: ${formatPaperShadowRefs(expected?.risk_refs, locale)}`
      : '',
    formatPaperShadowRefs(expected?.signal_refs, locale)
      ? `${labels.signals}: ${formatPaperShadowRefs(
          expected?.signal_refs,
          locale,
        )}`
      : '',
    riskGateStatuses ? `${labels.riskGateStatuses}: ${riskGateStatuses}` : '',
    manualStatuses ? `${labels.manualStatuses}: ${manualStatuses}` : '',
    submissionStatuses
      ? `${labels.submissionStatuses}: ${submissionStatuses}`
      : '',
  ].filter(Boolean);
  if (expectedItems.length > 0) {
    blocks.push({ title: labels.expectedTitle, items: expectedItems });
  }

  const missingIntents = formatPaperShadowRefs(
    execution?.missing_order_intent_refs,
    locale,
  );
  const divergedOrders = formatPaperShadowRefs(
    execution?.diverged_order_refs,
    locale,
  );
  const failedOrders = formatPaperShadowRefs(
    execution?.failed_order_refs,
    locale,
  );
  const executionItems = [
    typeof execution?.matched_order_count === 'number'
      ? `${labels.matchedOrders}: ${execution.matched_order_count}`
      : '',
    missingIntents ? `${labels.missingIntents}: ${missingIntents}` : '',
    divergedOrders ? `${labels.divergedOrders}: ${divergedOrders}` : '',
    failedOrders ? `${labels.failedOrders}: ${failedOrders}` : '',
    simStatuses ? `${labels.simStatuses}: ${simStatuses}` : '',
    formatPaperShadowValueMap(execution?.fill_count_by_order)
      ? `${labels.fillCounts}: ${formatPaperShadowValueMap(
          execution?.fill_count_by_order,
        )}`
      : '',
    formatPaperShadowValueMap(execution?.filled_quantity_by_order)
      ? `${labels.filledQty}: ${formatPaperShadowValueMap(
          execution?.filled_quantity_by_order,
        )}`
      : '',
    formatPaperShadowValueMap(execution?.remaining_quantity_by_order)
      ? `${labels.remainingQty}: ${formatPaperShadowValueMap(
          execution?.remaining_quantity_by_order,
        )}`
      : '',
  ].filter(Boolean);
  if (executionItems.length > 0) {
    blocks.push({ title: labels.executionTitle, items: executionItems });
  }

  const marketItems = paperShadowMarketContextItems(summary, locale);
  if (marketItems.length > 0) {
    blocks.push({ title: labels.marketTitle, items: marketItems });
  }

  const safetyItems = [
    summary.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    summary.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);
  if (safetyItems.length > 0) {
    blocks.push({ title: labels.safetyTitle, items: safetyItems });
  }
  return blocks;
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
    running: { en: 'Running', zh: '运行中' },
    within_expectations: { en: 'Within expectations', zh: '符合预期' },
    accepted_for_manual_confirmation: {
      en: 'Accepted for manual confirmation',
      zh: '已接受，可人工确认',
    },
    diverged: { en: 'Diverged', zh: '存在偏差' },
    failed: { en: 'Failed', zh: '运行失败' },
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
    wait_for_paper_shadow_run: {
      en: 'Paper/shadow simulation is running; wait for completion',
      zh: 'Paper/shadow 模拟正在运行，等待完成',
    },
    review_manual_confirmation: {
      en: 'Simulation reviewed; continue with manual confirmation',
      zh: '模拟已复核，可继续人工确认',
    },
    resolve_shadow_divergence: {
      en: 'Resolve simulation divergence before approval',
      zh: '批准前先处理模拟偏差',
    },
    inspect_failed_run: {
      en: 'Inspect failed paper/shadow run before approval',
      zh: '批准前先检查失败的 paper/shadow 运行',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function paperShadowManualHandoffStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    ready_after_accepted_review: {
      en: 'Ready after accepted simulation review',
      zh: '已接受模拟复核，可人工确认',
    },
    ready_after_clean_simulation: {
      en: 'Ready after clean simulation',
      zh: '模拟无偏差，可人工确认',
    },
    blocked_by_unresolved_divergence: {
      en: 'Blocked by unresolved simulation divergence',
      zh: '模拟偏差未处理，暂不可人工确认',
    },
    blocked_by_failed_run: {
      en: 'Blocked by failed simulation run',
      zh: '模拟运行失败，暂不可人工确认',
    },
    blocked_by_review_requested_rerun: {
      en: 'Blocked until simulation reruns',
      zh: '需要重新运行模拟后再确认',
    },
    paper_shadow_required: {
      en: 'Simulation required before manual confirmation',
      zh: '人工确认前需要模拟复核',
    },
    waiting_for_paper_shadow_run: {
      en: 'Waiting for simulation result',
      zh: '等待模拟复核结果',
    },
    not_required: {
      en: 'No manual handoff required',
      zh: '无需人工确认交接',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function paperShadowManualHandoffEvidenceItems(
  handoff: NonNullable<
    OperationsTodayResponse['paper_shadow']['manual_handoff']
  >,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          title: '人工确认交接',
          next: '下一步',
          queue: '复核队列',
          item: '项',
          items: '项',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          title: 'Manual handoff',
          next: 'Next',
          queue: 'Review queue',
          item: 'item',
          items: 'items',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const actions = (handoff.required_actions ?? [])
    .filter((action) => action && action !== 'none')
    .map((action) => paperShadowNextStepLabel(action, locale));
  const queueCount = handoff.review_queue_count ?? 0;
  return [
    `${labels.title}: ${paperShadowManualHandoffStatusLabel(
      handoff.status,
      locale,
    )}`,
    actions.length ? `${labels.next}: ${actions.join(' · ')}` : '',
    queueCount > 0
      ? `${labels.queue}: ${queueCount} ${
          queueCount === 1 ? labels.item : labels.items
        }`
      : '',
    handoff.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    handoff.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);
}

function paperShadowReviewQueueItemTitle(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const primary =
    item.symbol?.trim() ||
    (item.order_id
      ? formatPublicEvidenceReference(
          `paper_shadow_order:${item.order_id}`,
          locale,
        )
      : '');
  return [primary, paperShadowNextStepLabel(item.required_action, locale)]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowReviewQueueSafetyText(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const labels: string[] = [];
  if (item.does_not_submit_broker_order) {
    labels.push(locale === 'zh' ? '不会提交券商订单' : 'No broker submission');
  }
  if (item.does_not_mutate_production_ledger) {
    labels.push(
      locale === 'zh' ? '不会修改生产账本' : 'No production ledger mutation',
    );
  }
  return labels.join(' · ');
}

function paperShadowReviewQueueDetailItems(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          risk: '风控',
          manual: '人工确认',
          accountTruth: '账户事实',
          cash: '现金',
          constraints: '约束',
          projectedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          simulatedSlippage: '模拟滑点',
          expected: '预期',
          fill: '成交',
          terminalOutcome: '终态结果',
          omsPath: 'OMS 路径',
          omsTransition: 'OMS 状态变更',
          evidence: '证据',
        }
      : {
          risk: 'Risk',
          manual: 'Manual',
          accountTruth: 'Account truth',
          cash: 'Cash',
          constraints: 'Constraints',
          projectedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          simulatedSlippage: 'Sim slippage',
          expected: 'Expected',
          fill: 'Fill',
          terminalOutcome: 'Terminal outcome',
          omsPath: 'OMS path',
          omsTransition: 'OMS transition',
          evidence: 'Evidence',
        };
  const riskManual = [
    item.risk_gate_status
      ? `${labels.risk} ${formatPublicStatus(item.risk_gate_status, locale)}`
      : '',
    item.manual_confirmation_status
      ? `${labels.manual} ${reviewQueueManualStatusLabel(
          item.manual_confirmation_status,
          locale,
        )}`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const accountCash = [
    item.account_truth?.gate_status
      ? `${labels.accountTruth} ${formatPublicStatus(
          item.account_truth.gate_status,
          locale,
        )}`
      : '',
    item.cash_status
      ? `${labels.cash} ${formatPublicStatus(item.cash_status, locale)}`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const constraints = formatPaperShadowStatusCountMap(
    item.constraint_status_counts,
    locale,
  );
  const costEvidence = [
    reviewQueueCurrencyItem(
      labels.projectedFee,
      item.cost_evidence?.estimated_total_fee,
    ),
    reviewQueueCurrencyItem(
      labels.simulatedFeeTax,
      item.cost_evidence?.simulated_fee_tax_cost,
    ),
    reviewQueueCurrencyItem(
      labels.simulatedSlippage,
      item.cost_evidence?.simulated_slippage_cost,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const marketContext = [
    reviewQueueCurrencyItem(
      labels.expected,
      item.market_context?.expected_price,
    ),
    reviewQueueFillPriceItem(
      labels.fill,
      item.market_context?.simulated_fill_prices,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const omsStatusPath = reviewQueueOmsStatusPath(item.oms_status_path, locale);
  const terminalOutcome = reviewQueueTerminalOutcomeSummary(item, locale);
  const omsTransition = reviewQueueLatestOmsTransition(item, locale);
  const evidenceRefs = formatPaperShadowRefs(
    item.evidence_refs ?? [
      ...(item.strategy_refs ?? []),
      ...(item.risk_refs ?? []),
      ...(item.signal_refs ?? []),
    ],
    locale,
  );
  return [
    riskManual,
    accountCash,
    constraints ? `${labels.constraints} ${constraints}` : '',
    costEvidence,
    marketContext,
    terminalOutcome ? `${labels.terminalOutcome}: ${terminalOutcome}` : '',
    omsStatusPath ? `${labels.omsPath}: ${omsStatusPath}` : '',
    omsTransition ? `${labels.omsTransition}: ${omsTransition}` : '',
    evidenceRefs ? `${labels.evidence}: ${evidenceRefs}` : '',
  ].filter(Boolean);
}

function reviewQueueTerminalOutcomeSummary(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const status = reviewQueueOmsStatusLabel(
    item.terminal_status ?? undefined,
    locale,
  );
  const reason = reviewQueueTerminalReasonLabel(
    item.terminal_reason ?? undefined,
    locale,
  );
  const transition = item.terminal_oms_transition_ref
    ? formatPublicEvidenceReference(item.terminal_oms_transition_ref, locale)
    : '';
  return [status, reason, transition].filter(Boolean).join(' · ');
}

function reviewQueueTerminalReasonLabel(
  reason: string | undefined,
  locale: Locale,
) {
  const normalized = String(reason ?? '').trim();
  if (!normalized) {
    return '';
  }
  const labels: Record<string, Record<Locale, string>> = {
    operator_cancelled: {
      en: 'Operator cancelled simulation before fill',
      zh: '操作员在模拟成交前取消',
    },
    paper_session_closed: {
      en: 'Paper session closed before fill',
      zh: '模拟交易时段结束，未成交前过期',
    },
  };
  return labels[normalized]?.[locale] ?? formatPublicStatus(normalized, locale);
}

function reviewQueueOmsStatusPath(
  values: string[] | undefined,
  locale: Locale,
) {
  if (!values || values.length === 0) {
    return '';
  }
  return values
    .map((value) => reviewQueueOmsStatusLabel(value, locale))
    .filter(Boolean)
    .join(' > ');
}

function reviewQueueLatestOmsTransition(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const transition = [...(item.oms_transitions ?? [])]
    .reverse()
    .find((entry) => entry.to_status);
  if (!transition?.to_status) {
    return '';
  }
  const orderId = item.order_id ? `${item.order_id} ` : '';
  const sequence =
    transition.sequence !== null && transition.sequence !== undefined
      ? `#${transition.sequence} `
      : '';
  return `${orderId}${sequence}${reviewQueueOmsStatusLabel(
    transition.to_status,
    locale,
  )}`;
}

function reviewQueueOmsStatusLabel(
  value: string | null | undefined,
  locale: Locale,
) {
  const status = String(value ?? '').trim();
  if (!status) {
    return '';
  }
  const labels: Record<string, Record<Locale, string>> = {
    staged: { en: 'Staged', zh: '已暂存' },
    submitted: { en: 'Submitted', zh: '已提交模拟' },
    accepted: { en: 'Accepted', zh: '已接受模拟' },
    partially_filled: { en: 'Partially Filled', zh: '部分成交' },
    filled: { en: 'Filled', zh: '已成交' },
    rejected: { en: 'Rejected', zh: '已拒绝' },
    cancelled: { en: 'Cancelled', zh: '已取消' },
    expired: { en: 'Expired', zh: '已过期' },
    reconciled: { en: 'Reconciled', zh: '已对账' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function reviewQueueManualStatusLabel(value: string, locale: Locale) {
  if (value === 'ready_for_manual_confirmation') {
    return locale === 'zh' ? '可人工确认' : 'Ready';
  }
  return formatPublicStatus(value, locale);
}

function reviewQueueCurrencyItem(label: string, value: unknown) {
  const numeric = numericCostSummaryValue(value);
  return numeric === null ? '' : `${label} ${formatCurrency(numeric)}`;
}

function reviewQueueFillPriceItem(
  label: string,
  values: unknown[] | undefined,
) {
  const prices = (values ?? [])
    .map((value) => numericCostSummaryValue(value))
    .filter((value): value is number => value !== null)
    .map((value) => formatCurrency(value));
  return prices.length ? `${label} ${prices.join(', ')}` : '';
}

function automationModeLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    paper_shadow: { en: 'paper/shadow only', zh: '仅 paper/shadow' },
    manual_confirmation: { en: 'manual confirmation', zh: '人工确认' },
    disabled: { en: 'disabled', zh: '已停用' },
    live_like: { en: 'live-like gated', zh: '类实盘门禁' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function automationExecutionMode(cockpit: AutomationCockpitResponse) {
  return (
    cockpit.automation_status.mode ??
    cockpit.automation_status.default_execution_mode ??
    '--'
  );
}

function strategyPromotionStageLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    research: { en: 'Research', zh: '研究' },
    paper_shadow: { en: 'Paper/shadow', zh: '模拟/影子运行' },
    shadow: { en: 'Shadow', zh: '影子运行' },
    manual_confirmation: { en: 'Manual confirmation', zh: '人工确认' },
    controlled_bridge_pilot: {
      en: 'Controlled bridge pilot',
      zh: '受控桥接试点',
    },
    paused: { en: 'Paused', zh: '已暂停' },
    retired: { en: 'Retired', zh: '已退役' },
    live_like: { en: 'Live-like gated', zh: '类实盘门禁' },
    live_like_blocked: { en: 'Live-like blocked', zh: '类实盘已阻断' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function strategyPromotionGateStatusLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    blocked: { en: 'Blocked', zh: '已阻断' },
    paper_shadow_ready: {
      en: 'Paper/shadow ready',
      zh: '模拟/影子运行就绪',
    },
    paper_shadow_enabled: {
      en: 'Paper/shadow enabled',
      zh: '模拟/影子运行已启用',
    },
    live_like_disabled: {
      en: 'Live-like disabled',
      zh: '类实盘已关闭',
    },
    paused: { en: 'Paused', zh: '已暂停' },
    retired: { en: 'Retired', zh: '已退役' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function strategyPromotionLifecycleLabels(
  lifecycle:
    | NonNullable<
        AutomationCockpitResponse['promotion_states'][number]['lifecycle']
      >
    | undefined,
  locale: Locale,
) {
  if (!lifecycle) {
    return [];
  }
  const labels: string[] = [];
  if (lifecycle.audit_only) {
    labels.push(locale === 'zh' ? '生命周期仅审计' : 'Lifecycle audit only');
  }
  if (lifecycle.does_not_authorize_execution) {
    labels.push(
      locale === 'zh' ? '不授权执行' : 'Does not authorize execution',
    );
  }
  if (lifecycle.terminal) {
    labels.push(locale === 'zh' ? '终止状态' : 'Terminal state');
  }
  for (const disabledStage of lifecycle.disabled_stages ?? []) {
    if (disabledStage === 'controlled_bridge_pilot') {
      labels.push(
        locale === 'zh'
          ? '受控桥接试点已关闭'
          : 'Controlled bridge pilot disabled',
      );
    } else if (disabledStage === 'live_like') {
      labels.push(locale === 'zh' ? '类实盘已关闭' : 'Live-like disabled');
    } else {
      labels.push(
        `${strategyPromotionStageLabel(disabledStage, locale)} ${
          locale === 'zh' ? '已关闭' : 'disabled'
        }`,
      );
    }
  }
  return labels;
}

function strategyPromotionMissingRequirementsLabel(
  missingRequirements: string[] | undefined,
  locale: Locale,
) {
  const items = (missingRequirements ?? [])
    .map((item) => formatPublicStatus(item, locale))
    .filter(Boolean);
  if (!items.length) {
    return locale === 'zh' ? '无缺失要求' : 'No missing requirements';
  }
  return items.join(locale === 'zh' ? '；' : '; ');
}

function automationRecommendedActionLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    import_broker_evidence: {
      en: 'import broker evidence',
      zh: '导入券商证据',
    },
    review_manual_confirmation: {
      en: 'review manual confirmation',
      zh: '复核人工确认',
    },
    review_broker_evidence_match: {
      en: 'review broker evidence match',
      zh: '复核券商证据匹配',
    },
    create_manual_ticket: { en: 'create manual ticket', zh: '生成手工下单票' },
    review_gateway_status: { en: 'review gateway status', zh: '复核网关状态' },
    import_broker_statement_or_update_order: {
      en: 'import broker statement or update order',
      zh: '导入券商交割单或更新订单',
    },
    create_manual_ticket_or_cancel: {
      en: 'create manual ticket or cancel',
      zh: '创建手工票据或取消订单',
    },
    confirm_or_cancel_order: {
      en: 'confirm or cancel order',
      zh: '确认或取消订单',
    },
    inspect_failed_paper_shadow_run: {
      en: 'inspect failed paper/shadow run',
      zh: '检查失败的 paper/shadow 运行',
    },
    inspect_scheduler_failure: {
      en: 'inspect scheduler failure',
      zh: '检查调度失败',
    },
    inspect_failed_automation_run: {
      en: 'inspect failed automation run',
      zh: '检查失败的自动化运行',
    },
    review_broker_evidence_mismatch: {
      en: 'review broker evidence mismatch',
      zh: '复核券商证据不匹配',
    },
    paper_shadow_available: {
      en: 'run intraday paper/shadow',
      zh: '运行盘中 paper/shadow',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function automationNextAction(
  cockpit: AutomationCockpitResponse,
  locale: Locale,
) {
  if (cockpit.automation_status.kill_switch_enabled) {
    return locale === 'zh' ? '先处理全局熔断' : 'resolve global kill switch';
  }
  const brokerEvidenceItem =
    cockpit.execution_reconciliation_open_items.find(
      (item) => item.recommended_action === 'import_broker_evidence',
    ) ?? cockpit.execution_reconciliation_open_items[0];
  if (brokerEvidenceItem) {
    return automationRecommendedActionLabel(
      brokerEvidenceItem.recommended_action,
      locale,
    );
  }
  const primaryAlertAction = automationOpenAlertSuggestedAction(
    cockpit.open_alerts[0],
  );
  if (primaryAlertAction) {
    return automationRecommendedActionLabel(primaryAlertAction, locale);
  }
  if (cockpit.open_alert_count > 0) {
    return locale === 'zh' ? '复核自动化告警' : 'review automation alerts';
  }
  if (cockpit.automation_status.next_action) {
    return automationRecommendedActionLabel(
      cockpit.automation_status.next_action,
      locale,
    );
  }
  return locale === 'zh'
    ? '运行盘中 paper/shadow'
    : 'run intraday paper/shadow';
}

function automationOpenAlertSuggestedAction(
  alert: AutomationCockpitResponse['open_alerts'][number] | undefined,
) {
  const payload = objectRecord(alert?.payload);
  const suggestedAction = payload?.suggested_action;
  return typeof suggestedAction === 'string' && suggestedAction.trim()
    ? suggestedAction.trim()
    : '';
}

function automationOpenAlertReviewLabels(
  payload: Record<string, unknown> | null,
  locale: Locale,
) {
  const labels: string[] = [];
  const suggestedAction =
    typeof payload?.suggested_action === 'string'
      ? payload.suggested_action.trim()
      : '';
  if (suggestedAction) {
    labels.push(automationRecommendedActionLabel(suggestedAction, locale));
  }
  if (payload?.requires_manual_review === true) {
    labels.push(locale === 'zh' ? '需要人工复核' : 'Manual review required');
  }
  if (payload?.retry_recommended === true) {
    labels.push(locale === 'zh' ? '建议重试' : 'Retry recommended');
  }
  if (payload?.does_not_submit_broker_order === true) {
    labels.push(locale === 'zh' ? '不会提交券商订单' : 'No broker submission');
  }
  if (payload?.does_not_mutate_production_ledger === true) {
    labels.push(locale === 'zh' ? '不会改写账本' : 'No ledger mutation');
  }
  return labels;
}

function brokerGatewayDisplayName(
  gateway: BrokerGatewayCapability,
  locale: Locale,
) {
  if (gateway.gateway_id === 'manual_ticket') {
    return locale === 'zh' ? '人工工单' : 'Manual ticket';
  }
  if (gateway.gateway_id === 'live_disabled') {
    return locale === 'zh' ? '实盘券商执行' : 'Live broker execution';
  }
  if (gateway.gateway_id === 'staged_broker_evidence') {
    return locale === 'zh' ? '已暂存券商证据' : 'Staged broker evidence';
  }
  if (gateway.display_name) return gateway.display_name;
  return formatPublicStatus(gateway.gateway_id, locale);
}

function brokerGatewayStatusLabel(status: string, locale: Locale) {
  if (status === 'blocked_by_kill_switch') {
    return locale === 'zh' ? '被熔断开关阻断' : 'Blocked by kill switch';
  }
  return formatPublicStatus(status, locale);
}

function controlledBridgePolicyStatusLabel(status: string, locale: Locale) {
  if (status === 'configured_non_submitting') {
    return locale === 'zh' ? '已配置，不提交' : 'Configured, no submission';
  }
  if (status === 'incomplete_whitelist') {
    return locale === 'zh' ? '白名单不完整' : 'Incomplete whitelist';
  }
  return formatPublicStatus(status, locale);
}

function controlledBridgeListSummary(
  label: 'connector' | 'account' | 'strategy' | 'symbol',
  values: string[] | undefined,
  locale: Locale,
) {
  const labelText =
    label === 'connector'
      ? locale === 'zh'
        ? '连接器'
        : 'Connector'
      : label === 'account'
        ? locale === 'zh'
          ? '账户'
          : 'Account'
        : label === 'strategy'
          ? locale === 'zh'
            ? '策略'
            : 'Strategy'
          : locale === 'zh'
            ? '标的'
            : 'Symbol';
  const displayValues = values?.length
    ? values.join(', ')
    : locale === 'zh'
      ? '未配置'
      : 'not configured';
  return `${labelText}: ${displayValues}`;
}

function controlledBridgeTokenList(
  values: string[] | undefined,
  locale: Locale,
) {
  if (values?.length) {
    return values
      .map((value) => controlledBridgeTokenLabel(value, locale))
      .join(', ');
  }
  return locale === 'zh' ? '无' : 'none';
}

function controlledBridgeTokenLabel(value: string, locale: Locale) {
  const labels: Record<string, Record<Locale, string>> = {
    account_truth: { en: 'account truth', zh: '账户事实' },
    research_evidence: { en: 'research evidence', zh: '研究证据' },
    risk: { en: 'risk', zh: '风控' },
    paper_shadow: { en: 'paper/shadow', zh: '模拟/影子运行' },
    manual_confirmation: { en: 'manual confirmation', zh: '人工确认' },
    kill_switch_clear: { en: 'kill switch clear', zh: '熔断关闭' },
    connector_health: { en: 'connector health', zh: '连接器健康' },
    execution_reconciliation: {
      en: 'execution reconciliation',
      zh: '执行对账',
    },
    controlled_bridge_policy_disabled: {
      en: 'controlled bridge policy disabled',
      zh: '受控桥接策略未启用',
    },
    controlled_bridge_whitelist_empty: {
      en: 'controlled bridge whitelist empty',
      zh: '受控桥接白名单为空',
    },
    live_gateway_not_implemented: {
      en: 'live gateway not implemented',
      zh: '实盘网关尚未实现',
    },
  };
  return labels[value]?.[locale] ?? formatPublicCode(value, locale);
}

function brokerConnectorStatusLabel(status: string, locale: Locale) {
  if (status === 'configured_readonly_unverified') {
    return locale === 'zh'
      ? '只读配置完成，未连接验证'
      : 'Configured readonly unverified';
  }
  if (status === 'configuration_incomplete') {
    return locale === 'zh' ? '配置不完整' : 'Configuration incomplete';
  }
  return formatPublicStatus(status, locale);
}

function brokerGatewayCapabilityLabel(
  label:
    | 'preview'
    | 'export'
    | 'dry_run'
    | 'query_orders'
    | 'query_fills'
    | 'read_positions'
    | 'read_cash'
    | 'submit'
    | 'cancel',
  enabled: boolean | undefined,
  locale: Locale,
) {
  const action =
    label === 'preview'
      ? locale === 'zh'
        ? '预览'
        : 'Preview'
      : label === 'export'
        ? locale === 'zh'
          ? '导出'
          : 'Export'
        : label === 'dry_run'
          ? locale === 'zh'
            ? '干跑'
            : 'Dry run'
          : label === 'query_orders'
            ? locale === 'zh'
              ? '查询订单'
              : 'Query orders'
            : label === 'query_fills'
              ? locale === 'zh'
                ? '查询成交'
                : 'Query fills'
              : label === 'read_positions'
                ? locale === 'zh'
                  ? '读取持仓'
                  : 'Read positions'
                : label === 'read_cash'
                  ? locale === 'zh'
                    ? '读取资金'
                    : 'Read cash'
                  : label === 'submit'
                    ? locale === 'zh'
                      ? '提交'
                      : 'Submit'
                    : locale === 'zh'
                      ? '撤单'
                      : 'Cancel';
  const state = enabled
    ? locale === 'zh'
      ? '可用'
      : 'available'
    : locale === 'zh'
      ? '阻断'
      : 'blocked';
  return `${action} ${state}`;
}

function brokerConnectorCapabilityLabel(
  label:
    | 'read_account'
    | 'read_cash'
    | 'read_positions'
    | 'read_orders'
    | 'read_fills'
    | 'preview_orders'
    | 'export_tickets'
    | 'dry_run_orders'
    | 'submit'
    | 'cancel',
  enabled: boolean | undefined,
  locale: Locale,
) {
  const action =
    label === 'read_account'
      ? locale === 'zh'
        ? '读取账户'
        : 'Read account'
      : label === 'read_cash'
        ? locale === 'zh'
          ? '读取资金'
          : 'Read cash'
        : label === 'read_positions'
          ? locale === 'zh'
            ? '读取持仓'
            : 'Read positions'
          : label === 'read_orders'
            ? locale === 'zh'
              ? '读取订单'
              : 'Read orders'
            : label === 'read_fills'
              ? locale === 'zh'
                ? '读取成交'
                : 'Read fills'
              : label === 'preview_orders'
                ? locale === 'zh'
                  ? '预览订单'
                  : 'Preview orders'
                : label === 'export_tickets'
                  ? locale === 'zh'
                    ? '导出票据'
                    : 'Export tickets'
                  : label === 'dry_run_orders'
                    ? locale === 'zh'
                      ? 'Dry-run 订单'
                      : 'Dry-run orders'
                    : label === 'submit'
                      ? locale === 'zh'
                        ? '提交'
                        : 'Submit'
                      : locale === 'zh'
                        ? '撤单'
                        : 'Cancel';
  const state = enabled
    ? locale === 'zh'
      ? '可用'
      : 'available'
    : locale === 'zh'
      ? '阻断'
      : 'blocked';
  return `${action} ${state}`;
}

function runtimeConnectorSnapshotStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    snapshot_ready: { en: 'Snapshot ready', zh: '快照可复核' },
    snapshot_degraded: { en: 'Snapshot degraded', zh: '快照降级' },
    snapshot_unavailable: { en: 'Snapshot unavailable', zh: '快照不可用' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function executionReconciliationStatusLabel(status: string, locale: Locale) {
  if (status === 'open_items') {
    return locale === 'zh' ? '存在未处理项' : 'Open items';
  }
  if (status === 'clear') {
    return locale === 'zh' ? '已清理' : 'Clear';
  }
  return formatPublicStatus(status, locale);
}

function executionReconciliationItemStatusLabel(
  status: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    awaiting_manual_confirmation: {
      en: 'Awaiting manual confirmation',
      zh: '等待人工确认',
    },
    gateway_action_missing: {
      en: 'Gateway action missing',
      zh: '缺少网关动作',
    },
    broker_evidence_available: {
      en: 'Broker evidence available',
      zh: '券商证据可复核',
    },
    broker_evidence_mismatch: {
      en: 'Broker evidence mismatch',
      zh: '券商证据不匹配',
    },
    manual_execution_recorded: {
      en: 'Manual execution recorded',
      zh: '手工成交证据已记录',
    },
    awaiting_broker_evidence: {
      en: 'Awaiting broker evidence',
      zh: '等待券商证据',
    },
    cancelled: {
      en: 'Cancelled',
      zh: '已取消',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function omsOrderStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    awaiting_manual_confirmation: {
      en: 'Awaiting manual confirmation',
      zh: '等待人工确认',
    },
    manually_confirmed: {
      en: 'Manually confirmed',
      zh: '已人工确认',
    },
    manual_ticket_created: {
      en: 'Manual ticket created',
      zh: '已创建手工票据',
    },
    broker_submission_blocked: {
      en: 'Broker submission blocked',
      zh: '券商提交已阻断',
    },
    staged: {
      en: 'Staged',
      zh: '已暂存',
    },
    submitted: {
      en: 'Submitted',
      zh: '已提交',
    },
    accepted: {
      en: 'Accepted',
      zh: '已接受',
    },
    partially_filled: {
      en: 'Partially filled',
      zh: '部分成交',
    },
    filled: {
      en: 'Filled',
      zh: '已成交',
    },
    rejected: {
      en: 'Rejected',
      zh: '已拒绝',
    },
    cancelled: {
      en: 'Cancelled',
      zh: '已取消',
    },
    expired: {
      en: 'Expired',
      zh: '已过期',
    },
    reconciled: {
      en: 'Reconciled',
      zh: '已对账',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function executionReconciliationActionLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    import_broker_statement_or_update_order: {
      en: 'Import broker statement or update order',
      zh: '导入券商交割单或更新订单',
    },
    create_manual_ticket_or_cancel: {
      en: 'Create manual ticket or cancel',
      zh: '创建手工票据或取消订单',
    },
    confirm_or_cancel_order: {
      en: 'Confirm or cancel order',
      zh: '确认或取消订单',
    },
    review_broker_evidence_match: {
      en: 'Review broker evidence match',
      zh: '复核券商证据匹配',
    },
    review_broker_evidence_mismatch: {
      en: 'Review broker evidence mismatch',
      zh: '复核券商证据不匹配',
    },
    review_manual_execution_and_import_broker_statement: {
      en: 'Review manual execution and import broker statement',
      zh: '复核手工成交并导入券商交割单',
    },
    review_order_state: {
      en: 'Review order state',
      zh: '复核订单状态',
    },
  };
  return (
    labels[value]?.[locale] ?? automationRecommendedActionLabel(value, locale)
  );
}

function brokerTradeCostEvidenceForItem(
  item: ExecutionReconciliationItem | undefined,
  locale: Locale,
): BrokerTradeCostEvidence | null {
  const payload = objectRecord(item?.payload);
  const summary = objectRecord(payload?.broker_trade_cost_summary);
  if (!summary) {
    return null;
  }

  const labels =
    locale === 'zh'
      ? {
          brokerEvent: '条券商事件',
          brokerEventsUnavailable: '券商事件待复核',
          grossAmount: '成交总额',
          feeTax: '手续费 / 税费',
          transferFee: '过户费',
          netAmount: '净额',
          reviewRequired: '更新账本前需复核',
          noLedgerMutation: '不修改账本',
        }
      : {
          brokerEvent: 'broker event',
          brokerEventsUnavailable: 'Broker events need review',
          grossAmount: 'Gross amount',
          feeTax: 'Fee / tax',
          transferFee: 'Transfer fee',
          netAmount: 'Net amount',
          reviewRequired: 'Review before ledger update',
          noLedgerMutation: 'No ledger mutation',
        };
  const eventCountValue = numericCostSummaryValue(summary.event_count);
  const eventCount =
    eventCountValue === null ? 0 : Math.max(0, Math.trunc(eventCountValue));
  const grossAmount = formatCurrency(
    numericCostSummaryValue(summary.gross_amount),
  );
  const fee = formatCurrency(numericCostSummaryValue(summary.fee));
  const tax = formatCurrency(numericCostSummaryValue(summary.tax));
  const transferFee = formatCurrency(
    numericCostSummaryValue(summary.transfer_fee),
  );
  const netAmount = formatCurrency(numericCostSummaryValue(summary.net_amount));
  const items = [
    grossAmount !== '--'
      ? { label: labels.grossAmount, value: grossAmount }
      : null,
    fee !== '--' || tax !== '--'
      ? { label: labels.feeTax, value: `${fee} / ${tax}` }
      : null,
    transferFee !== '--'
      ? { label: labels.transferFee, value: transferFee }
      : null,
    netAmount !== '--' ? { label: labels.netAmount, value: netAmount } : null,
  ].filter(
    (entry): entry is { label: string; value: string } => entry !== null,
  );
  if (eventCount <= 0 && items.length === 0) {
    return null;
  }
  return {
    eventCountLabel:
      eventCount > 0
        ? countLabel(eventCount, labels.brokerEvent, 'broker events', locale)
        : labels.brokerEventsUnavailable,
    items,
    safetyLabels: [
      summary.review_required_before_ledger_update === true
        ? labels.reviewRequired
        : '',
      summary.does_not_mutate_production_ledger === true
        ? labels.noLedgerMutation
        : '',
    ].filter(Boolean),
  };
}

function manualExecutionEvidenceForItem(
  item: ExecutionReconciliationItem | undefined,
  locale: Locale,
): ManualExecutionEvidence | null {
  const payload = objectRecord(item?.payload);
  return manualExecutionEvidenceForPayload(payload, locale);
}

function manualExecutionEvidenceForPayload(
  payload: Record<string, unknown> | null,
  locale: Locale,
): ManualExecutionEvidence | null {
  const summary = objectRecord(payload?.manual_execution_evidence_summary);
  if (!summary) {
    return null;
  }

  const labels =
    locale === 'zh'
      ? {
          gatewayEvent: '个网关事件',
          gatewayEventsUnavailable: '网关事件待复核',
          previewFingerprint: 'Preview fingerprint',
          fillPrice: '成交价',
          quantity: '数量',
          grossAmount: '成交总额',
          feeTax: '手续费 / 税费',
          transferFee: '过户费',
          netCashImpact: '净现金影响',
          ledgerDraft: '账本草稿',
          reviewRequired: '更新账本前需复核',
          operatorSave: '需要人工保存账本',
          noBrokerSubmission: '不提交券商订单',
          noOmsMutation: '不修改 OMS',
          noLedgerMutation: '不修改账本',
        }
      : {
          gatewayEvent: 'gateway event',
          gatewayEventsUnavailable: 'Gateway events need review',
          previewFingerprint: 'Preview fingerprint',
          fillPrice: 'Fill price',
          quantity: 'Quantity',
          grossAmount: 'Gross amount',
          feeTax: 'Fee / tax',
          transferFee: 'Transfer fee',
          netCashImpact: 'Net cash impact',
          ledgerDraft: 'Ledger draft',
          reviewRequired: 'Review before ledger update',
          operatorSave: 'Operator ledger save required',
          noBrokerSubmission: 'No broker submission',
          noOmsMutation: 'No OMS mutation',
          noLedgerMutation: 'No ledger mutation',
        };
  const eventCountValue = numericCostSummaryValue(summary.event_count);
  const eventCount =
    eventCountValue === null ? 0 : Math.max(0, Math.trunc(eventCountValue));
  const fillPrice = formatCurrency(numericCostSummaryValue(summary.fill_price));
  const grossAmount = formatCurrency(
    numericCostSummaryValue(summary.gross_amount),
  );
  const fee = formatCurrency(numericCostSummaryValue(summary.fee));
  const tax = formatCurrency(numericCostSummaryValue(summary.tax));
  const transferFee = formatCurrency(
    numericCostSummaryValue(summary.transfer_fee),
  );
  const netCashImpact = formatCurrency(
    numericCostSummaryValue(summary.net_cash_impact),
  );
  const ledgerDraft = formatCurrency(
    numericCostSummaryValue(summary.ledger_entry_amount),
  );
  const quantity =
    typeof summary.quantity === 'string' && summary.quantity.trim()
      ? summary.quantity.trim()
      : typeof summary.quantity === 'number'
        ? String(summary.quantity)
        : '';
  const fingerprint =
    typeof summary.preview_fingerprint === 'string'
      ? summary.preview_fingerprint
      : '';
  const items = [
    fillPrice !== '--' ? { label: labels.fillPrice, value: fillPrice } : null,
    quantity ? { label: labels.quantity, value: quantity } : null,
    grossAmount !== '--'
      ? { label: labels.grossAmount, value: grossAmount }
      : null,
    fee !== '--' || tax !== '--'
      ? { label: labels.feeTax, value: `${fee} / ${tax}` }
      : null,
    transferFee !== '--'
      ? { label: labels.transferFee, value: transferFee }
      : null,
    netCashImpact !== '--'
      ? { label: labels.netCashImpact, value: netCashImpact }
      : null,
    ledgerDraft !== '--'
      ? { label: labels.ledgerDraft, value: ledgerDraft }
      : null,
  ].filter(
    (entry): entry is { label: string; value: string } => entry !== null,
  );
  if (eventCount <= 0 && items.length === 0 && !fingerprint) {
    return null;
  }
  return {
    eventCountLabel:
      eventCount > 0
        ? countLabel(eventCount, labels.gatewayEvent, 'gateway events', locale)
        : labels.gatewayEventsUnavailable,
    fingerprint,
    items: fingerprint
      ? [
          {
            label: labels.previewFingerprint,
            value: fingerprint,
          },
          ...items,
        ]
      : items,
    safetyLabels: [
      summary.review_required_before_ledger_update === true
        ? labels.reviewRequired
        : '',
      summary.requires_operator_ledger_save === true ? labels.operatorSave : '',
      summary.submitted_to_broker === false ? labels.noBrokerSubmission : '',
      summary.does_not_mutate_oms === true ? labels.noOmsMutation : '',
      summary.does_not_mutate_production_ledger === true
        ? labels.noLedgerMutation
        : '',
    ].filter(Boolean),
  };
}

function countLabel(
  count: number,
  singular: string,
  plural: string,
  locale: Locale,
) {
  if (locale === 'zh') {
    return `${count} ${singular}`;
  }
  return `${count} ${count === 1 ? singular : plural}`;
}

function stagedFillSymbolSummary(
  fills: BrokerGatewayFillsQueryResponse,
  locale: Locale,
) {
  const symbols = Array.from(
    new Set(
      fills.fills
        .map((fill) =>
          typeof fill.symbol === 'string' ? fill.symbol.trim() : '',
        )
        .filter(Boolean),
    ),
  ).slice(0, 4);
  if (symbols.length === 0) {
    return locale === 'zh' ? '暂无样本' : 'No samples';
  }
  return symbols.join(locale === 'zh' ? '、' : ', ');
}

function stagedFillReconciliationReviewHint(
  fills: BrokerGatewayFillsQueryResponse | undefined,
  reconciliationRun: ExecutionReconciliationRun | undefined,
  locale: Locale,
) {
  const fillCount = Math.max(fills?.fill_count ?? 0, fills?.fills.length ?? 0);
  const openItemCount = reconciliationRun?.open_item_count ?? 0;
  if (fillCount <= 0 || openItemCount <= 0) {
    return null;
  }

  const fillLabel = countLabel(
    fillCount,
    locale === 'zh' ? '条暂存成交' : 'staged fill',
    'staged fills',
    locale,
  );

  return {
    title:
      locale === 'zh'
        ? '暂存成交可用于执行对账复核'
        : 'Staged fills ready for reconciliation review',
    detail:
      locale === 'zh'
        ? `${fillLabel}可先与执行对账比对，再考虑任何账本更新。`
        : `${fillLabel} can be compared with execution reconciliation before any ledger update.`,
  };
}

function primaryExecutionReconciliationItemForRun(
  run: ExecutionReconciliationRun | undefined,
): ExecutionReconciliationItem | undefined {
  return (
    run?.items?.find(
      (item) =>
        (item.suggested_action ?? item.recommended_action ?? 'no_action') !==
        'no_action',
    ) ?? run?.items?.[0]
  );
}

function AutomationCockpitPanel({
  cockpit,
  brokerGatewayStatus,
  brokerConnectorHealth,
  brokerConnectorHealthLoading,
  brokerConnectorHealthError,
  brokerAccountFacts,
  brokerAccountFactsLoading,
  brokerAccountFactsError,
  brokerFills,
  brokerFillsLoading,
  brokerFillsError,
  brokerOrderQuery,
  brokerOrderQueryLoading,
  brokerOrderQueryError,
  executionReconciliationRuns,
  executionReconciliationRunDetail,
  executionReconciliationLoading,
  executionReconciliationError,
  brokerGatewayLoading,
  brokerGatewayError,
  loading,
  error,
}: {
  cockpit: AutomationCockpitResponse | undefined;
  brokerGatewayStatus: BrokerGatewayStatusResponse | undefined;
  brokerConnectorHealth: BrokerConnectorHealthResponse | undefined;
  brokerConnectorHealthLoading: boolean;
  brokerConnectorHealthError: boolean;
  brokerAccountFacts: BrokerGatewayAccountFactsResponse | undefined;
  brokerAccountFactsLoading: boolean;
  brokerAccountFactsError: boolean;
  brokerFills: BrokerGatewayFillsQueryResponse | undefined;
  brokerFillsLoading: boolean;
  brokerFillsError: boolean;
  brokerOrderQuery: BrokerGatewayOrderQueryResponse | undefined;
  brokerOrderQueryLoading: boolean;
  brokerOrderQueryError: boolean;
  executionReconciliationRuns: ExecutionReconciliationRun[] | undefined;
  executionReconciliationRunDetail: ExecutionReconciliationRun | undefined;
  executionReconciliationLoading: boolean;
  executionReconciliationError: boolean;
  brokerGatewayLoading: boolean;
  brokerGatewayError: boolean;
  loading: boolean;
  error: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();

  if (loading) {
    return null;
  }
  if (error || !cockpit) {
    return null;
  }

  const openAlerts = cockpit.open_alert_count;
  const reconciliationReviews =
    cockpit.execution_reconciliation_open_items.length;
  const nextAction = automationNextAction(cockpit, locale);
  const manualDefault = cockpit.automation_status.manual_confirmation_required;
  const brokerOff =
    !cockpit.broker_submission_enabled &&
    !cockpit.automation_status.broker_submission_enabled;
  const gatewayStatusTitle =
    brokerGatewayError && !brokerGatewayStatus
      ? locale === 'zh'
        ? '网关状态不可用'
        : 'Gateway status unavailable'
      : brokerGatewayLoading && !brokerGatewayStatus
        ? locale === 'zh'
          ? '网关状态加载中'
          : 'Gateway status loading'
        : brokerGatewayStatus?.kill_switch_enabled
          ? locale === 'zh'
            ? '熔断开关已开启'
            : 'Kill switch active'
          : locale === 'zh'
            ? '熔断开关关闭'
            : 'Kill switch clear';
  const gatewayStatusDetail =
    brokerGatewayStatus?.kill_switch_reason ??
    brokerGatewayStatus?.gateways.find((gateway) => gateway.blocked_reason)
      ?.blocked_reason ??
    null;
  const showConnectorHealth =
    brokerConnectorHealthLoading ||
    brokerConnectorHealthError ||
    Boolean(brokerConnectorHealth?.connectors.length);
  const runtimeConnectorSnapshots = cockpit.runtime_connector_snapshots ?? [];
  const showRuntimeConnectorSnapshots = Boolean(
    runtimeConnectorSnapshots.length,
  );
  const showAccountFacts =
    brokerAccountFactsLoading ||
    brokerAccountFactsError ||
    (brokerAccountFacts?.broker_event_count ?? 0) > 0 ||
    Boolean(brokerAccountFacts?.cash_balances.length) ||
    Boolean(brokerAccountFacts?.positions.length) ||
    Boolean(brokerAccountFacts?.fills.length);
  const showBrokerFills =
    brokerFillsLoading ||
    brokerFillsError ||
    (brokerFills?.fill_count ?? 0) > 0 ||
    Boolean(brokerFills?.fills.length);
  const latestExecutionReconciliationRun =
    executionReconciliationRunDetail ?? executionReconciliationRuns?.[0];
  const primaryExecutionReconciliationItem =
    primaryExecutionReconciliationItemForRun(latestExecutionReconciliationRun);
  const brokerTradeCostEvidence = brokerTradeCostEvidenceForItem(
    primaryExecutionReconciliationItem,
    locale,
  );
  const manualExecutionEvidence = manualExecutionEvidenceForItem(
    primaryExecutionReconciliationItem,
    locale,
  );
  const primaryOpenAlert = cockpit.open_alerts[0];
  const primaryOpenAlertPayload = objectRecord(primaryOpenAlert?.payload);
  const openAlertManualExecutionEvidence = manualExecutionEvidenceForPayload(
    primaryOpenAlertPayload,
    locale,
  );
  const openAlertReviewLabels = automationOpenAlertReviewLabels(
    primaryOpenAlertPayload,
    locale,
  );
  const showExecutionReconciliation =
    executionReconciliationLoading ||
    executionReconciliationError ||
    Boolean(latestExecutionReconciliationRun);
  const stagedFillReviewHint = stagedFillReconciliationReviewHint(
    brokerFills,
    latestExecutionReconciliationRun,
    locale,
  );
  const showBrokerOrderQuery =
    Boolean(primaryExecutionReconciliationItem?.order_id) &&
    (brokerOrderQueryLoading ||
      brokerOrderQueryError ||
      Boolean(brokerOrderQuery));

  return (
    <section
      data-testid="decision-automation-cockpit"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {locale === 'zh' ? '自动化控制' : 'Automation control'}
            </div>
            <h2 className="app-card-title mt-1.5">
              {locale === 'zh' ? '自动化待办' : 'Automation to-do'}
            </h2>
          </div>
          <div className="min-w-0 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-3 py-1.5 text-sm font-semibold text-[var(--app-warning)] sm:text-right">
            {locale === 'zh' ? '下一步：' : 'Next: '}
            {nextAction}
          </div>
        </div>

        <div className="mt-4 grid min-w-0 gap-2 md:grid-cols-4">
          <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '执行模式' : 'Execution mode'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {automationModeLabel(automationExecutionMode(cockpit), locale)}
            </div>
          </div>
          <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '确认门禁' : 'Confirmation gate'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {manualDefault
                ? locale === 'zh'
                  ? '默认仍需人工确认'
                  : 'Manual confirmation remains default'
                : locale === 'zh'
                  ? '人工确认未强制'
                  : 'Manual confirmation not enforced'}
            </div>
          </div>
          <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '券商提交' : 'Broker submission'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {brokerOff
                ? locale === 'zh'
                  ? '券商提交关闭'
                  : 'Broker submission off'
                : locale === 'zh'
                  ? '券商提交已开启'
                  : 'Broker submission on'}
            </div>
          </div>
          <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '待处理' : 'Queue'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {locale === 'zh'
                ? `${openAlerts} 个开放告警 · ${reconciliationReviews} 个对账复核`
                : `${openAlerts} open alert${
                    openAlerts === 1 ? '' : 's'
                  } · ${reconciliationReviews} reconciliation review${
                    reconciliationReviews === 1 ? '' : 's'
                  }`}
            </div>
          </div>
        </div>

        {primaryOpenAlert ? (
          <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2.5">
            <div className="text-sm font-semibold text-[var(--app-text)]">
              {primaryOpenAlert.title}
            </div>
            {primaryOpenAlert.detail ? (
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {primaryOpenAlert.detail}
              </div>
            ) : null}
            {openAlertReviewLabels.length ? (
              <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                {openAlertReviewLabels.map((label) => (
                  <span className="app-chip" key={label}>
                    {label}
                  </span>
                ))}
              </div>
            ) : null}
            {openAlertManualExecutionEvidence ? (
              <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                    {locale === 'zh'
                      ? '手工成交证据'
                      : 'Manual execution evidence'}
                  </div>
                  <span className="app-chip">
                    {openAlertManualExecutionEvidence.eventCountLabel}
                  </span>
                </div>
                {openAlertManualExecutionEvidence.items.length ? (
                  <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
                    {openAlertManualExecutionEvidence.items.map((entry) => (
                      <div
                        className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                        key={entry.label}
                      >
                        <div className="app-muted text-xs">{entry.label}</div>
                        <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                          {entry.value}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {openAlertManualExecutionEvidence.safetyLabels.length ? (
                  <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                    {openAlertManualExecutionEvidence.safetyLabels.map(
                      (label) => (
                        <span className="app-chip" key={label}>
                          {label}
                        </span>
                      ),
                    )}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {cockpit.promotion_states.length ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                {locale === 'zh' ? '策略晋级状态' : 'Strategy promotion state'}
              </div>
              <span className="app-chip">
                {cockpit.promotion_states.length === 1
                  ? strategyPromotionStageLabel(
                      cockpit.promotion_states[0].stage,
                      locale,
                    )
                  : countLabel(
                      cockpit.promotion_states.length,
                      locale === 'zh' ? '个策略' : 'strategy',
                      'strategies',
                      locale,
                    )}
              </span>
            </div>
            <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
              {cockpit.promotion_states.slice(0, 4).map((state) => {
                const lifecycleLabels = strategyPromotionLifecycleLabels(
                  state.lifecycle,
                  locale,
                );
                return (
                  <div
                    className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                    key={state.strategy_id}
                  >
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="break-words text-sm font-semibold text-[var(--app-text)]">
                          {state.strategy_id}
                        </div>
                        <div className="app-muted mt-1 break-words text-xs leading-5">
                          {strategyPromotionMissingRequirementsLabel(
                            state.missing_requirements,
                            locale,
                          )}
                        </div>
                      </div>
                      <span className="app-chip">
                        {strategyPromotionStageLabel(state.stage, locale)}
                      </span>
                    </div>
                    <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                      <span>
                        {strategyPromotionGateStatusLabel(
                          state.gate_status ?? state.status ?? 'unknown',
                          locale,
                        )}
                      </span>
                      <span>
                        {state.live_like_enabled
                          ? locale === 'zh'
                            ? '类实盘已启用'
                            : 'Live-like enabled'
                          : locale === 'zh'
                            ? '类实盘已关闭'
                            : 'Live-like disabled'}
                      </span>
                      {typeof state.backtest_result_id === 'number' ? (
                        <span>
                          {locale === 'zh' ? '回测证据' : 'Backtest evidence'}:{' '}
                          {state.backtest_result_id}
                        </span>
                      ) : null}
                      <span>
                        {locale === 'zh'
                          ? '默认仍需人工确认'
                          : 'Manual confirmation remains default'}
                      </span>
                    </div>
                    {lifecycleLabels.length ? (
                      <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                        {lifecycleLabels.map((label) => (
                          <span className="app-chip" key={label}>
                            {label}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {brokerGatewayStatus || brokerGatewayLoading || brokerGatewayError ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                {locale === 'zh' ? '券商网关状态' : 'Broker gateway status'}
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
                  brokerGatewayStatus?.kill_switch_enabled || brokerGatewayError
                    ? 'border-[color-mix(in_srgb,var(--app-danger)_40%,transparent)] text-[var(--app-danger)]'
                    : 'border-[color-mix(in_srgb,var(--app-success)_35%,transparent)] text-[var(--app-success)]'
                }`}
              >
                {gatewayStatusTitle}
              </span>
            </div>
            {gatewayStatusDetail ? (
              <div className="app-muted mt-2 break-words text-sm leading-6">
                {gatewayStatusDetail}
              </div>
            ) : null}
            {brokerGatewayStatus?.gateways.length ? (
              <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
                {brokerGatewayStatus.gateways.map((gateway) => (
                  <div
                    className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                    key={gateway.gateway_id}
                  >
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0 text-sm font-semibold text-[var(--app-text)]">
                        {brokerGatewayDisplayName(gateway, locale)}
                      </div>
                      <span className="app-chip">
                        {brokerGatewayStatusLabel(gateway.status, locale)}
                      </span>
                    </div>
                    <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'preview',
                          gateway.can_preview_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'export',
                          gateway.can_export_tickets,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'dry_run',
                          gateway.can_dry_run_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'query_orders',
                          gateway.can_query_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'query_fills',
                          gateway.can_query_fills,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'read_positions',
                          gateway.can_query_positions,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'read_cash',
                          gateway.can_query_cash,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'submit',
                          gateway.can_submit_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerGatewayCapabilityLabel(
                          'cancel',
                          gateway.can_cancel_orders,
                          locale,
                        )}
                      </span>
                    </div>
                    {gateway.blocked_reason ? (
                      <div className="app-muted mt-2 break-words text-xs leading-5">
                        {gateway.blocked_reason}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
            {brokerGatewayStatus?.controlled_bridge_policy ? (
              <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-[var(--app-text)]">
                      {locale === 'zh'
                        ? '受控桥接策略'
                        : 'Controlled bridge policy'}
                    </div>
                    <div className="app-muted mt-1 break-words text-xs leading-5">
                      {brokerGatewayStatus.controlled_bridge_policy.policy_id}
                    </div>
                  </div>
                  <span className="app-chip">
                    {controlledBridgePolicyStatusLabel(
                      brokerGatewayStatus.controlled_bridge_policy.status,
                      locale,
                    )}
                  </span>
                </div>
                <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                  <span>
                    {controlledBridgeListSummary(
                      'connector',
                      brokerGatewayStatus.controlled_bridge_policy
                        .allowed_connector_ids,
                      locale,
                    )}
                  </span>
                  <span>
                    {controlledBridgeListSummary(
                      'account',
                      brokerGatewayStatus.controlled_bridge_policy
                        .allowed_account_aliases,
                      locale,
                    )}
                  </span>
                  <span>
                    {controlledBridgeListSummary(
                      'strategy',
                      brokerGatewayStatus.controlled_bridge_policy
                        .allowed_strategy_ids,
                      locale,
                    )}
                  </span>
                  <span>
                    {controlledBridgeListSummary(
                      'symbol',
                      brokerGatewayStatus.controlled_bridge_policy
                        .allowed_symbols,
                      locale,
                    )}
                  </span>
                </div>
                <div className="app-muted mt-2 break-words text-xs leading-5">
                  {locale === 'zh' ? '必要门禁' : 'Required gates'}:{' '}
                  {controlledBridgeTokenList(
                    brokerGatewayStatus.controlled_bridge_policy.required_gates,
                    locale,
                  )}
                </div>
                {brokerGatewayStatus.controlled_bridge_policy.blockers
                  ?.length ? (
                  <div className="app-muted mt-1 break-words text-xs leading-5">
                    {locale === 'zh' ? '阻断项' : 'Blockers'}:{' '}
                    {controlledBridgeTokenList(
                      brokerGatewayStatus.controlled_bridge_policy.blockers,
                      locale,
                    )}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {showConnectorHealth ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
              {locale === 'zh'
                ? '只读连接器健康'
                : 'Read-only connector health'}
            </div>
            {brokerConnectorHealthLoading && !brokerConnectorHealth ? (
              <div className="app-muted mt-2 text-sm">
                {locale === 'zh'
                  ? '连接器状态加载中'
                  : 'Connector status loading'}
              </div>
            ) : brokerConnectorHealthError && !brokerConnectorHealth ? (
              <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
                {locale === 'zh'
                  ? '连接器状态不可用'
                  : 'Connector status unavailable'}
              </div>
            ) : brokerConnectorHealth?.connectors.length ? (
              <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
                {brokerConnectorHealth.connectors.map((connector) => (
                  <div
                    className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                    key={connector.connector_id}
                  >
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-[var(--app-text)]">
                          {connector.connector_id}
                        </div>
                        {connector.account_alias ? (
                          <div className="app-muted mt-0.5 break-words text-xs">
                            {connector.account_alias}
                          </div>
                        ) : null}
                      </div>
                      <span className="app-chip">
                        {brokerConnectorStatusLabel(connector.status, locale)}
                      </span>
                    </div>
                    <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'read_account',
                          connector.capabilities?.can_read_account,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'read_cash',
                          connector.capabilities?.can_read_cash,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'read_positions',
                          connector.capabilities?.can_read_positions,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'read_orders',
                          connector.capabilities?.can_read_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'read_fills',
                          connector.capabilities?.can_read_fills,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'preview_orders',
                          connector.capabilities?.can_preview_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'export_tickets',
                          connector.capabilities?.can_export_tickets,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'dry_run_orders',
                          connector.capabilities?.can_dry_run_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'submit',
                          connector.capabilities?.can_submit_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'cancel',
                          connector.capabilities?.can_cancel_orders,
                          locale,
                        )}
                      </span>
                    </div>
                    {connector.message ? (
                      <div className="app-muted mt-2 break-words text-xs leading-5">
                        {connector.message}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {showRuntimeConnectorSnapshots ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
              {locale === 'zh'
                ? '运行态连接器快照'
                : 'Runtime connector snapshot'}
            </div>
            <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
              {runtimeConnectorSnapshots.slice(0, 4).map((snapshot) => {
                const cashBalance = snapshot.cash_balance;
                const cashLabel =
                  cashBalance?.currency || cashBalance?.balance != null
                    ? `${locale === 'zh' ? '资金' : 'Cash'} ${
                        cashBalance?.currency ?? ''
                      } ${cashBalance?.balance ?? ''}`.trim()
                    : locale === 'zh'
                      ? '资金未返回'
                      : 'Cash unavailable';
                return (
                  <div
                    className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                    key={snapshot.connector_id}
                  >
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="break-words text-sm font-semibold text-[var(--app-text)]">
                          {snapshot.connector_id}
                        </div>
                        {snapshot.account_alias ? (
                          <div className="app-muted mt-0.5 break-words text-xs">
                            {snapshot.account_alias}
                          </div>
                        ) : null}
                      </div>
                      <span className="app-chip">
                        {runtimeConnectorSnapshotStatusLabel(
                          snapshot.status,
                          locale,
                        )}
                      </span>
                    </div>
                    <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                      <span>{cashLabel}</span>
                      <span>
                        {countLabel(
                          snapshot.position_count ??
                            snapshot.positions?.length ??
                            0,
                          locale === 'zh' ? '个持仓' : 'position',
                          'positions',
                          locale,
                        )}
                      </span>
                      <span>
                        {countLabel(
                          snapshot.order_count ?? snapshot.orders?.length ?? 0,
                          locale === 'zh' ? '个订单' : 'order',
                          'orders',
                          locale,
                        )}
                      </span>
                      <span>
                        {countLabel(
                          snapshot.fill_count ?? snapshot.fills?.length ?? 0,
                          locale === 'zh' ? '笔成交' : 'fill',
                          'fills',
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'submit',
                          snapshot.capabilities?.can_submit_orders,
                          locale,
                        )}
                      </span>
                      <span>
                        {brokerConnectorCapabilityLabel(
                          'cancel',
                          snapshot.capabilities?.can_cancel_orders,
                          locale,
                        )}
                      </span>
                    </div>
                    <div className="app-muted mt-2 break-words text-xs leading-5">
                      {snapshot.submitted_to_broker
                        ? locale === 'zh'
                          ? '需要复核：快照声明已提交券商'
                          : 'Review required: snapshot claims broker submission'
                        : locale === 'zh'
                          ? '不会提交券商订单'
                          : 'No broker submission'}
                      {' · '}
                      {snapshot.does_not_mutate_production_ledger
                        ? locale === 'zh'
                          ? '不写生产账本'
                          : 'No ledger mutation'
                        : locale === 'zh'
                          ? '需要账本变更复核'
                          : 'Ledger mutation requires review'}
                    </div>
                    {snapshot.connector_health?.message ? (
                      <div className="app-muted mt-1 break-words text-xs leading-5">
                        {snapshot.connector_health.message}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {showAccountFacts ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                {locale === 'zh' ? '暂存账户事实' : 'Staged account facts'}
              </div>
              <span className="app-chip">
                {brokerAccountFacts
                  ? countLabel(
                      brokerAccountFacts.broker_event_count,
                      locale === 'zh'
                        ? '条券商证据事件'
                        : 'broker evidence event',
                      'broker evidence events',
                      locale,
                    )
                  : brokerAccountFactsLoading
                    ? copy.states.loading
                    : locale === 'zh'
                      ? '不可用'
                      : 'Unavailable'}
              </span>
            </div>
            {brokerAccountFactsError && !brokerAccountFacts ? (
              <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
                {locale === 'zh'
                  ? '暂存账户事实不可用'
                  : 'Staged account facts unavailable'}
              </div>
            ) : brokerAccountFacts ? (
              <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-3">
                <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '资金' : 'Cash'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {countLabel(
                      brokerAccountFacts.cash_balances.length,
                      locale === 'zh' ? '条资金' : 'cash',
                      'cash',
                      locale,
                    )}
                  </div>
                </div>
                <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '持仓' : 'Positions'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {countLabel(
                      brokerAccountFacts.positions.length,
                      locale === 'zh' ? '条持仓' : 'position',
                      'positions',
                      locale,
                    )}
                  </div>
                </div>
                <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '成交' : 'Fills'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {countLabel(
                      brokerAccountFacts.fills.length,
                      locale === 'zh' ? '条成交' : 'fill',
                      'fills',
                      locale,
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {showBrokerFills ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                {locale === 'zh' ? '暂存成交轮询' : 'Staged fill polling'}
              </div>
              <span className="app-chip">
                {brokerFills
                  ? countLabel(
                      brokerFills.fill_count,
                      locale === 'zh' ? '条暂存成交' : 'staged fill',
                      'staged fills',
                      locale,
                    )
                  : brokerFillsLoading
                    ? copy.states.loading
                    : locale === 'zh'
                      ? '不可用'
                      : 'Unavailable'}
              </span>
            </div>
            {brokerFillsError && !brokerFills ? (
              <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
                {locale === 'zh'
                  ? '暂存成交查询不可用'
                  : 'Staged fill query unavailable'}
              </div>
            ) : brokerFills ? (
              <>
                <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-3">
                  <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                    <div className="app-muted text-xs">
                      {locale === 'zh' ? '券商证据事件' : 'Broker evidence'}
                    </div>
                    <div className="mt-1 font-semibold text-[var(--app-text)]">
                      {countLabel(
                        brokerFills.broker_event_count,
                        locale === 'zh'
                          ? '条券商证据事件'
                          : 'broker evidence event',
                        'broker evidence events',
                        locale,
                      )}
                    </div>
                  </div>
                  <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                    <div className="app-muted text-xs">
                      {locale === 'zh' ? '样本标的' : 'Sample symbols'}
                    </div>
                    <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                      {stagedFillSymbolSummary(brokerFills, locale)}
                    </div>
                  </div>
                  <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                    <div className="app-muted text-xs">
                      {locale === 'zh' ? '安全边界' : 'Safety boundary'}
                    </div>
                    <div className="mt-1 font-semibold text-[var(--app-text)]">
                      {brokerFills.submitted_to_broker ||
                      brokerFills.can_submit_orders
                        ? locale === 'zh'
                          ? '需要人工复核'
                          : 'Needs review'
                        : locale === 'zh'
                          ? '不提交券商订单'
                          : 'No broker submission'}
                    </div>
                  </div>
                </div>
                {stagedFillReviewHint ? (
                  <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2.5">
                    <div className="text-sm font-semibold text-[var(--app-text)]">
                      {stagedFillReviewHint.title}
                    </div>
                    <div className="app-muted mt-1 break-words text-xs leading-5">
                      {stagedFillReviewHint.detail}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}

        {showExecutionReconciliation ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                {locale === 'zh' ? '执行对账' : 'Execution reconciliation'}
              </div>
              <span className="app-chip">
                {latestExecutionReconciliationRun
                  ? executionReconciliationStatusLabel(
                      latestExecutionReconciliationRun.status,
                      locale,
                    )
                  : executionReconciliationLoading
                    ? copy.states.loading
                    : locale === 'zh'
                      ? '不可用'
                      : 'Unavailable'}
              </span>
            </div>
            {executionReconciliationError &&
            !latestExecutionReconciliationRun ? (
              <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
                {locale === 'zh'
                  ? '执行对账不可用'
                  : 'Execution reconciliation unavailable'}
              </div>
            ) : latestExecutionReconciliationRun ? (
              <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-[var(--app-text)]">
                      {latestExecutionReconciliationRun.run_id}
                    </div>
                    <div className="app-muted mt-1 text-xs">
                      {locale === 'zh'
                        ? `${latestExecutionReconciliationRun.open_item_count} 个未处理 / 共 ${latestExecutionReconciliationRun.item_count} 个`
                        : `${latestExecutionReconciliationRun.open_item_count} open of ${latestExecutionReconciliationRun.item_count}`}
                    </div>
                  </div>
                  {latestExecutionReconciliationRun.run_date ? (
                    <span className="app-chip">
                      {latestExecutionReconciliationRun.run_date}
                    </span>
                  ) : null}
                </div>
                {primaryExecutionReconciliationItem ? (
                  <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
                    <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-[var(--app-text)]">
                          {primaryExecutionReconciliationItem.order_id ?? '--'}
                        </div>
                        <div className="app-muted mt-1 text-xs">
                          {executionReconciliationItemStatusLabel(
                            primaryExecutionReconciliationItem.item_status ??
                              primaryExecutionReconciliationItem.status ??
                              'unknown',
                            locale,
                          )}
                        </div>
                      </div>
                      <span className="app-chip">
                        {executionReconciliationActionLabel(
                          primaryExecutionReconciliationItem.suggested_action ??
                            primaryExecutionReconciliationItem.recommended_action ??
                            'review_order_state',
                          locale,
                        )}
                      </span>
                    </div>
                    {primaryExecutionReconciliationItem.detail ? (
                      <div className="app-muted mt-2 break-words text-sm leading-6">
                        {primaryExecutionReconciliationItem.detail}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {brokerTradeCostEvidence ? (
                  <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
                    <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                        {locale === 'zh'
                          ? '券商成本证据'
                          : 'Broker cost evidence'}
                      </div>
                      <span className="app-chip">
                        {brokerTradeCostEvidence.eventCountLabel}
                      </span>
                    </div>
                    {brokerTradeCostEvidence.items.length ? (
                      <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
                        {brokerTradeCostEvidence.items.map((entry) => (
                          <div
                            className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                            key={entry.label}
                          >
                            <div className="app-muted text-xs">
                              {entry.label}
                            </div>
                            <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                              {entry.value}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {brokerTradeCostEvidence.safetyLabels.length ? (
                      <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                        {brokerTradeCostEvidence.safetyLabels.map((label) => (
                          <span className="app-chip" key={label}>
                            {label}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {manualExecutionEvidence ? (
                  <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
                    <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                        {locale === 'zh'
                          ? '手工成交证据'
                          : 'Manual execution evidence'}
                      </div>
                      <span className="app-chip">
                        {manualExecutionEvidence.eventCountLabel}
                      </span>
                    </div>
                    {manualExecutionEvidence.items.length ? (
                      <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
                        {manualExecutionEvidence.items.map((entry) => (
                          <div
                            className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                            key={entry.label}
                          >
                            <div className="app-muted text-xs">
                              {entry.label}
                            </div>
                            <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                              {entry.value}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {manualExecutionEvidence.safetyLabels.length ? (
                      <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                        {manualExecutionEvidence.safetyLabels.map((label) => (
                          <span className="app-chip" key={label}>
                            {label}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {showBrokerOrderQuery ? (
                  <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
                    <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="app-kicker text-[10px] text-[var(--app-subtext-1)]">
                        {locale === 'zh'
                          ? '只读订单查询'
                          : 'Read-only order query'}
                      </div>
                      <span className="app-chip">
                        {brokerOrderQuery
                          ? brokerOrderQuery.status === 'query_ready'
                            ? locale === 'zh'
                              ? '查询就绪'
                              : 'Query ready'
                            : formatPublicStatus(
                                brokerOrderQuery.status,
                                locale,
                              )
                          : brokerOrderQueryLoading
                            ? copy.states.loading
                            : locale === 'zh'
                              ? '不可用'
                              : 'Unavailable'}
                      </span>
                    </div>
                    {brokerOrderQueryError && !brokerOrderQuery ? (
                      <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
                        {locale === 'zh'
                          ? '只读订单查询不可用'
                          : 'Read-only order query unavailable'}
                      </div>
                    ) : brokerOrderQuery ? (
                      <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
                        <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                          <div className="app-muted text-xs">
                            {locale === 'zh' ? 'OMS 订单' : 'OMS order'}
                          </div>
                          <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                            {String(
                              brokerOrderQuery.oms_order?.order_id ??
                                primaryExecutionReconciliationItem?.order_id ??
                                '--',
                            )}
                          </div>
                          <div className="app-muted mt-1 break-words text-xs leading-5">
                            {omsOrderStatusLabel(
                              String(
                                brokerOrderQuery.oms_order?.status ?? 'unknown',
                              ),
                              locale,
                            )}
                          </div>
                        </div>
                        <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                          <div className="app-muted text-xs">
                            {locale === 'zh' ? '网关审计' : 'Gateway audit'}
                          </div>
                          <div className="mt-1 font-semibold text-[var(--app-text)]">
                            {countLabel(
                              brokerOrderQuery.gateway_event_count,
                              locale === 'zh' ? '条网关事件' : 'gateway event',
                              'gateway events',
                              locale,
                            )}
                          </div>
                        </div>
                        <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                          <div className="app-muted text-xs">
                            {locale === 'zh'
                              ? '暂存成交'
                              : 'Staged broker fills'}
                          </div>
                          <div className="mt-1 font-semibold text-[var(--app-text)]">
                            {countLabel(
                              brokerOrderQuery.staged_broker_fill_count,
                              locale === 'zh'
                                ? '条暂存成交'
                                : 'staged broker fill',
                              'staged broker fills',
                              locale,
                            )}
                          </div>
                        </div>
                        <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                          <div className="app-muted text-xs">
                            {locale === 'zh' ? '安全边界' : 'Safety boundary'}
                          </div>
                          <div className="mt-1 font-semibold text-[var(--app-text)]">
                            {brokerOrderQuery.submitted_to_broker ||
                            brokerOrderQuery.can_submit_orders
                              ? locale === 'zh'
                                ? '需要人工复核'
                                : 'Needs review'
                              : locale === 'zh'
                                ? '不提交券商订单'
                                : 'No broker submission'}
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function DailyTradingPlanPanel({
  plan,
  operationsToday,
  loading,
  error,
  onRunPaperShadow,
  paperShadowRunPending,
  paperShadowRunError,
}: {
  plan: DailyTradingPlanResponse | undefined;
  operationsToday: OperationsTodayResponse | undefined;
  loading: boolean;
  error: boolean;
  onRunPaperShadow: () => void;
  paperShadowRunPending: boolean;
  paperShadowRunError: boolean;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const firstIntent = plan?.order_intents?.[0];
  const constraintChecks = firstIntent?.constraint_checks ?? [];
  const fallbackShadowStatus =
    (plan?.order_intent_count ?? 0) > 0 ? 'not_run' : 'not_required';
  const currentShadowStatus =
    operationsToday?.paper_shadow.effective_status ??
    operationsToday?.paper_shadow.status ??
    fallbackShadowStatus;
  const canRunPaperShadow = (plan?.order_intent_count ?? 0) > 0;
  const runPaperShadowLabel =
    currentShadowStatus === 'within_expectations' ||
    currentShadowStatus === 'accepted_for_manual_confirmation'
      ? locale === 'zh'
        ? '重新运行模拟复核'
        : 'Rerun paper/shadow simulation'
      : locale === 'zh'
        ? '运行模拟复核'
        : 'Run paper/shadow simulation';
  const paperShadowCostItems = paperShadowCostSummaryItems(
    operationsToday?.paper_shadow.divergence_summary?.cost_summary,
    locale,
  );
  const paperShadowDivergenceBlocks = paperShadowDivergenceEvidenceBlocks(
    operationsToday?.paper_shadow.divergence_summary,
    locale,
  );
  const paperShadowReviewQueue =
    operationsToday?.paper_shadow.review_queue ?? [];
  const paperShadowManualHandoffItems = operationsToday?.paper_shadow
    .manual_handoff
    ? paperShadowManualHandoffEvidenceItems(
        operationsToday.paper_shadow.manual_handoff,
        locale,
      )
    : [];

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
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="app-chip">
                    {paperShadowStatusLabel(currentShadowStatus, locale)}
                  </span>
                  <button
                    type="button"
                    className="app-button-secondary inline-flex min-h-8 items-center justify-center rounded-xl px-3 py-1.5 text-center text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={!canRunPaperShadow || paperShadowRunPending}
                    onClick={onRunPaperShadow}
                  >
                    {paperShadowRunPending
                      ? locale === 'zh'
                        ? '运行中'
                        : 'Running'
                      : runPaperShadowLabel}
                  </button>
                </div>
              </div>
              <div className="app-muted mt-2 text-sm">
                {paperShadowNextStepLabel(
                  operationsToday?.paper_shadow.next_manual_review_step ??
                    'run_paper_shadow_daily',
                  locale,
                )}
              </div>
              {paperShadowManualHandoffItems.length > 0 ? (
                <div className="mt-3 grid min-w-0 gap-1 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2 text-xs text-[var(--app-text)]">
                  {paperShadowManualHandoffItems.map((item) => (
                    <div className="min-w-0 break-words" key={item}>
                      {item}
                    </div>
                  ))}
                </div>
              ) : null}
              {paperShadowRunError ? (
                <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
                  {locale === 'zh'
                    ? '模拟复核运行失败，请查看后端日志。'
                    : 'Simulation run failed; check backend logs.'}
                </div>
              ) : null}
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
              {paperShadowReviewQueue.length > 0 ? (
                <div className="mt-3 min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2 text-sm">
                  <div className="text-xs font-semibold uppercase text-[var(--app-muted)]">
                    {locale === 'zh' ? '复核队列' : 'Review queue'}
                  </div>
                  <div className="mt-2 grid min-w-0 gap-2">
                    {paperShadowReviewQueue.slice(0, 3).map((item) => {
                      const safetyText = paperShadowReviewQueueSafetyText(
                        item,
                        locale,
                      );
                      const detailItems = paperShadowReviewQueueDetailItems(
                        item,
                        locale,
                      );
                      return (
                        <div
                          className="min-w-0"
                          key={item.review_id || item.order_id || item.symbol}
                        >
                          <div className="min-w-0 break-words font-semibold text-[var(--app-text)]">
                            {paperShadowReviewQueueItemTitle(item, locale)}
                          </div>
                          {safetyText ? (
                            <div className="app-muted mt-1 min-w-0 break-words text-xs">
                              {safetyText}
                            </div>
                          ) : null}
                          {detailItems.length > 0 ? (
                            <div className="mt-1 grid min-w-0 gap-1 text-xs text-[var(--app-text)]">
                              {detailItems.map((detail) => (
                                <div
                                  className="min-w-0 break-words"
                                  key={detail}
                                >
                                  {detail}
                                </div>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
              {paperShadowCostItems.length > 0 ? (
                <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-2 xl:grid-cols-5">
                  {paperShadowCostItems.map((item) => (
                    <div
                      className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-3 py-2"
                      key={item.label}
                    >
                      <div className="app-muted text-xs">{item.label}</div>
                      <div className="min-w-0 break-words font-mono tabular-nums text-[var(--app-text)]">
                        {item.value}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {paperShadowDivergenceBlocks.length > 0 ? (
                <div className="mt-3 grid min-w-0 gap-2 text-sm lg:grid-cols-2">
                  {paperShadowDivergenceBlocks.map((block) => (
                    <div
                      className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-3 py-2"
                      key={block.title}
                    >
                      <div className="text-xs font-semibold uppercase text-[var(--app-muted)]">
                        {block.title}
                      </div>
                      <div className="mt-2 grid min-w-0 gap-1">
                        {block.items.map((item) => (
                          <div
                            className="min-w-0 break-words text-[var(--app-text)]"
                            key={item}
                          >
                            {item}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
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
  const automationCockpit = useAutomationCockpitQuery();
  const brokerGatewayStatus = useBrokerGatewayStatusQuery();
  const brokerConnectorHealth = useBrokerConnectorHealthQuery();
  const brokerAccountFacts = useBrokerGatewayAccountFactsQuery();
  const brokerFills = useBrokerGatewayFillsQuery();
  const executionReconciliationRuns = useExecutionReconciliationRunsQuery();
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
        onRunPaperShadow={() => runPaperShadow.mutate()}
        paperShadowRunPending={runPaperShadow.isPending}
        paperShadowRunError={runPaperShadow.isError}
      />

      <AutomationCockpitPanel
        cockpit={automationCockpit.data}
        brokerGatewayStatus={brokerGatewayStatus.data}
        brokerConnectorHealth={brokerConnectorHealth.data}
        brokerConnectorHealthLoading={brokerConnectorHealth.isLoading}
        brokerConnectorHealthError={brokerConnectorHealth.isError}
        brokerAccountFacts={brokerAccountFacts.data}
        brokerAccountFactsLoading={brokerAccountFacts.isLoading}
        brokerAccountFactsError={brokerAccountFacts.isError}
        brokerFills={brokerFills.data}
        brokerFillsLoading={brokerFills.isLoading}
        brokerFillsError={brokerFills.isError}
        brokerOrderQuery={brokerOrderQuery.data}
        brokerOrderQueryLoading={brokerOrderQuery.isLoading}
        brokerOrderQueryError={brokerOrderQuery.isError}
        executionReconciliationRuns={executionReconciliationRuns.data}
        executionReconciliationRunDetail={executionReconciliationRunDetail.data}
        executionReconciliationLoading={executionReconciliationRuns.isLoading}
        executionReconciliationError={
          executionReconciliationRuns.isError ||
          executionReconciliationRunDetail.isError
        }
        brokerGatewayLoading={brokerGatewayStatus.isLoading}
        brokerGatewayError={brokerGatewayStatus.isError}
        loading={automationCockpit.isLoading}
        error={automationCockpit.isError}
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
