import type {
  OperationsAttentionItem,
  OperationsStatus,
  OperationsTodayResponse,
} from '../api';
import type { Locale } from '../../../shared/preferences/context';
import type { ExceptionItem, StatusTone } from '../../../shared/ui/workbench';

export function formatEvidenceTime(
  value: string | null | undefined,
  locale: Locale,
) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(parsed);
}

export function statusTone(status: OperationsStatus) {
  if (status === 'blocked') {
    return 'danger' as const;
  }
  if (status === 'degraded' || status === 'manual_action_required') {
    return 'warning' as const;
  }
  if (status === 'pass' || status === 'healthy' || status === 'no_action') {
    return 'success' as const;
  }
  return 'neutral' as const;
}

export function exceptionTone(
  status: OperationsStatus,
): ExceptionItem['severity'] {
  const tone: StatusTone = statusTone(status);
  return tone === 'success' ? 'neutral' : tone;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function attentionContractIsSafe(
  item: unknown,
): item is OperationsAttentionItem {
  if (!isRecord(item) || !isRecord(item.evidence)) {
    return false;
  }
  return (
    item.schema_version === 'karkinos.operations_attention_item.v1' &&
    typeof item.subsystem_id === 'string' &&
    typeof item.status === 'string' &&
    typeof item.target === 'string' &&
    typeof item.next_action === 'string' &&
    typeof item.resolution_condition === 'string' &&
    typeof item.task_fingerprint === 'string' &&
    item.task_fingerprint.startsWith('sha256:') &&
    typeof item.evidence.status === 'string' &&
    (item.evidence.observed_at === null ||
      typeof item.evidence.observed_at === 'string') &&
    item.manual_acknowledgement_clears_status === false &&
    item.read_only_projection === true &&
    item.provider_contacted === false &&
    item.database_writes_performed === false &&
    item.authorizes_execution === false
  );
}

function subsystemContractIsSafe(value: unknown) {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === 'string' &&
    typeof value.status === 'string' &&
    typeof value.target === 'string' &&
    typeof value.next_action === 'string' &&
    typeof value.detail_status === 'string' &&
    (value.last_run_at === null || typeof value.last_run_at === 'string') &&
    Array.isArray(value.limitations) &&
    value.limitations.every((item) => typeof item === 'string')
  );
}

function citicSourceFollowUpContractIsSafe(value: unknown) {
  if (!isRecord(value)) {
    return false;
  }
  return (
    value.schema_version ===
      'karkinos.account_truth.citic_source_follow_up.v1' &&
    typeof value.status === 'string' &&
    typeof value.subsystem_status === 'string' &&
    typeof value.pending_source_count === 'number' &&
    Number.isFinite(value.pending_source_count) &&
    typeof value.scanned_source_count === 'number' &&
    Number.isFinite(value.scanned_source_count) &&
    value.scanned_source_count >= value.pending_source_count &&
    typeof value.intake_scan_truncated === 'boolean' &&
    typeof value.count_complete === 'boolean' &&
    !(value.intake_scan_truncated && value.count_complete) &&
    Array.isArray(value.blockers) &&
    value.blockers.every((item) => typeof item === 'string') &&
    Array.isArray(value.required_evidence) &&
    value.required_evidence.every((item) => typeof item === 'string') &&
    typeof value.reviewed_query_window_source_count === 'number' &&
    Number.isFinite(value.reviewed_query_window_source_count) &&
    typeof value.unreviewed_query_window_source_count === 'number' &&
    Number.isFinite(value.unreviewed_query_window_source_count) &&
    typeof value.query_window_reviews_complete === 'boolean' &&
    ['not_available', 'partial', 'clear', 'blocked'].includes(
      String(value.query_window_batch_integrity_status),
    ) &&
    typeof value.query_window_batch_assessment_fingerprint === 'string' &&
    value.query_window_batch_assessment_fingerprint.startsWith('sha256:') &&
    typeof value.query_window_gap_calendar_day_count === 'number' &&
    Number.isFinite(value.query_window_gap_calendar_day_count) &&
    value.query_window_gap_calendar_day_count >= 0 &&
    typeof value.query_window_overlap_calendar_day_count === 'number' &&
    Number.isFinite(value.query_window_overlap_calendar_day_count) &&
    value.query_window_overlap_calendar_day_count >= 0 &&
    typeof value.query_window_integrity_clear === 'boolean' &&
    value.query_window_integrity_clear ===
      (value.query_window_batch_integrity_status === 'clear') &&
    (!value.query_window_integrity_clear ||
      (value.query_window_reviews_complete &&
        value.query_window_gap_calendar_day_count === 0 &&
        value.query_window_overlap_calendar_day_count === 0)) &&
    Array.isArray(value.error_codes) &&
    value.error_codes.every((item) => typeof item === 'string') &&
    (value.latest_reviewed_at === null ||
      typeof value.latest_reviewed_at === 'string') &&
    typeof value.evidence_fingerprint === 'string' &&
    value.evidence_fingerprint.startsWith('sha256:') &&
    typeof value.next_manual_action === 'string' &&
    Array.isArray(value.limitations) &&
    value.limitations.every((item) => typeof item === 'string') &&
    value.persisted_facts_only === true &&
    value.source_paths_included === false &&
    value.source_names_included === false &&
    value.transaction_details_included === false &&
    value.provider_contacted === false &&
    value.database_writes_performed === false &&
    value.eligible_for_account_truth === false &&
    value.eligible_for_reconciliation === false &&
    value.authorizes_execution === false &&
    value.changes_capital_authority === false
  );
}

export function operationsProjectionIsSafe(
  value: unknown,
): value is OperationsTodayResponse {
  if (!isRecord(value) || !isRecord(value.health)) {
    return false;
  }
  const health = value.health;
  const attentionItems = value.attention_items ?? [];
  const citicSourceFollowUp = value.citic_source_follow_up;
  return (
    value.schema_version === 'karkinos.operations_today.v1' &&
    typeof value.generated_at === 'string' &&
    typeof value.conclusion_status === 'string' &&
    [
      'total',
      'pass',
      'degraded',
      'blocked',
      'manual_action_required',
      'skipped',
    ].every(
      (key) => typeof health[key] === 'number' && Number.isFinite(health[key]),
    ) &&
    Array.isArray(value.subsystems) &&
    value.subsystems.every(subsystemContractIsSafe) &&
    Array.isArray(attentionItems) &&
    attentionItems.every(attentionContractIsSafe) &&
    (citicSourceFollowUp === undefined ||
      citicSourceFollowUpContractIsSafe(citicSourceFollowUp))
  );
}
