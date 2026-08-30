import { formatCurrency as formatCurrencyValue } from '../../../shared/format';
import type { AppCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import type {
  DailyTradingPlanResponse,
  DecisionCandidate,
  DecisionResponse,
  QuoteDiagnosticItem,
} from '../overview-feature-boundary';
import type { TodayQueueItem } from './today-queue-types';

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

function tradingPlanBlockerCategoryLabel(category: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    account_truth: { en: 'Account truth', zh: '账户事实' },
    market_data: { en: 'Market/NAV data', zh: '行情/净值' },
    portfolio: { en: 'Portfolio constraints', zh: '组合约束' },
    risk: { en: 'Risk gate', zh: '风控闸门' },
    evidence_not_ready: { en: 'Evidence not ready', zh: '证据未就绪' },
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
    .join(' · ');
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

function visibleResearchOperationPreview(
  tradingPlan: DailyTradingPlanResponse | null | undefined,
) {
  const preview = tradingPlan?.research_operation_preview;
  if (
    !tradingPlan ||
    tradingPlan.candidate_pool_count !== 0 ||
    tradingPlan.blocked_count !== 0 ||
    tradingPlan.order_intent_count !== 0 ||
    preview?.schema_version !==
      'karkinos.decision.research_operation_preview.v1' ||
    preview.status !== 'available' ||
    preview.operations.length === 0 ||
    !preview.target_market_date ||
    preview.market_calendar_evidence_refs.length === 0 ||
    !preview.dataset_snapshot_id ||
    !preview.formula_fingerprint ||
    preview.account_qualification_status !== 'not_evaluated' ||
    preview.account_positions_evaluated !== false ||
    preview.research_only !== true ||
    preview.executable !== false ||
    preview.authorizes_order_creation !== false ||
    preview.authorizes_execution !== false ||
    preview.authority_effect !== 'none'
  ) {
    return null;
  }
  return preview;
}

function researchOperationSummary(
  preview: NonNullable<DailyTradingPlanResponse['research_operation_preview']>,
  tradingPlan: DailyTradingPlanResponse,
  candidates: DecisionCandidate[],
  quoteDiagnostics: QuoteDiagnosticItem[],
  locale: Locale,
) {
  const formatter = new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    style: 'percent',
    maximumFractionDigits: 1,
  });
  const buyCandidates = preview.operations.filter(
    (operation) => operation.operation === 'buy_candidate',
  );
  const exitCandidateCount = preview.operations.filter(
    (operation) => operation.operation === 'exit_if_held_candidate',
  ).length;
  const instrumentProjection = tradingPlan.research_operation_instruments;
  const persistedNames =
    instrumentProjection?.schema_version ===
      'karkinos.decision.research_operation_instruments.v1' &&
    instrumentProjection.provider_contacted === false &&
    instrumentProjection.database_writes_performed === false &&
    instrumentProjection.read_only === true &&
    instrumentProjection.research_only === true &&
    instrumentProjection.authority_effect === 'none'
      ? new Map(
          instrumentProjection.items.map((item) => [
            item.symbol,
            item.display_name,
          ]),
        )
      : new Map<string, string>();
  const instrumentLabel = (symbol: string) => {
    const quote = quoteDiagnostics.find((item) => item.symbol === symbol);
    const candidate = candidates.find((item) => item.symbol === symbol);
    const displayName =
      persistedNames.get(symbol) ??
      quote?.display_name ??
      quote?.name ??
      (candidate ? decisionCandidateDisplayName(candidate) : null);
    if (!displayName || displayName === symbol) {
      return locale === 'zh'
        ? `名称待补全（${symbol}）`
        : `name unavailable (${symbol})`;
    }
    return `${displayName}（${symbol}）`;
  };
  const summaries = buyCandidates
    .slice(0, 3)
    .map((operation) =>
      locale === 'zh'
        ? `买入研究候选 ${instrumentLabel(operation.symbol)} · 目标权重 ${formatter.format(operation.target_weight)}`
        : `buy research candidate ${instrumentLabel(operation.symbol)} (target weight ${formatter.format(operation.target_weight)})`,
    );
  const remainingBuys = buyCandidates.length - summaries.length;
  if (remainingBuys > 0) {
    summaries.push(
      locale === 'zh'
        ? `另 ${remainingBuys} 个买入研究候选`
        : `${remainingBuys} more buy research candidates`,
    );
  }
  if (exitCandidateCount > 0) {
    summaries.push(
      locale === 'zh'
        ? `${exitCandidateCount} 个若持有则退出候选（账户持仓未评估）`
        : `${exitCandidateCount} exit-if-held candidates (account positions not evaluated)`,
    );
  }
  return summaries.join(locale === 'zh' ? '；' : '; ');
}

export function buildDecisionQueueItem({
  todayDecision,
  todayDecisionLoading,
  todayDecisionError,
  tradingPlan,
  tradingPlanLoading,
  tradingPlanError,
  instrumentDiagnostics,
  resolution,
  copy,
  locale,
}: {
  todayDecision?: DecisionResponse | null;
  todayDecisionLoading: boolean;
  todayDecisionError: boolean;
  tradingPlan?: DailyTradingPlanResponse | null;
  tradingPlanLoading: boolean;
  tradingPlanError: boolean;
  instrumentDiagnostics: QuoteDiagnosticItem[];
  resolution?: string;
  copy: AppCopy;
  locale: Locale;
}): TodayQueueItem {
  const labels = copy.overview.dashboard;
  const candidates = todayDecision?.candidates ?? [];
  const researchPreview = visibleResearchOperationPreview(tradingPlan);
  const leadingCandidate = candidates[0];
  const decisionActionLabel = leadingCandidate
    ? (labels.decisionActionLabels[leadingCandidate.action] ??
      formatPublicStatus(leadingCandidate.action, locale))
    : null;
  const candidateDetail = leadingCandidate
    ? `${decisionActionLabel} · ${decisionCandidateDisplayName(leadingCandidate)}`
    : labels.strategyCandidateEmptyDetail;
  const cashShortfall =
    tradingPlan?.order_intents.find(
      (intent) => (intent.cash_shortfall ?? 0) > 0,
    )?.cash_shortfall ?? 0;
  const title = tradingPlanError
    ? labels.tradingPlanUnavailable
    : tradingPlan?.conclusion_status === 'cash_shortfall'
      ? labels.tradingPlanCashShortfall
      : (tradingPlan?.manual_ready_count ?? 0) > 0
        ? labels.tradingPlanManualReady(tradingPlan?.manual_ready_count ?? 0)
        : (tradingPlan?.blocked_count ?? 0) > 0
          ? labels.tradingPlanNeedsReview
          : (tradingPlan?.candidate_pool_count ?? candidates.length) > 0
            ? labels.strategyCandidateAction
            : researchPreview
              ? labels.researchOperationCandidate
              : labels.strategyCandidateClear;
  const detail = tradingPlanError
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
            : candidateDetail;
  const resolvedDetail = researchPreview
    ? labels.researchOperationDetail(
        researchOperationSummary(
          researchPreview,
          tradingPlan!,
          candidates,
          instrumentDiagnostics,
          locale,
        ),
      )
    : detail;
  const blockerSummary = tradingPlanBlockerSummaryText(tradingPlan, locale);
  const meta = tradingPlanLoading
    ? copy.states.loading
    : tradingPlan
      ? blockerSummary
        ? labels.tradingPlanMeta(
            tradingPlan.manual_ready_count,
            tradingPlan.candidate_pool_count,
            blockerSummary,
          )
        : labels.tradingPlanMeta(
            tradingPlan.manual_ready_count,
            tradingPlan.candidate_pool_count,
            tradingPlan.blocked_count,
          )
      : labels.candidateCount(candidates.length);
  const resolvedMeta = researchPreview
    ? labels.researchOperationMeta(
        researchPreview.operations.length,
        researchPreview.market_date ?? '--',
        researchPreview.target_market_date ?? '--',
      )
    : meta;
  const tone = tradingPlanError
    ? 'danger'
    : (tradingPlan?.manual_ready_count ?? 0) > 0 ||
        (tradingPlan?.blocked_count ?? 0) > 0 ||
        candidates.length > 0
      ? 'warning'
      : researchPreview
        ? 'neutral'
        : 'success';
  const priority =
    tradingPlanError ||
    tradingPlan?.conclusion_status === 'cash_shortfall' ||
    (tradingPlan?.manual_ready_count ?? 0) > 0
      ? 'first'
      : (tradingPlan?.blocked_count ?? 0) > 0 || candidates.length > 0
        ? 'watch'
        : researchPreview
          ? 'watch'
          : 'normal';
  return {
    key: 'decision',
    title: todayDecisionError ? labels.strategyDecisionUnavailable : title,
    detail:
      todayDecisionLoading || tradingPlanLoading
        ? labels.strategyCandidateLoading
        : resolvedDetail,
    meta:
      todayDecisionLoading || tradingPlanLoading
        ? copy.states.loading
        : resolvedMeta,
    href: researchPreview ? '/ai-research' : '/decision',
    actionLabel: researchPreview ? labels.viewAiResearch : labels.viewDecision,
    tone: todayDecisionError ? 'danger' : tone,
    priority: todayDecisionError ? 'watch' : priority,
    alwaysVisible: researchPreview !== null,
    resolution:
      todayDecisionLoading || tradingPlanLoading
        ? undefined
        : researchPreview
          ? labels.researchOperationResolution
          : resolution,
  };
}
