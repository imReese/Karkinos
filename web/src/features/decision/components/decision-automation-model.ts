import { type Locale } from '../../../shared/preferences/context';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  type AutomationCockpitResponse,
  type BrokerGatewayCapability,
} from '../decision-feature-boundary';
import { objectRecord } from './decision-status-model';
import {
  numericSnapshotValue,
  stringSnapshotValue,
} from './decision-trading-plan-model';
import { controlledOrderJourneyNextActionLabel } from './decision-execution-model';
import { automationRecommendedActionLabel } from './decision-operator-action-labels';

export function automationModeLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    paper_shadow: { en: 'paper/shadow only', zh: '仅 paper/shadow' },
    manual_confirmation: { en: 'manual confirmation', zh: '人工确认' },
    disabled: { en: 'disabled', zh: '已停用' },
    live_like: { en: 'live-like gated', zh: '类实盘门禁' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

export function automationExecutionMode(cockpit: AutomationCockpitResponse) {
  return (
    cockpit.automation_status.mode ??
    cockpit.automation_status.default_execution_mode ??
    '--'
  );
}

export function strategyPromotionStageLabel(value: string, locale: Locale) {
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

export function strategyPromotionGateStatusLabel(
  value: string,
  locale: Locale,
) {
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

export function strategyPromotionLifecycleLabels(
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

export function strategyPromotionMissingRequirementsLabel(
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

export function automationNextAction(
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
  const controlledOrderAction =
    cockpit.controlled_execution?.primary_attention_order_journey
      ?.next_operator_action ??
    cockpit.controlled_execution?.latest_order_journey?.next_operator_action;
  if (controlledOrderAction) {
    return controlledOrderJourneyNextActionLabel(controlledOrderAction, locale);
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

export function automationOpenAlertReviewLabels(
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
  const snapshotLabel = automationOpenAlertInputSnapshotLabel(payload, locale);
  if (snapshotLabel) {
    labels.push(snapshotLabel);
  }
  const rerunKeyLabel = automationOpenAlertRerunKeyLabel(payload, locale);
  if (rerunKeyLabel) {
    labels.push(rerunKeyLabel);
  }
  const retryLabel = automationOpenAlertRetryLabel(payload, locale);
  if (retryLabel) {
    labels.push(retryLabel);
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

function automationOpenAlertInputSnapshotLabel(
  payload: Record<string, unknown> | null,
  locale: Locale,
) {
  const snapshot = objectRecord(payload?.input_snapshot);
  if (!snapshot) {
    return '';
  }
  const orderIntentCount = numericSnapshotValue(snapshot.order_intent_count);
  const sourceDecision = stringSnapshotValue(snapshot.source_decision);
  const fingerprint =
    stringSnapshotValue(snapshot.input_fingerprint) ??
    stringSnapshotValue(payload?.input_fingerprint);
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

function automationOpenAlertRerunKeyLabel(
  payload: Record<string, unknown> | null,
  locale: Locale,
) {
  const key = stringSnapshotValue(payload?.idempotency_key);
  if (!key) {
    return '';
  }
  return locale === 'zh' ? `重跑键: ${key}` : `Rerun key: ${key}`;
}

function automationOpenAlertRetryLabel(
  payload: Record<string, unknown> | null,
  locale: Locale,
) {
  const retryState = objectRecord(payload?.retry_state);
  const attempt = numericSnapshotValue(retryState?.attempt);
  if (attempt === null || attempt <= 0) {
    return '';
  }
  const maxAttempts = Math.max(
    numericSnapshotValue(retryState?.max_attempts) ?? attempt,
    attempt,
  );
  const previousAttempts =
    numericSnapshotValue(retryState?.previous_attempts) ?? 0;
  if (locale === 'zh') {
    return previousAttempts > 0
      ? `重试 ${attempt}/${maxAttempts}；此前 ${previousAttempts} 次`
      : `重试 ${attempt}/${maxAttempts}`;
  }
  return previousAttempts > 0
    ? `Retry ${attempt}/${maxAttempts}; previous attempts ${previousAttempts}`
    : `Retry ${attempt}/${maxAttempts}`;
}

export function brokerGatewayDisplayName(
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

export function brokerGatewayStatusLabel(status: string, locale: Locale) {
  if (status === 'blocked_by_kill_switch') {
    return locale === 'zh' ? '被熔断开关阻断' : 'Blocked by kill switch';
  }
  if (status === 'blocked_by_trading_controls_unavailable') {
    return locale === 'zh'
      ? '交易控制不可用，已阻断'
      : 'Blocked: trading controls unavailable';
  }
  return formatPublicStatus(status, locale);
}

export function brokerGatewayBlockedReason(
  gateway: BrokerGatewayCapability,
  locale: Locale,
) {
  if (gateway.status === 'blocked_by_trading_controls_unavailable') {
    return locale === 'zh'
      ? '缺少可验证的交易控制快照；恢复控制状态并重新复核前，人工工单保持阻断。'
      : 'No verifiable trading-control snapshot is available. Restore control state and review again before generating a manual ticket.';
  }
  return gateway.blocked_reason ?? null;
}

export function controlledBridgePolicyStatusLabel(
  status: string,
  locale: Locale,
) {
  if (status === 'configured_non_submitting') {
    return locale === 'zh' ? '已配置，不提交' : 'Configured, no submission';
  }
  if (status === 'incomplete_whitelist') {
    return locale === 'zh' ? '白名单不完整' : 'Incomplete whitelist';
  }
  return formatPublicStatus(status, locale);
}

export function controlledBridgeListSummary(
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

export function controlledBridgeTokenList(
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

export function brokerConnectorStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    collector_evidence_clear: {
      en: 'Persisted evidence clear',
      zh: '持久化证据清晰',
    },
    collector_evidence_missing: {
      en: 'Explicit ingestion required',
      zh: '需要显式采集',
    },
    collector_evidence_pending: {
      en: 'Collector evidence pending',
      zh: '采集证据待提交',
    },
    collector_evidence_blocked: {
      en: 'Collector evidence blocked',
      zh: '采集证据阻断',
    },
    collector_evidence_unavailable: {
      en: 'Evidence store unavailable',
      zh: '证据库不可用',
    },
    disabled: { en: 'Registration disabled', zh: '注册已停用' },
  };
  if (labels[status]) {
    return labels[status][locale];
  }
  return formatPublicStatus(status, locale);
}

export function currentPerOrderReviewStatusLabel(
  status: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    unavailable: { en: 'Review source unavailable', zh: '复核来源不可用' },
    blocked_source: { en: 'Review source blocked', zh: '复核来源已阻断' },
    review_ready: { en: 'Exact review ready', zh: '精确复核已就绪' },
    blocked_review: { en: 'Evidence review blocked', zh: '证据复核已阻断' },
    no_current_candidates: {
      en: 'No current candidate · default off',
      zh: '无当前候选 · 默认关闭',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}
