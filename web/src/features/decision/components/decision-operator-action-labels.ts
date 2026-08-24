import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';

export function automationRecommendedActionLabel(
  value: string,
  locale: Locale,
) {
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
    review_current_per_order_source_blockers: {
      en: 'review current per-order evidence source',
      zh: '复核当前逐单证据来源',
    },
    resolve_current_per_order_evidence_blockers: {
      en: 'resolve current per-order evidence blockers',
      zh: '处理当前逐单证据阻断',
    },
    paper_shadow_available: {
      en: 'run intraday paper/shadow',
      zh: '运行盘中 paper/shadow',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}
