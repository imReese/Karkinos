import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  operationsNextActionLabel,
  type OperationsTodayResponse,
} from '../overview-feature-boundary';
import {
  numericPaperShadowValue,
  stringPaperShadowSnapshotValue,
} from './today-queue-paper-shadow';

export function executionReconciliationOverviewSummary(
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

export function operationsSchedulerEvidenceSummary(
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
  return [
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
  ]
    .filter(Boolean)
    .join(' · ');
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
