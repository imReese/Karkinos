import { ChevronDown } from 'lucide-react';

import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import {
  ExceptionList,
  type ExceptionItem,
} from '../../../shared/ui/workbench';
import {
  usePreferences,
  type Locale,
} from '../../../shared/preferences/context';
import type { AccountOverview } from '../../account/api';
import type { QuoteDiagnosticItem } from '../../account/components/dashboard-quick-actions';
import type { AccountStrategyContributionReport } from '../../account-strategy/api';
import type {
  DailyTradingPlanResponse,
  DecisionCandidate,
  DecisionResponse,
} from '../../decision/api';
import type { OperationsTodayResponse } from '../../operations/api';
import {
  operationsAttentionResolutionLabel,
  operationsNextActionLabel,
  operationsTargetHref,
} from '../../operations/presentation';
import type { ManualOrder } from '../../trading/api';
import type {
  CurrentHoldingMarketEvidenceReview,
  PortfolioSnapshot,
} from '../../portfolio/api';
import type { MarketDataHealthResponse } from '../../market/api';
import { MarketRefreshButton } from '../../market/components/market-refresh-button';
import {
  formatCurrency as formatCurrencyValue,
  formatTimestamp,
} from '../../../shared/format';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../../../shared/public-labels';

type TodayQueueTone = 'success' | 'warning' | 'danger' | 'neutral';
type TodayQueuePriority = 'first' | 'watch' | 'normal';

type TodayQueueItem = {
  key: string;
  title: string;
  detail: string;
  meta: string;
  href: string;
  actionLabel: string;
  tone: TodayQueueTone;
  priority: TodayQueuePriority;
  resolution?: string;
};

const TODAY_QUEUE_PRIORITY_ORDER: TodayQueuePriority[] = [
  'first',
  'watch',
  'normal',
];

function todayQueuePriorityLabel(
  priority: TodayQueuePriority,
  labels: AppCopy['overview']['dashboard'],
) {
  if (priority === 'first') {
    return labels.queuePriorityFirst;
  }
  if (priority === 'watch') {
    return labels.queuePriorityWatch;
  }
  return labels.queuePriorityNormal;
}

function canUseStrategyContribution(
  report?: AccountStrategyContributionReport | null,
) {
  return Boolean(
    report &&
    report.schema_version === 'karkinos.account_strategy_contribution.v2' &&
    report.contribution_status === 'evidence_bound_from_posted_fills' &&
    report.evidence_binding_status === 'bound' &&
    report.linked_fill_count > 0 &&
    report.ledger_posted_fill_count === report.linked_fill_count &&
    report.unposted_linked_fill_count === 0 &&
    Boolean(report.valuation_snapshot_id) &&
    (report.ledger_cutoff_id ?? 0) > 0 &&
    Boolean(report.contribution_fingerprint) &&
    report.evidence_refs.length > 0 &&
    report.missing_valuation_symbols.length === 0 &&
    report.persisted_facts_only === true &&
    report.provider_contacted === false &&
    report.database_writes_performed === false &&
    report.authorizes_execution === false,
  );
}

function strategyContributionReviewHref(
  report?: AccountStrategyContributionReport | null,
) {
  const status = report?.contribution_status ?? '';
  if (status.startsWith('valuation_')) {
    return '/market';
  }
  if (status.startsWith('ledger_')) {
    return '/operations';
  }
  return '/backtest';
}

function currentHoldingMarketReviewSummary(
  report: CurrentHoldingMarketEvidenceReview,
  labels: AppCopy['overview']['dashboard'],
) {
  return labels.dataReviewSummary(
    report.fund_nav_review_count,
    report.stale_or_cached_review_count,
    report.missing_or_error_review_count,
    report.estimated_review_count,
    report.unknown_status_review_count,
  );
}

function currentHoldingMarketReviewContractIsValid(
  report?: CurrentHoldingMarketEvidenceReview | null,
  portfolioSnapshot?: PortfolioSnapshot | null,
) {
  if (!report || !portfolioSnapshot) {
    return false;
  }
  const identityContractValid =
    report.status === 'blocked_identity'
      ? report.source_blockers.length > 0
      : Boolean(
          report.valuation_snapshot_id &&
          report.ledger_fingerprint &&
          report.quote_set_fingerprint,
        );
  const crossResponseIdentityValid = Boolean(
    report.valuation_snapshot_id === portfolioSnapshot.valuation_snapshot_id &&
    report.ledger_cutoff_id === portfolioSnapshot.ledger_cutoff_id &&
    report.ledger_fingerprint === portfolioSnapshot.ledger_fingerprint &&
    report.quote_set_fingerprint === portfolioSnapshot.quote_set_fingerprint,
  );
  return Boolean(
    report.schema_version ===
      'karkinos.current_holding_market_evidence_review.v1' &&
    report.reads_persisted_facts_only === true &&
    report.provider_contact_performed === false &&
    report.runtime_connector_query_performed === false &&
    report.database_writes_performed === false &&
    report.does_not_mutate_oms === true &&
    report.does_not_mutate_production_ledger === true &&
    report.does_not_mutate_risk === true &&
    report.does_not_mutate_kill_switch === true &&
    report.does_not_change_capital_authority === true &&
    report.authorizes_execution === false &&
    report.review_fingerprint.startsWith('sha256:') &&
    report.current_holding_count ===
      report.confirmed_holding_count + report.review_required_count &&
    report.items.length === report.review_required_count &&
    identityContractValid &&
    crossResponseIdentityValid &&
    Number.isInteger(report.ledger_cutoff_id) &&
    report.ledger_cutoff_id >= 0,
  );
}

function decisionCandidateDisplayName(candidate: DecisionCandidate) {
  return (
    candidate.display_name ??
    candidate.name ??
    candidate.evidence.signal?.display_name ??
    candidate.evidence.signal?.name ??
    candidate.symbol
  );
}

function tradingPlanIntentInstrumentLabel(
  intent: DailyTradingPlanResponse['order_intents'][number],
  candidates: DecisionCandidate[],
  quoteDiagnostics: QuoteDiagnosticItem[],
) {
  const symbol = String(intent.symbol ?? '').trim();
  const candidate = candidates.find(
    (item) =>
      (intent.action_id !== null && item.action_id === intent.action_id) ||
      item.symbol === symbol,
  );
  const quote = quoteDiagnostics.find((item) => item.symbol === symbol);
  const displayName =
    quote?.display_name ??
    quote?.name ??
    (candidate ? decisionCandidateDisplayName(candidate) : null);
  if (!displayName || displayName === symbol) {
    return symbol || '--';
  }
  return `${displayName}（${symbol}）`;
}

function tradingPlanManualIntentSummary(
  tradingPlan: DailyTradingPlanResponse,
  candidates: DecisionCandidate[],
  quoteDiagnostics: QuoteDiagnosticItem[],
  locale: Locale,
) {
  const intents = tradingPlan.order_intents.filter(
    (intent) => intent.submission_status === 'manual_confirmation_required',
  );
  const visibleIntents = intents.slice(0, 3);
  const formatter = new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    maximumFractionDigits: 4,
  });
  const summaries = visibleIntents.map((intent) =>
    [
      formatPublicStatus(intent.side, locale),
      tradingPlanIntentInstrumentLabel(intent, candidates, quoteDiagnostics),
      formatter.format(intent.estimated_quantity),
    ].join(' · '),
  );
  const remaining = intents.length - visibleIntents.length;
  if (remaining > 0) {
    summaries.push(
      locale === 'zh'
        ? `另 ${remaining} 笔待确认`
        : `${remaining} more awaiting confirmation`,
    );
  }
  return summaries.join(locale === 'zh' ? '；' : '; ');
}

function primaryOperationsDailyPlanBlocker(
  operations: OperationsTodayResponse | null | undefined,
) {
  const summary = operations?.daily_plan.blocker_summary ?? [];
  if (!operations || operations.daily_plan.blocked_count <= 0) {
    return null;
  }
  return summary[0] ?? null;
}

function isAwaitingRiskGateBlocker(
  blocker: ReturnType<typeof primaryOperationsDailyPlanBlocker>,
) {
  if (!blocker) {
    return false;
  }
  const reasons = blocker.reasons ?? [];
  return (
    blocker.target === 'risk' &&
    (blocker.category === 'evidence_not_ready' ||
      reasons.includes('awaiting_risk_gate') ||
      reasons.includes('risk_gate_not_checked'))
  );
}

function isRiskBlockedBlocker(
  blocker: ReturnType<typeof primaryOperationsDailyPlanBlocker>,
) {
  if (!blocker) {
    return false;
  }
  const reasons = blocker.reasons ?? [];
  return (
    blocker.target === 'risk' &&
    (blocker.category === 'risk_blocked' ||
      reasons.includes('risk_gate_blocked') ||
      reasons.some((reason) =>
        [
          'cash reserve would fall below min_cash_reserve',
          'projected position weight exceeds max_position_weight',
          'cash_buffer_breached',
          'concentration_limit_breached',
        ].includes(reason),
      ))
  );
}

function operationsQueueTarget(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
) {
  const primaryTarget = primarySubsystem?.target ?? operations?.primary_target;
  if (primaryTarget === 'market' || primaryTarget === 'account-truth') {
    return primaryTarget;
  }
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (isAwaitingRiskGateBlocker(blocker) || isRiskBlockedBlocker(blocker)) {
    return 'risk';
  }
  return primaryTarget;
}

function operationsDuplicatesTradingPlanReview(
  operations: OperationsTodayResponse | null | undefined,
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
) {
  if (!operations || !tradingPlan) {
    return false;
  }
  const operationsManualReady = operations.daily_plan.manual_ready_count;
  const nextAction = operationsPrimaryNextAction(operations, primarySubsystem);
  return (
    operations.conclusion_status === 'manual_action_required' &&
    operationsQueueTarget(operations, primarySubsystem) === 'trading' &&
    (nextAction === 'review_manual_order_intents' ||
      nextAction === 'review_manual_confirmation') &&
    operations.daily_plan.blocked_count === 0 &&
    tradingPlan.blocked_count === 0 &&
    operationsManualReady > 0 &&
    tradingPlan.manual_ready_count === operationsManualReady
  );
}

function operationsStatusTitle(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const status = operations?.conclusion_status;
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (isAwaitingRiskGateBlocker(blocker)) {
    return locale === 'zh' ? '风险闸门待检查' : 'Risk gate checks pending';
  }
  if (isRiskBlockedBlocker(blocker)) {
    return locale === 'zh' ? '风控阻断待复核' : 'Risk blocks need review';
  }
  if (locale === 'zh') {
    if (!operations) return '运营状态加载中';
    if (status === 'blocked') return '今日待办存在阻断';
    if (status === 'manual_action_required') return '今日待办需要人工复核';
    if (status === 'degraded') return '今日待办存在降级项';
    return '今日运行状态正常';
  }
  if (!operations) return 'Operations status loading';
  if (status === 'blocked') return 'Today runbook has blockers';
  if (status === 'manual_action_required') {
    return 'Today runbook needs manual review';
  }
  if (status === 'degraded') return 'Today runbook has degraded checks';
  return 'Today runbook is healthy';
}

function riskBlockReasonLabel(reason: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    'cash reserve would fall below min_cash_reserve': {
      en: 'cash buffer would be breached',
      zh: '现金缓冲不足',
    },
    cash_buffer_breached: {
      en: 'cash buffer would be breached',
      zh: '现金缓冲不足',
    },
    'projected position weight exceeds max_position_weight': {
      en: 'single-name weight would exceed policy',
      zh: '单标的仓位过高',
    },
    concentration_limit_breached: {
      en: 'single-name weight would exceed policy',
      zh: '单标的仓位过高',
    },
    risk_gate_blocked: {
      en: 'risk gate blocked the action',
      zh: '风控闸门阻断动作',
    },
  };
  return labels[reason]?.[locale] ?? formatPublicStatus(reason, locale);
}

function riskBlockerDetailText(
  blocker: ReturnType<typeof primaryOperationsDailyPlanBlocker>,
  locale: Locale,
) {
  if (!blocker) {
    return null;
  }
  const reasons = Array.from(
    new Set(
      (blocker.reasons ?? []).map((reason) =>
        riskBlockReasonLabel(reason, locale),
      ),
    ),
  ).slice(0, 3);
  const symbols = (blocker.sample_symbols ?? []).slice(0, 3);
  const reasonText = reasons.length
    ? reasons.join(locale === 'zh' ? '、' : ', ')
    : locale === 'zh'
      ? '风控规则'
      : 'risk policy';
  if (locale === 'zh') {
    const symbolText = symbols.length ? `；涉及 ${symbols.join('、')}` : '';
    return `${blocker.count} 个候选被风控阻断：${reasonText}${symbolText}。先复核原因，不进入人工确认。`;
  }
  const symbolText = symbols.length ? ` Symbols: ${symbols.join(', ')}.` : '';
  return `${blocker.count} candidates are blocked by risk: ${reasonText}.${symbolText} Review the reasons before manual confirmation.`;
}

function numericPaperShadowValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function overviewCountLabel(count: number, singular: string, locale: Locale) {
  if (locale === 'zh') {
    return `${count} ${singular}`;
  }
  return `${count} ${singular}${count === 1 ? '' : 's'}`;
}

function paperShadowOverviewEvidenceSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const paperShadow = operations?.paper_shadow;
  if (!paperShadow) {
    return null;
  }
  const nextStep = paperShadow.next_manual_review_step;
  const shouldSummarize =
    Boolean(paperShadow.manual_handoff) ||
    nextStep === 'review_shadow_divergence' ||
    nextStep === 'resolve_shadow_divergence' ||
    paperShadow.status === 'review_required' ||
    paperShadow.status === 'diverged' ||
    paperShadow.divergence_status === 'review_required' ||
    paperShadow.divergence_status === 'diverged';
  if (!shouldSummarize) {
    return null;
  }
  const summary = paperShadow.divergence_summary;
  const labels =
    locale === 'zh'
      ? {
          prefix: 'Paper/shadow',
          orderIntent: '订单意图',
          simOrder: '模拟订单',
          simFill: '模拟成交',
          diverged: '偏差',
          slippage: '模拟滑点',
          noBrokerSubmission: '不会提交券商订单',
        }
      : {
          prefix: 'Paper/shadow',
          orderIntent: 'order intent',
          simOrder: 'sim order',
          simFill: 'sim fill',
          diverged: 'Diverged',
          slippage: 'Sim slippage',
          noBrokerSubmission: 'No broker submission',
        };
  const countText = [
    overviewCountLabel(
      paperShadow.order_intent_count,
      labels.orderIntent,
      locale,
    ),
    overviewCountLabel(
      paperShadow.simulated_order_count,
      labels.simOrder,
      locale,
    ),
    overviewCountLabel(
      paperShadow.simulated_fill_count,
      labels.simFill,
      locale,
    ),
  ].join(locale === 'zh' ? '，' : ', ');
  const divergedRefs = (
    summary?.execution_comparison?.diverged_order_refs ?? []
  )
    .slice(0, 2)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const slippage = numericPaperShadowValue(
    summary?.cost_summary?.simulated_slippage_cost,
  );
  return [
    `${labels.prefix}: ${countText}`,
    ...paperShadowInputSnapshotSummary(paperShadow, locale),
    divergedRefs.length
      ? `${labels.diverged}: ${divergedRefs.join(locale === 'zh' ? '；' : '; ')}`
      : '',
    paperShadowManualHandoffSummary(paperShadow, locale),
    paperShadowReviewQueueSummary(paperShadow, locale),
    slippage !== null
      ? `${labels.slippage}: ${formatCurrencyValue(slippage)}`
      : '',
    summary?.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowInputSnapshotSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const snapshot = paperShadow.input_snapshot;
  const orderIntentCount = numericPaperShadowValue(
    snapshot?.order_intent_count,
  );
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot?.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot?.input_fingerprint) ??
    stringPaperShadowSnapshotValue(paperShadow.input_fingerprint);
  const labels =
    locale === 'zh'
      ? {
          input: '输入快照',
          orderIntent: '订单意图',
          source: '源决策',
          fingerprint: '指纹',
          safety: '快照安全边界',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          input: 'Input snapshot',
          orderIntent: 'order intent',
          source: 'Source',
          fingerprint: 'Fingerprint',
          safety: 'Snapshot safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const inputParts = [
    orderIntentCount === null
      ? ''
      : `${orderIntentCount} ${labels.orderIntent}${
          locale === 'en' && orderIntentCount !== 1 ? 's' : ''
        }`,
    sourceDecision
      ? `${labels.source} ${formatPublicStatus(sourceDecision, locale)}`
      : '',
    fingerprint ? `${labels.fingerprint} ${fingerprint.slice(0, 12)}` : '',
  ].filter(Boolean);
  const safetyParts = [
    snapshot?.does_not_submit_broker_order === true
      ? labels.noBrokerSubmission
      : '',
    snapshot?.does_not_mutate_production_ledger === true
      ? labels.noLedgerMutation
      : '',
  ].filter(Boolean);
  return [
    inputParts.length ? `${labels.input}: ${inputParts.join(' · ')}` : '',
    safetyParts.length ? `${labels.safety}: ${safetyParts.join(' · ')}` : '',
  ].filter(Boolean);
}

function stringPaperShadowSnapshotValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function paperShadowManualHandoffSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const handoff = paperShadow.manual_handoff;
  if (!handoff) {
    return null;
  }
  const labels =
    locale === 'zh'
      ? {
          prefix: '人工确认交接',
          queue: '复核队列',
          item: '项',
          items: '项',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          prefix: 'Manual handoff',
          queue: 'Review queue',
          item: 'item',
          items: 'items',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const queueCount = handoff.review_queue_count ?? 0;
  return [
    `${labels.prefix}: ${paperShadowManualHandoffStatusLabel(
      handoff.status,
      locale,
    )}`,
    queueCount > 0
      ? `${labels.queue}: ${queueCount} ${
          queueCount === 1 ? labels.item : labels.items
        }`
      : '',
    handoff.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    handoff.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ]
    .filter(Boolean)
    .join(' · ');
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

function paperShadowReviewQueueSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const queue = paperShadow.review_queue ?? [];
  if (queue.length === 0) {
    return null;
  }
  const firstAction = queue[0]?.required_action
    ? operationsNextActionLabel(queue[0].required_action, locale)
    : '';
  const firstDetail = paperShadowReviewQueueItemSummary(queue[0], locale);
  if (locale === 'zh') {
    return [`复核队列：${queue.length} 项`, firstAction, firstDetail]
      .filter(Boolean)
      .join(' · ');
  }
  return [
    `Review queue: ${queue.length} item${queue.length === 1 ? '' : 's'}`,
    firstAction,
    firstDetail,
  ]
    .filter(Boolean)
    .join(' · ');
}

type OverviewPaperShadowReviewQueueItem = NonNullable<
  OperationsTodayResponse['paper_shadow']['review_queue']
>[number];

function paperShadowReviewQueueItemSummary(
  item: OverviewPaperShadowReviewQueueItem | undefined,
  locale: Locale,
) {
  if (!item) {
    return '';
  }
  const labels =
    locale === 'zh'
      ? {
          risk: '风控',
          manual: '人工确认',
          manualReady: '可确认',
          accountTruth: '账户事实',
          cash: '现金',
          constraints: '约束',
          projectedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          queueSlippage: '队列滑点',
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
          manualReady: 'Ready',
          accountTruth: 'Account truth',
          cash: 'Cash',
          constraints: 'Constraints',
          projectedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          queueSlippage: 'Queue slippage',
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
      ? `${labels.manual} ${
          item.manual_confirmation_status === 'ready_for_manual_confirmation'
            ? labels.manualReady
            : formatPublicStatus(item.manual_confirmation_status, locale)
        }`
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
  const constraints = paperShadowStatusCountSummary(
    item.constraint_status_counts,
    locale,
  );
  const costs = [
    paperShadowCurrencySummary(
      labels.projectedFee,
      item.cost_evidence?.estimated_total_fee,
    ),
    paperShadowCurrencySummary(
      labels.simulatedFeeTax,
      item.cost_evidence?.simulated_fee_tax_cost,
    ),
    paperShadowCurrencySummary(
      labels.queueSlippage,
      item.cost_evidence?.simulated_slippage_cost,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const marketContext = [
    paperShadowCurrencySummary(
      labels.expected,
      item.market_context?.expected_price,
    ),
    paperShadowFillPriceSummary(
      labels.fill,
      item.market_context?.simulated_fill_prices,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const omsStatusPath = paperShadowOmsStatusPath(item.oms_status_path, locale);
  const terminalOutcome = paperShadowTerminalOutcomeSummary(item, locale);
  const omsTransition = paperShadowLatestOmsTransition(item, locale);
  const evidence = (item.evidence_refs ?? [])
    .slice(0, 6)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean)
    .join(locale === 'zh' ? '；' : '; ');
  return [
    riskManual,
    accountCash,
    constraints ? `${labels.constraints} ${constraints}` : '',
    costs,
    marketContext,
    terminalOutcome ? `${labels.terminalOutcome}: ${terminalOutcome}` : '',
    omsStatusPath ? `${labels.omsPath}: ${omsStatusPath}` : '',
    omsTransition ? `${labels.omsTransition}: ${omsTransition}` : '',
    evidence ? `${labels.evidence}: ${evidence}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowTerminalOutcomeSummary(
  item: OverviewPaperShadowReviewQueueItem,
  locale: Locale,
) {
  const status = paperShadowOmsStatusLabel(
    item.terminal_status ?? undefined,
    locale,
  );
  const reason = paperShadowTerminalReasonLabel(
    item.terminal_reason ?? undefined,
    locale,
  );
  const transition = item.terminal_oms_transition_ref
    ? formatPublicEvidenceReference(item.terminal_oms_transition_ref, locale)
    : '';
  return [status, reason, transition].filter(Boolean).join(' · ');
}

function paperShadowTerminalReasonLabel(
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

function paperShadowOmsStatusPath(
  values: string[] | undefined,
  locale: Locale,
) {
  if (!values || values.length === 0) {
    return '';
  }
  return values
    .map((value) => paperShadowOmsStatusLabel(value, locale))
    .filter(Boolean)
    .join(' > ');
}

function paperShadowLatestOmsTransition(
  item: OverviewPaperShadowReviewQueueItem,
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
  return `${orderId}${sequence}${paperShadowOmsStatusLabel(
    transition.to_status,
    locale,
  )}`;
}

function paperShadowOmsStatusLabel(
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

function paperShadowStatusCountSummary(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  return Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([key, value]) => `${formatPublicStatus(key, locale)}: ${value}`)
    .join(locale === 'zh' ? '；' : '; ');
}

function paperShadowCurrencySummary(label: string, value: unknown) {
  const numeric = numericPaperShadowValue(value);
  return numeric === null ? '' : `${label} ${formatCurrencyValue(numeric)}`;
}

function paperShadowFillPriceSummary(
  label: string,
  values: unknown[] | undefined,
) {
  const prices = (values ?? [])
    .map((value) => numericPaperShadowValue(value))
    .filter((value): value is number => value !== null)
    .map((value) => formatCurrencyValue(value));
  return prices.length ? `${label} ${prices.join(', ')}` : '';
}

function operationsDetailText(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
  fallback: string,
) {
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (blocker && isAwaitingRiskGateBlocker(blocker)) {
    if (locale === 'zh') {
      return `${blocker.count} 个候选等待风险闸门检查；当前 ${operations?.daily_plan.manual_ready_count ?? 0} 个可人工确认。`;
    }
    return `${blocker.count} candidates are waiting for risk-gate checks; ${operations?.daily_plan.manual_ready_count ?? 0} are ready for manual confirmation.`;
  }
  if (blocker && isRiskBlockedBlocker(blocker)) {
    return riskBlockerDetailText(blocker, locale) ?? fallback;
  }
  const schedulerSummary = operationsSchedulerEvidenceSummary(
    operations,
    locale,
  );
  if (schedulerSummary) {
    return `${fallback} · ${schedulerSummary}`;
  }
  const reconciliationSummary = executionReconciliationOverviewSummary(
    operations,
    locale,
  );
  if (reconciliationSummary) {
    return `${fallback} · ${reconciliationSummary}`;
  }
  const paperShadowSummary = paperShadowOverviewEvidenceSummary(
    operations,
    locale,
  );
  return paperShadowSummary ? `${fallback} · ${paperShadowSummary}` : fallback;
}

function executionReconciliationOverviewSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const reconciliation = operations?.execution_reconciliation;
  if (!reconciliation || reconciliation.open_item_count <= 0) {
    return '';
  }
  const first = reconciliation.first_open_item;
  const manualSummary = first?.manual_execution_evidence_summary;
  const labels =
    locale === 'zh'
      ? {
          reviewCount: '对账复核',
          item: '项',
          items: '项',
          manualExecution: '手工成交',
          preview: '预览',
          noBrokerSubmission: '不会提交券商订单',
          noOmsMutation: '不会修改 OMS',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          reviewCount: 'Reconciliation review',
          item: 'item',
          items: 'items',
          manualExecution: 'Manual execution',
          preview: 'Preview',
          noBrokerSubmission: 'No broker submission',
          noOmsMutation: 'No OMS mutation',
          noLedgerMutation: 'No production ledger mutation',
        };
  const countLabel =
    reconciliation.open_item_count === 1 ? labels.item : labels.items;
  return [
    `${labels.reviewCount}: ${reconciliation.open_item_count} ${countLabel}`,
    operationsNextActionLabel(
      reconciliation.next_review_step || first?.suggested_action || 'none',
      locale,
    ),
    first?.order_id ? `${labels.manualExecution}: ${first.order_id}` : '',
    manualSummary?.preview_fingerprint
      ? `${labels.preview} ${manualSummary.preview_fingerprint}`
      : '',
    reconciliation.does_not_submit_broker_order ||
    manualSummary?.submitted_to_broker === false
      ? labels.noBrokerSubmission
      : '',
    reconciliation.does_not_mutate_oms ||
    manualSummary?.does_not_mutate_oms === true
      ? labels.noOmsMutation
      : '',
    reconciliation.does_not_mutate_production_ledger ||
    manualSummary?.does_not_mutate_production_ledger === true
      ? labels.noLedgerMutation
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function operationsSchedulerEvidenceSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const scheduler = operations?.scheduler;
  if (!scheduler) {
    return '';
  }
  const status = String(scheduler.status ?? '')
    .trim()
    .toLowerCase();
  const isFailure =
    status.endsWith('_failed') || status === 'failed' || status === 'error';
  if (!isFailure && operations?.primary_target !== 'scheduler') {
    return '';
  }

  const parts = [
    scheduler.run_id
      ? locale === 'zh'
        ? `运行 ${scheduler.run_id}`
        : `Run ${scheduler.run_id}`
      : '',
    schedulerInputSnapshotSummary(scheduler, locale),
    schedulerRerunKeySummary(scheduler.idempotency_key, locale),
    schedulerRetrySummary(scheduler.retry_state, locale),
    schedulerErrorSummary(scheduler.error),
    scheduler.does_not_submit_broker_order
      ? locale === 'zh'
        ? '不会提交券商订单'
        : 'No broker submission'
      : '',
  ].filter(Boolean);
  return parts.join(locale === 'zh' ? ' · ' : ' · ');
}

function schedulerInputSnapshotSummary(
  scheduler: NonNullable<OperationsTodayResponse['scheduler']>,
  locale: Locale,
) {
  const snapshot = scheduler.input_snapshot;
  if (!snapshot) {
    return '';
  }
  const orderIntentCount = numericPaperShadowValue(snapshot.order_intent_count);
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot.input_fingerprint) ??
    stringPaperShadowSnapshotValue(scheduler.input_fingerprint);
  const labels =
    locale === 'zh'
      ? {
          input: '输入快照',
          orderIntent: '订单意图',
          source: '源决策',
          fingerprint: '指纹',
        }
      : {
          input: 'Input snapshot',
          orderIntent: 'order intent',
          source: 'Source',
          fingerprint: 'Fingerprint',
        };
  const parts = [
    orderIntentCount === null
      ? ''
      : `${orderIntentCount} ${labels.orderIntent}${
          locale === 'en' && orderIntentCount !== 1 ? 's' : ''
        }`,
    sourceDecision
      ? `${labels.source} ${formatPublicStatus(sourceDecision, locale)}`
      : '',
    fingerprint ? `${labels.fingerprint} ${fingerprint.slice(0, 12)}` : '',
  ].filter(Boolean);
  return parts.length ? `${labels.input}: ${parts.join(' · ')}` : '';
}

function schedulerRerunKeySummary(
  idempotencyKey: string | null | undefined,
  locale: Locale,
) {
  const key = stringPaperShadowSnapshotValue(idempotencyKey);
  if (!key) {
    return '';
  }
  return locale === 'zh' ? `重跑键: ${key}` : `Rerun key: ${key}`;
}

function schedulerRetrySummary(
  retryState: Record<string, unknown> | undefined,
  locale: Locale,
) {
  if (!retryState) {
    return '';
  }
  const attempt = numericRetryValue(retryState.attempt);
  if (attempt <= 0) {
    return '';
  }
  const maxAttempts = Math.max(
    numericRetryValue(retryState.max_attempts),
    attempt,
  );
  const previousAttempts = numericRetryValue(retryState.previous_attempts);
  if (locale === 'zh') {
    return previousAttempts > 0
      ? `重试 ${attempt}/${maxAttempts}；此前 ${previousAttempts} 次`
      : `重试 ${attempt}/${maxAttempts}`;
  }
  return previousAttempts > 0
    ? `Retry ${attempt}/${maxAttempts}; previous attempts ${previousAttempts}`
    : `Retry ${attempt}/${maxAttempts}`;
}

function schedulerErrorSummary(error: Record<string, unknown> | undefined) {
  if (!error) {
    return '';
  }
  const type = String(error.type ?? '').trim();
  const message = String(error.message ?? '').trim();
  if (type && message) {
    return `${type}: ${message}`;
  }
  return type || message;
}

function numericRetryValue(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? Math.trunc(numberValue) : 0;
}

function operationsPrimaryNextAction(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
) {
  if (
    operations?.paper_shadow.review_status ===
      'accepted_for_manual_confirmation' ||
    operations?.paper_shadow.status === 'within_expectations' ||
    operations?.paper_shadow.divergence_status === 'within_expectations'
  ) {
    return operations.paper_shadow.next_manual_review_step;
  }
  return (
    primarySubsystem?.next_action ??
    operations?.paper_shadow.next_manual_review_step
  );
}

function operationsStatusMeta(
  operations: OperationsTodayResponse,
  locale: Locale,
) {
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (blocker && isAwaitingRiskGateBlocker(blocker)) {
    return locale === 'zh'
      ? `${blocker.count} 待检查`
      : `${blocker.count} pending checks`;
  }
  if (blocker && isRiskBlockedBlocker(blocker)) {
    return locale === 'zh'
      ? `${blocker.count} 风控阻断`
      : `${blocker.count} risk blocked`;
  }
  const { blocked, manual_action_required, degraded, pass, total } =
    operations.health;
  if (locale === 'zh') {
    if (blocked > 0) return `${blocked} 阻断`;
    if (operations.conclusion_status === 'degraded' && degraded > 0) {
      return `${degraded} 降级`;
    }
    if (manual_action_required > 0) return `${manual_action_required} 人工复核`;
    if (degraded > 0) return `${degraded} 降级`;
    return `${pass}/${total} 通过`;
  }
  if (blocked > 0) return `${blocked} blocked`;
  if (operations.conclusion_status === 'degraded' && degraded > 0) {
    return `${degraded} degraded`;
  }
  if (manual_action_required > 0) {
    return `${manual_action_required} manual review`;
  }
  if (degraded > 0) return `${degraded} degraded`;
  return `${pass}/${total} passed`;
}

function operationsActionLabel(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsTodayResponse['subsystems'][number] | undefined,
  labels: AppCopy['overview']['dashboard'],
  locale: Locale,
) {
  const target = operationsQueueTarget(operations, primarySubsystem);
  if (target === 'risk') {
    return labels.operationsViewRisk;
  }
  if (target === 'account-truth') {
    return labels.operationsViewAccountTruth;
  }
  if (target === 'market') {
    return labels.operationsViewMarket;
  }
  if (target === 'trading') {
    return labels.operationsViewTrading;
  }
  if (target === 'paper-shadow') {
    return labels.operationsViewPaperShadow;
  }
  return locale === 'zh' ? '查看运行证据' : 'View run evidence';
}

function tradingPlanBlockerCategoryLabel(category: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    account_truth: { en: 'Account truth', zh: '账户事实' },
    market_data: { en: 'Market/NAV data', zh: '行情/净值' },
    portfolio: { en: 'Portfolio constraints', zh: '组合约束' },
    risk: { en: 'Risk gate', zh: '风控闸门' },
    evidence_not_ready: {
      en: 'Evidence not ready',
      zh: '证据未就绪',
    },
    other: { en: 'Other blockers', zh: '其他阻断' },
  };
  return labels[category]?.[locale] ?? formatPublicStatus(category, locale);
}

function tradingPlanBlockerSummaryText(
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  locale: Locale,
) {
  const summary = tradingPlan?.blocker_summary ?? [];
  if (!tradingPlan || tradingPlan.blocked_count <= 0) {
    return null;
  }
  if (summary.length === 0) {
    return locale === 'zh'
      ? `${tradingPlan.blocked_count} 个阻断待归因`
      : `${tradingPlan.blocked_count} blockers need classification`;
  }
  return summary
    .slice(0, 3)
    .map(
      (item) =>
        `${tradingPlanBlockerCategoryLabel(item.category, locale)} ${item.count}`,
    )
    .join(locale === 'zh' ? ' · ' : ' · ');
}

function tradingPlanBlockedDetailText(
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  locale: Locale,
  fallback: string,
) {
  const summary = tradingPlan?.blocker_summary ?? [];
  if (!tradingPlan || tradingPlan.blocked_count <= 0 || summary.length === 0) {
    return fallback;
  }
  const primary = summary[0];
  const primaryLabel = tradingPlanBlockerCategoryLabel(
    primary.category,
    locale,
  );
  if (locale === 'zh') {
    if (primary.category === 'evidence_not_ready') {
      return `${primary.count} 个候选尚未通过风控/证据闸门；当前 ${tradingPlan.manual_ready_count} 个需要人工确认。`;
    }
    return `先处理 ${primaryLabel} ${primary.count} 项，再重新生成今日交易计划。`;
  }
  if (primary.category === 'evidence_not_ready') {
    return `${primary.count} candidates are still waiting on risk/evidence gates; ${tradingPlan.manual_ready_count} need manual confirmation now.`;
  }
  return `Resolve ${primary.count} ${primaryLabel.toLowerCase()} items first, then regenerate today's trading plan.`;
}

export function DashboardTodayQueue({
  overview,
  marketHealth,
  portfolioSnapshot,
  marketEvidenceReview,
  marketEvidenceReviewLoading,
  marketEvidenceReviewError,
  quoteDiagnostics,
  pendingOrders,
  pendingOrdersLoading,
  pendingOrdersError,
  strategyContribution,
  strategyContributionLoading,
  strategyContributionError,
  todayDecision,
  todayDecisionLoading,
  todayDecisionError,
  tradingPlan,
  tradingPlanLoading,
  tradingPlanError,
  operationsToday,
  operationsTodayLoading,
  operationsTodayError,
}: {
  overview: AccountOverview;
  marketHealth?: MarketDataHealthResponse;
  portfolioSnapshot: PortfolioSnapshot;
  marketEvidenceReview?: CurrentHoldingMarketEvidenceReview | null;
  marketEvidenceReviewLoading: boolean;
  marketEvidenceReviewError: boolean;
  quoteDiagnostics: QuoteDiagnosticItem[];
  pendingOrders: ManualOrder[];
  pendingOrdersLoading: boolean;
  pendingOrdersError: boolean;
  strategyContribution?: AccountStrategyContributionReport | null;
  strategyContributionLoading: boolean;
  strategyContributionError: boolean;
  todayDecision?: DecisionResponse | null;
  todayDecisionLoading: boolean;
  todayDecisionError: boolean;
  tradingPlan?: DailyTradingPlanResponse | null;
  tradingPlanLoading: boolean;
  tradingPlanError: boolean;
  operationsToday?: OperationsTodayResponse | null;
  operationsTodayLoading: boolean;
  operationsTodayError: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const instrumentDiagnostics = [
    ...quoteDiagnostics,
    ...(marketHealth?.quotes ?? []),
  ];
  const marketReviewContractValid = currentHoldingMarketReviewContractIsValid(
    marketEvidenceReview,
    portfolioSnapshot,
  );
  const marketReviewUnavailable =
    marketEvidenceReviewError ||
    (!marketEvidenceReviewLoading && !marketReviewContractValid);
  const marketReviewIdentityBlocked =
    marketReviewContractValid &&
    marketEvidenceReview?.status === 'blocked_identity';
  const dataNeedsReview = Boolean(
    marketReviewUnavailable ||
    marketReviewIdentityBlocked ||
    marketEvidenceReview?.status === 'review_required',
  );
  const dataDetail = marketEvidenceReviewLoading
    ? labels.dataReviewLoading
    : marketReviewUnavailable
      ? labels.dataReviewUnavailable
      : marketReviewIdentityBlocked
        ? labels.dataReviewIdentityBlocked
        : marketEvidenceReview?.status === 'review_required'
          ? currentHoldingMarketReviewSummary(marketEvidenceReview, labels)
          : `${labels.valuationTime}: ${formatTimestamp(
              marketEvidenceReview?.valuation_as_of ??
                overview.valuation_timestamp,
            )}`;
  const dataMeta = marketEvidenceReviewLoading
    ? copy.states.loading
    : marketReviewUnavailable
      ? '--'
      : marketEvidenceReview?.status === 'review_required'
        ? labels.affectedCount(marketEvidenceReview.review_required_count)
        : labels.dataReviewConfirmedCount(
            marketEvidenceReview?.confirmed_holding_count ?? 0,
          );
  const dataTone: TodayQueueTone = marketReviewUnavailable
    ? 'danger'
    : dataNeedsReview
      ? 'warning'
      : marketEvidenceReviewLoading
        ? 'neutral'
        : 'success';
  const dataPriority: TodayQueuePriority = marketReviewUnavailable
    ? 'first'
    : dataNeedsReview
      ? 'first'
      : 'normal';
  const dataRefreshSymbols =
    marketReviewContractValid &&
    marketEvidenceReview?.status === 'review_required'
      ? marketEvidenceReview.refreshable_symbols
      : [];
  const strategyReady = canUseStrategyContribution(strategyContribution);
  const strategyHasNoLinkedFills =
    strategyContribution?.contribution_status === 'no_linked_fills' &&
    strategyContribution.linked_fill_count === 0 &&
    (strategyContribution.unattributed_fill_count ?? 0) === 0;
  const strategyStatus = strategyContribution?.contribution_status
    ? (copy.backtest.page.accountStrategyContributionStatusMap[
        strategyContribution.contribution_status as keyof typeof copy.backtest.page.accountStrategyContributionStatusMap
      ] ?? formatPublicStatus(strategyContribution.contribution_status, locale))
    : copy.backtest.page.accountStrategyContributionStatusMap.no_linked_fills;
  const strategyNextAction = strategyContribution?.next_manual_action
    ? (copy.backtest.page.accountStrategyNextActionMap[
        strategyContribution.next_manual_action as keyof typeof copy.backtest.page.accountStrategyNextActionMap
      ] ?? formatPublicStatus(strategyContribution.next_manual_action, locale))
    : copy.backtest.page.accountStrategyContributionHiddenUntilEvidence;
  const strategyHref = strategyContributionReviewHref(strategyContribution);
  const strategyActionLabel = strategyHref.startsWith('/market')
    ? labels.viewData
    : strategyHref.startsWith('/operations')
      ? labels.viewOperations
      : labels.viewStrategy;
  const candidates = todayDecision?.candidates ?? [];
  const leadingCandidate = candidates[0];
  const decisionActionLabel = leadingCandidate
    ? (labels.decisionActionLabels[leadingCandidate.action] ??
      formatPublicStatus(leadingCandidate.action, locale))
    : null;
  const decisionCandidateDetail = leadingCandidate
    ? `${decisionActionLabel} · ${decisionCandidateDisplayName(leadingCandidate)}`
    : labels.strategyCandidateEmptyDetail;
  const cashShortfall =
    tradingPlan?.order_intents.find(
      (intent) => (intent.cash_shortfall ?? 0) > 0,
    )?.cash_shortfall ?? 0;
  const tradingPlanTitle = tradingPlanError
    ? labels.tradingPlanUnavailable
    : tradingPlan?.conclusion_status === 'cash_shortfall'
      ? labels.tradingPlanCashShortfall
      : (tradingPlan?.manual_ready_count ?? 0) > 0
        ? labels.tradingPlanManualReady(tradingPlan?.manual_ready_count ?? 0)
        : (tradingPlan?.blocked_count ?? 0) > 0
          ? labels.tradingPlanNeedsReview
          : (tradingPlan?.candidate_pool_count ?? candidates.length) > 0
            ? labels.strategyCandidateAction
            : labels.strategyCandidateClear;
  const tradingPlanDetail = tradingPlanError
    ? labels.tradingPlanUnavailable
    : tradingPlanLoading
      ? labels.tradingPlanLoading
      : tradingPlan?.conclusion_status === 'cash_shortfall'
        ? labels.tradingPlanCashShortfallDetail(
            formatCurrencyValue(cashShortfall),
          )
        : (tradingPlan?.manual_ready_count ?? 0) > 0
          ? tradingPlan && tradingPlan.order_intents.length > 0
            ? tradingPlanManualIntentSummary(
                tradingPlan,
                candidates,
                instrumentDiagnostics,
                locale,
              )
            : labels.tradingPlanManualReadyDetail(
                tradingPlan?.manual_ready_count ?? 0,
              )
          : (tradingPlan?.blocked_count ?? 0) > 0
            ? tradingPlanBlockedDetailText(
                tradingPlan,
                locale,
                labels.tradingPlanBlockedDetail(
                  tradingPlan?.blocked_count ?? 0,
                ),
              )
            : decisionCandidateDetail;
  const tradingPlanBlockerSummary = tradingPlanBlockerSummaryText(
    tradingPlan,
    locale,
  );
  const tradingPlanMeta = tradingPlanLoading
    ? copy.states.loading
    : tradingPlan
      ? tradingPlanBlockerSummary
        ? labels.tradingPlanMeta(
            tradingPlan.manual_ready_count,
            tradingPlan.candidate_pool_count,
            tradingPlanBlockerSummary,
          )
        : labels.tradingPlanMeta(
            tradingPlan.manual_ready_count,
            tradingPlan.candidate_pool_count,
            tradingPlan.blocked_count,
          )
      : labels.candidateCount(candidates.length);
  const tradingPlanTone: TodayQueueTone = tradingPlanError
    ? 'danger'
    : (tradingPlan?.manual_ready_count ?? 0) > 0 ||
        (tradingPlan?.blocked_count ?? 0) > 0 ||
        candidates.length > 0
      ? 'warning'
      : 'success';
  const tradingPlanPriority: TodayQueuePriority =
    tradingPlanError ||
    tradingPlan?.conclusion_status === 'cash_shortfall' ||
    (tradingPlan?.manual_ready_count ?? 0) > 0
      ? 'first'
      : (tradingPlan?.blocked_count ?? 0) > 0 || candidates.length > 0
        ? 'watch'
        : 'normal';
  const operationsPrimarySubsystem =
    operationsToday?.subsystems.find(
      (item) =>
        item.target === operationsToday.primary_target &&
        item.status === operationsToday.conclusion_status,
    ) ??
    operationsToday?.subsystems.find(
      (item) => item.status === operationsToday.conclusion_status,
    );
  const operationsPrimaryTarget = operationsQueueTarget(
    operationsToday,
    operationsPrimarySubsystem,
  );
  const operationsPrimaryAttention =
    operationsToday?.attention_items?.find(
      (item) => item.subsystem_id === operationsPrimarySubsystem?.id,
    ) ??
    operationsToday?.attention_items?.find(
      (item) => item.target === operationsPrimaryTarget,
    );
  const operationsResolution = operationsPrimaryAttention
    ? labels.resolutionCondition(
        operationsAttentionResolutionLabel(
          operationsPrimaryAttention.resolution_condition,
          locale,
        ),
      )
    : undefined;
  const decisionAttention =
    operationsToday?.attention_items?.find(
      (item) => item.subsystem_id === 'daily_trading_plan',
    ) ??
    operationsToday?.attention_items?.find(
      (item) => item.subsystem_id === 'strategy_candidates',
    );
  const decisionResolution = decisionAttention
    ? labels.resolutionCondition(
        operationsAttentionResolutionLabel(
          decisionAttention.resolution_condition,
          locale,
        ),
      )
    : undefined;
  const operationsTone: TodayQueueTone = operationsTodayError
    ? 'danger'
    : operationsToday?.conclusion_status === 'blocked'
      ? 'danger'
      : operationsToday?.conclusion_status === 'manual_action_required' ||
          operationsToday?.conclusion_status === 'degraded'
        ? 'warning'
        : 'success';
  const operationsPriority: TodayQueuePriority =
    operationsTodayError ||
    operationsToday?.conclusion_status === 'blocked' ||
    operationsToday?.conclusion_status === 'manual_action_required'
      ? 'first'
      : operationsToday?.conclusion_status === 'degraded'
        ? 'watch'
        : 'normal';
  const hideDuplicateOperationsReview =
    (dataNeedsReview && operationsPrimaryTarget === 'market') ||
    operationsDuplicatesTradingPlanReview(
      operationsToday,
      tradingPlan,
      operationsPrimarySubsystem,
    );

  const allItems: TodayQueueItem[] = [
    {
      key: 'operations',
      title: operationsTodayError
        ? locale === 'zh'
          ? '运营状态不可用'
          : 'Operations status unavailable'
        : operationsStatusTitle(operationsToday, locale),
      detail: operationsTodayLoading
        ? copy.states.loading
        : operationsToday
          ? operationsDetailText(
              operationsToday,
              locale,
              operationsNextActionLabel(
                operationsPrimaryNextAction(
                  operationsToday,
                  operationsPrimarySubsystem,
                ),
                locale,
              ),
            )
          : copy.states.loading,
      meta: operationsTodayLoading
        ? copy.states.loading
        : operationsToday
          ? operationsStatusMeta(operationsToday, locale)
          : '--',
      href: operationsTargetHref(operationsPrimaryTarget),
      actionLabel: operationsActionLabel(
        operationsToday,
        operationsPrimarySubsystem,
        labels,
        locale,
      ),
      tone: operationsTone,
      priority: operationsPriority,
      resolution: operationsResolution,
    },
    {
      key: 'data',
      title: marketEvidenceReviewLoading
        ? labels.dataReviewLoading
        : dataNeedsReview
          ? labels.dataNeedsReview
          : labels.dataUsable,
      detail: dataDetail,
      meta: dataMeta,
      href: '/market#current-holding-evidence-review',
      actionLabel: labels.viewData,
      tone: dataTone,
      priority: dataPriority,
      resolution:
        dataNeedsReview && !marketEvidenceReviewLoading
          ? labels.dataResolutionCondition
          : undefined,
    },
    {
      key: 'decision',
      title: todayDecisionError
        ? labels.strategyDecisionUnavailable
        : tradingPlanTitle,
      detail:
        todayDecisionLoading || tradingPlanLoading
          ? labels.strategyCandidateLoading
          : tradingPlanDetail,
      meta:
        todayDecisionLoading || tradingPlanLoading
          ? copy.states.loading
          : tradingPlanMeta,
      href: '/decision',
      actionLabel: labels.viewDecision,
      tone: todayDecisionError ? 'danger' : tradingPlanTone,
      priority: todayDecisionError ? 'watch' : tradingPlanPriority,
      resolution:
        todayDecisionLoading || tradingPlanLoading
          ? undefined
          : decisionResolution,
    },
    {
      key: 'orders',
      title: pendingOrdersError
        ? copy.trading.orders.loadFailed
        : pendingOrders.length > 0
          ? labels.pendingOrdersReady
          : labels.pendingOrdersClear,
      detail: pendingOrdersLoading
        ? copy.trading.orders.loading
        : pendingOrders.length > 0
          ? labels.pendingCount(pendingOrders.length)
          : labels.pendingEmptyDetail,
      meta: pendingOrdersLoading
        ? copy.states.loading
        : labels.pendingCount(pendingOrders.length),
      href: '/trading',
      actionLabel: labels.viewTrading,
      tone: pendingOrdersError
        ? 'danger'
        : pendingOrders.length > 0
          ? 'warning'
          : 'success',
      priority:
        pendingOrdersError || pendingOrders.length > 0 ? 'first' : 'normal',
    },
    {
      key: 'strategy',
      title: strategyContributionLoading
        ? copy.backtest.page.accountStrategyContributionLoading
        : strategyContributionError
          ? labels.strategyUnavailable
          : strategyReady
            ? labels.strategyEvidenceLinked
            : strategyHasNoLinkedFills
              ? labels.strategyNoLinkedFills
              : labels.strategyEvidenceRequired,
      detail: strategyContributionLoading
        ? copy.backtest.page.accountStrategyContributionLoading
        : strategyReady && strategyContribution
          ? `${copy.backtest.page.accountStrategyNetContribution}: ${formatCurrencyValue(
              strategyContribution.net_contribution,
            )}`
          : strategyNextAction,
      meta: strategyContributionLoading ? copy.states.loading : strategyStatus,
      href: strategyHref,
      actionLabel: strategyActionLabel,
      tone: strategyContributionError
        ? 'danger'
        : strategyContributionLoading
          ? 'neutral'
          : strategyReady || strategyHasNoLinkedFills
            ? 'success'
            : 'warning',
      priority: strategyContributionError
        ? 'watch'
        : strategyContributionLoading
          ? 'normal'
          : strategyReady || strategyHasNoLinkedFills
            ? 'normal'
            : 'watch',
      resolution: strategyContributionLoading
        ? undefined
        : strategyHasNoLinkedFills
          ? labels.strategyNoLinkedFillsResolution
          : strategyReady
            ? undefined
            : labels.strategyEvidenceResolution,
    },
  ];
  const items = allItems.filter(
    (item) => !(hideDuplicateOperationsReview && item.key === 'operations'),
  );
  const actionableCount = items.filter(
    (item) => item.priority !== 'normal',
  ).length;
  const exceptionItems: ExceptionItem[] = items
    .filter((item) => item.priority !== 'normal')
    .sort(
      (left, right) =>
        TODAY_QUEUE_PRIORITY_ORDER.indexOf(left.priority) -
        TODAY_QUEUE_PRIORITY_ORDER.indexOf(right.priority),
    )
    .map((item) => ({
      id: item.key,
      severity:
        item.tone === 'danger'
          ? 'danger'
          : item.tone === 'warning'
            ? 'warning'
            : 'info',
      statusLabel: todayQueuePriorityLabel(item.priority, labels),
      title: item.title,
      reason: item.detail,
      unblockCondition: item.resolution,
      nextAction:
        item.key === 'data' && dataRefreshSymbols.length > 0 ? (
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
            <MarketRefreshButton compact symbols={dataRefreshSymbols} />
            <a
              href={item.href}
              className="inline-flex min-h-8 items-center font-semibold text-[var(--app-accent)] hover:underline"
            >
              {item.actionLabel}
            </a>
          </div>
        ) : (
          <a
            href={item.href}
            className="font-semibold text-[var(--app-accent)] hover:underline"
          >
            {item.actionLabel}
          </a>
        ),
      evidence: item.meta,
    }));
  const normalCount = items.length - actionableCount;
  const primaryExceptionItems = exceptionItems.slice(0, 1);
  const additionalExceptionItems = exceptionItems.slice(1);
  const exceptionLabels =
    locale === 'zh'
      ? {
          reason: '阻断原因',
          unblockCondition: '解除条件',
          nextAction: '安全下一步',
          evidence: '证据',
        }
      : {
          reason: 'Reason',
          unblockCondition: 'Unblock condition',
          nextAction: 'Safe next step',
          evidence: 'Evidence',
        };

  return (
    <section className="min-w-0" data-testid="overview-today-queue">
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {labels.dailyWorkbench}
          </div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {labels.todayToReview}
          </h2>
        </div>
        <span className="text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]">
          {actionableCount}
        </span>
      </div>
      <ExceptionList
        items={primaryExceptionItems}
        ariaLabel={labels.todayToReview}
        emptyState={labels.noActionItems}
        density="compact"
        className="app-overview-primary-exception"
        labels={exceptionLabels}
      />
      {additionalExceptionItems.length > 0 ? (
        <details
          data-testid="overview-today-queue-more"
          className="group border-b border-[var(--app-divider)]"
        >
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
            <span>
              {labels.additionalReviewItems(additionalExceptionItems.length)}
            </span>
            <ChevronDown
              className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"
              aria-hidden="true"
            />
          </summary>
          <ExceptionList
            items={additionalExceptionItems}
            ariaLabel={labels.additionalReviewItems(
              additionalExceptionItems.length,
            )}
            emptyState={labels.noActionItems}
            density="compact"
            className="border-b-0"
            labels={exceptionLabels}
          />
        </details>
      ) : null}
      {normalCount > 0 ? (
        <div
          data-testid="overview-today-queue-normal"
          className="mt-2 border-y border-[var(--app-divider)] px-3 py-2 text-xs text-[var(--app-text-tertiary)]"
        >
          {todayQueuePriorityLabel('normal', labels)} · {normalCount}
        </div>
      ) : null}
    </section>
  );
}
