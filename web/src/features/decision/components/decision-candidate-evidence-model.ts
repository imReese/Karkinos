import { type Locale } from '../../../shared/preferences/context';
import { formatCurrency } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { type StrategyNameMap } from '../../../shared/strategy-display';
import { type PaperShadowDivergenceSummary } from '../decision-feature-boundary';
import {
  type DecisionCandidate,
  type StrategyAttributionGateEvidence,
} from '../api';
import type {
  BacktestPageCopy,
  CandidateEvidenceChainItem,
  DecisionCopy,
  PaperShadowDivergenceEvidenceBlock,
} from './decision-status-model';
import {
  accountTruthTone,
  decisionTone,
  evidenceStatus,
  formatPaperShadowCountMap,
  formatPaperShadowRefs,
  formatPaperShadowStatusCountMap,
  formatPaperShadowValueMap,
  manualStatus,
  nullableCurrency,
  numericEvidenceValue,
  paperShadowMarketContextItems,
  strategyAuditIdFromDisplay,
  strategyDisplayNameFromId,
} from './decision-status-model';

export function paperShadowDivergenceEvidenceBlocks(
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

export function strategyContributionDetailItems(
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

export function candidateEvidenceChainItems(
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
