import {
  EvidenceState,
  GateMatrix,
  StatusBadge,
} from '../../app/components/workbench';
import type { Locale } from '../../app/preferences';
import { formatPublicStatus } from '../../shared/public-labels';
import type { ControlledPerOrderPilotReadiness } from './api';

type LocalizedLabel = { en: string; zh: string };

const PILOT_BLOCKER_LABELS: Record<string, LocalizedLabel> = {
  pilot_readiness_source_contract_blocked: {
    en: 'A persisted source contract is unsafe',
    zh: '持久化来源合同不满足安全边界',
  },
  readonly_adapter_release_missing: {
    en: 'A read-only adapter release has not been recorded',
    zh: '尚未记录只读适配器发布记录',
  },
  multiple_observing_readonly_adapter_releases: {
    en: 'More than one read-only adapter release is observing',
    zh: '存在多个处于观测状态的只读适配器发布记录',
  },
  readonly_adapter_release_not_accepted: {
    en: 'The read-only adapter release has not been accepted',
    zh: '只读适配器发布记录尚未接受',
  },
  readonly_adapter_conformance_not_clear: {
    en: 'Adapter conformance evidence is not clear',
    zh: '适配器一致性证据尚未清晰',
  },
  readonly_collector_observation_missing: {
    en: 'A persisted collector observation is missing',
    zh: '缺少已持久化的采集器观测',
  },
  readonly_adapter_release_boundary_invalid: {
    en: 'The adapter release crosses its read-only boundary',
    zh: '适配器发布记录越过只读边界',
  },
  readonly_adapter_scope_unresolved: {
    en: 'The read-only adapter scope is unresolved',
    zh: '只读适配器范围尚未确定',
  },
  matching_readonly_soak_promotion_missing: {
    en: 'A matching read-only soak promotion is missing',
    zh: '缺少匹配的只读稳定性观察准入记录',
  },
  multiple_matching_readonly_soak_promotions: {
    en: 'More than one matching soak promotion exists',
    zh: '存在多个匹配的稳定性观察准入记录',
  },
  readonly_soak_promotion_not_ready: {
    en: 'The read-only soak is not ready for promotion',
    zh: '只读稳定性观察尚未满足准入条件',
  },
  readonly_soak_account_truth_not_linked: {
    en: 'The soak is not linked to Account Truth reconciliation',
    zh: '稳定性观察尚未关联账户事实对账',
  },
  readonly_soak_owner_acceptance_missing: {
    en: 'Signed owner acceptance is missing',
    zh: '缺少账户所有者签署确认',
  },
  readonly_soak_operator_identity_unverified: {
    en: 'The accepting operator identity is unverified',
    zh: '接受证据中的操作员身份未经验证',
  },
  readonly_soak_acceptance_boundary_invalid: {
    en: 'The soak acceptance crosses its non-authorizing boundary',
    zh: '稳定性观察的接受证据越过非授权边界',
  },
  write_release_status_count_mismatch: {
    en: 'The write-release status count conflicts with persisted releases',
    zh: '写入放行状态计数与持久化记录不一致',
  },
  active_manual_each_order_write_release_missing: {
    en: 'An active manual-each-order write release is missing',
    zh: '缺少有效的逐单人工写入放行凭证',
  },
  multiple_active_write_releases: {
    en: 'More than one active write release exists',
    zh: '存在多个有效写入放行凭证',
  },
  write_release_schema_invalid: {
    en: 'The write-release schema is invalid',
    zh: '写入放行数据契约无效',
  },
  write_release_execution_mode_invalid: {
    en: 'The write release is not manual-each-order',
    zh: '写入放行不是逐单人工模式',
  },
  write_release_order_authority_boundary_invalid: {
    en: 'The write release improperly grants order authority',
    zh: '写入放行错误授予订单权限',
  },
  write_release_capital_authority_boundary_invalid: {
    en: 'The write release improperly grants capital authority',
    zh: '写入放行错误授予资本权限',
  },
  write_release_revoked: {
    en: 'The write release has been revoked',
    zh: '写入放行已撤销',
  },
  pilot_scope_evidence_incomplete: {
    en: 'Provider, account, gateway, or connector evidence is incomplete',
    zh: '接入方、账户、执行网关或连接器证据不完整',
  },
  controlled_operator_view_untrusted: {
    en: 'The controlled-execution operator view is not trusted',
    zh: '受控执行操作视图不可信',
  },
  controlled_order_attention_count_invalid: {
    en: 'The unresolved-order count is invalid',
    zh: '未闭合订单计数无效',
  },
  unresolved_controlled_order_journey_present: {
    en: 'An unresolved controlled-order journey remains',
    zh: '仍有未闭合的受控订单流程',
  },
  controlled_order_attention_queue_truncated: {
    en: 'The controlled-order attention scan is truncated',
    zh: '受控订单关注项扫描已截断',
  },
  current_runtime_session_count_invalid: {
    en: 'The active-session count is invalid',
    zh: '当前会话计数无效',
  },
  session_authority_active_during_per_order_pilot: {
    en: 'Session authority is active during a per-order pilot',
    zh: '逐单试点期间仍存在会话权限',
  },
  blocked_runtime_session_count_invalid: {
    en: 'The blocked-session count is invalid',
    zh: '阻断会话计数无效',
  },
  blocked_runtime_session_present: {
    en: 'A blocked runtime session remains unresolved',
    zh: '仍有未解决的阻断运行会话',
  },
  connector_observations_missing: {
    en: 'Persisted connector observations are missing',
    zh: '缺少已持久化的连接器观测',
  },
  latest_snapshot_not_healthy: {
    en: 'The latest connector snapshot is not healthy',
    zh: '最新连接器快照不健康',
  },
  signed_owner_acceptance_missing: {
    en: 'Signed owner acceptance has not been recorded',
    zh: '尚未记录账户所有者签署确认',
  },
  account_truth_evidence_not_clear: {
    en: 'Account Truth evidence is not clear',
    zh: '账户事实证据尚未清晰',
  },
  account_truth_not_fresh: {
    en: 'Account Truth evidence is stale',
    zh: '账户事实证据已过期',
  },
  account_truth_unresolved_mismatches: {
    en: 'Account Truth still has unresolved mismatches',
    zh: '账户事实仍有未解决差异',
  },
};

const PILOT_RESOLUTION_LABELS: Record<string, LocalizedLabel> = {
  restore_safe_persisted_only_source_contracts: {
    en: 'Restore every source to its persisted-only, non-authorizing contract',
    zh: '恢复所有来源的仅持久化、非授权合同',
  },
  accept_and_observe_one_exact_readonly_adapter_release: {
    en: 'Accept and observe one exact read-only adapter release',
    zh: '接受并观测一份精确的只读适配器发布记录',
  },
  complete_exact_scope_soak_and_record_owner_acceptance: {
    en: 'Complete the exact-scope soak and record signed owner acceptance',
    zh: '完成精确范围稳定性观察，并记录账户所有者签署确认',
  },
  issue_one_short_lived_exact_scope_write_release: {
    en: 'Issue one short-lived, exact-scope manual-each-order write release',
    zh: '签发一份短时效、精确范围的逐单人工写入放行凭证',
  },
  resolve_provider_account_gateway_connector_scope_drift: {
    en: 'Resolve provider, account, gateway, and connector scope drift',
    zh: '解决接入方、账户、执行网关与连接器的范围漂移',
  },
  close_controlled_journeys_and_remove_session_authority: {
    en: 'Close controlled journeys and remove all session authority',
    zh: '关闭受控流程并移除全部会话权限',
  },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readinessContractIsSafe(
  value: unknown,
): value is ControlledPerOrderPilotReadiness {
  if (!isRecord(value) || !isRecord(value.scope)) {
    return false;
  }
  const scope = value.scope;
  const gates = value.gates;
  if (!Array.isArray(gates)) {
    return false;
  }
  const gatesAreSafe = gates.every(
    (gate) =>
      isRecord(gate) &&
      typeof gate.key === 'string' &&
      (gate.status === 'pass' || gate.status === 'blocked') &&
      Array.isArray(gate.blockers) &&
      gate.blockers.every((item) => typeof item === 'string') &&
      Array.isArray(gate.evidence_refs) &&
      gate.evidence_refs.every((item) => typeof item === 'string') &&
      typeof gate.resolution_condition === 'string' &&
      gate.manual_acknowledgement_clears_status === false,
  );
  const scopeFields = [
    'provider',
    'gateway_id',
    'account_alias',
    'connector_id',
    'readonly_release_evidence_ref',
    'write_release_evidence_id',
  ];
  const requiredGateKeys = [
    'persisted_source_contracts',
    'one_observing_readonly_adapter_release',
    'signed_readonly_soak_promotion',
    'one_active_manual_each_order_write_release',
    'one_exact_provider_account_gateway_scope',
    'no_unresolved_order_or_session_authority',
  ];
  const gateKeys = gates
    .filter(isRecord)
    .map((gate) => gate.key)
    .filter((key): key is string => typeof key === 'string');
  return (
    value.schema_version ===
      'karkinos.controlled_per_order_pilot_readiness.v1' &&
    (value.status === 'ready_for_exact_order_review' ||
      value.status === 'blocked') &&
    typeof value.readiness_fingerprint === 'string' &&
    /^sha256:[a-f0-9]{64}$/.test(value.readiness_fingerprint) &&
    (value.observed_at === null || typeof value.observed_at === 'string') &&
    typeof value.gate_count === 'number' &&
    value.gate_count === gates.length &&
    typeof value.passed_gate_count === 'number' &&
    value.passed_gate_count ===
      gates.filter((gate) => isRecord(gate) && gate.status === 'pass').length &&
    typeof value.blocked_gate_count === 'number' &&
    value.blocked_gate_count ===
      gates.filter((gate) => isRecord(gate) && gate.status === 'blocked')
        .length &&
    gatesAreSafe &&
    gateKeys.length === requiredGateKeys.length &&
    new Set(gateKeys).size === requiredGateKeys.length &&
    requiredGateKeys.every((key) => gateKeys.includes(key)) &&
    scopeFields.every((field) => typeof scope[field] === 'string') &&
    Array.isArray(value.required_next_order_gates) &&
    value.required_next_order_gates.every((item) => typeof item === 'string') &&
    Array.isArray(value.blockers) &&
    value.blockers.every((item) => typeof item === 'string') &&
    typeof value.next_safe_action === 'string' &&
    value.release_scope ===
      'pilot_admission_prerequisites_not_v1_8_completion' &&
    value.persisted_facts_only === true &&
    value.read_only_projection === true &&
    value.provider_contacted === false &&
    value.database_writes_performed === false &&
    value.broker_submission_enabled === false &&
    value.broker_cancellation_enabled === false &&
    value.does_not_mutate_oms === true &&
    value.does_not_mutate_production_ledger === true &&
    value.does_not_mutate_risk_state === true &&
    value.does_not_mutate_kill_switch === true &&
    value.does_not_mutate_capital_authority === true &&
    value.authorizes_execution === false &&
    value.automatic_scale_up_enabled === false &&
    Array.isArray(value.limitations) &&
    value.limitations.every((item) => typeof item === 'string')
  );
}

function gateLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    persisted_source_contracts: {
      en: 'Persisted source contracts',
      zh: '持久化来源合同',
    },
    one_observing_readonly_adapter_release: {
      en: 'One read-only adapter release',
      zh: '单一只读适配器发布记录',
    },
    signed_readonly_soak_promotion: {
      en: 'Signed read-only soak',
      zh: '已签署只读稳定性观察',
    },
    one_active_manual_each_order_write_release: {
      en: 'One manual-each-order write release',
      zh: '单一逐单写入放行',
    },
    one_exact_provider_account_gateway_scope: {
      en: 'Exact provider and account scope',
      zh: '精确接入方与账户范围',
    },
    no_unresolved_order_or_session_authority: {
      en: 'No unresolved order or session authority',
      zh: '无未闭合订单或会话权限',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function actionLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    review_pilot_readiness_source_contracts: {
      en: 'Repair and review the persisted source contracts',
      zh: '修复并复核持久化来源合同',
    },
    owner_select_and_review_real_broker_provider: {
      en: 'Owner selects and reviews one real broker provider',
      zh: '由账户所有者选择并复核一家真实券商接入方',
    },
    complete_readonly_soak_and_signed_acceptance: {
      en: 'Complete the read-only soak and signed owner acceptance',
      zh: '完成只读稳定性观察与账户所有者签署确认',
    },
    issue_short_lived_manual_each_order_write_release: {
      en: 'Issue one short-lived manual-each-order write release',
      zh: '签发一份短时效逐单写入放行凭证',
    },
    resolve_pilot_scope_drift: {
      en: 'Resolve provider, account, gateway, or connector scope drift',
      zh: '处理接入方、账户、执行网关或连接器范围漂移',
    },
    close_controlled_execution_attention: {
      en: 'Close unresolved controlled journeys and session authority',
      zh: '关闭未解决的受控流程与会话权限',
    },
    open_exact_order_review_without_submission: {
      en: 'Open a separate exact-order review; do not submit',
      zh: '打开独立的精确订单复核；不得提交',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function evidenceCodeFallback(value: string, locale: Locale) {
  const readable = value
    .replace(/:/g, ' · ')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (locale === 'zh') {
    return `证据代码：${value}`;
  }
  return `Evidence code: ${readable}`;
}

function blockerLabel(value: string, locale: Locale) {
  const exact = PILOT_BLOCKER_LABELS[value];
  if (exact) {
    return exact[locale];
  }
  if (value.startsWith('pilot_scope_mismatch:')) {
    const field = value.slice('pilot_scope_mismatch:'.length);
    const fields: Record<string, LocalizedLabel> = {
      provider: { en: 'provider', zh: '接入方' },
      gateway_id: { en: 'gateway', zh: '执行网关' },
      account_alias: { en: 'account', zh: '账户' },
      readonly_release: {
        en: 'read-only release',
        zh: '只读发布记录',
      },
      connector: { en: 'connector', zh: '连接器' },
      soak_account: { en: 'soak account', zh: '稳定性观察账户' },
      soak_acceptance: {
        en: 'soak acceptance',
        zh: '稳定性观察接受证据',
      },
    };
    const label = fields[field]?.[locale] ?? field;
    return locale === 'zh'
      ? `${label} 与试点范围不一致`
      : `${label} does not match the pilot scope`;
  }
  const sourceFailure = value.match(
    /^(adapter|soak|write_release|operator_view)_(schema_invalid|source_failed)$/,
  );
  if (sourceFailure) {
    const sourceLabels: Record<string, LocalizedLabel> = {
      adapter: { en: 'adapter', zh: '适配器' },
      soak: { en: 'soak', zh: '稳定性观察' },
      write_release: { en: 'write release', zh: '写入放行' },
      operator_view: { en: 'operator view', zh: '操作视图' },
    };
    const source =
      sourceLabels[sourceFailure[1]]?.[locale] ??
      sourceFailure[1].replace(/_/g, ' ');
    const failed = sourceFailure[2] === 'source_failed';
    return locale === 'zh'
      ? `${source}${failed ? '来源读取失败' : '数据契约无效'}`
      : `${source} ${failed ? 'source read failed' : 'schema is invalid'}`;
  }
  const boundary = value.match(
    /^(adapter|soak|soak_safety|write_status|operator_view)_(.+)_boundary_invalid$/,
  );
  if (boundary) {
    const sourceLabels: Record<string, LocalizedLabel> = {
      adapter: { en: 'adapter', zh: '适配器' },
      soak: { en: 'soak', zh: '稳定性观察' },
      soak_safety: { en: 'soak safety', zh: '稳定性观察安全项' },
      write_status: { en: 'write status', zh: '写入状态' },
      operator_view: { en: 'operator view', zh: '操作视图' },
    };
    const source =
      sourceLabels[boundary[1]]?.[locale] ?? boundary[1].replace(/_/g, ' ');
    const field = boundary[2].replace(/_/g, ' ');
    return locale === 'zh'
      ? `${source}的 ${field} 安全边界无效`
      : `${source} ${field} safety boundary is invalid`;
  }
  const incompleteDays = value.match(
    /^clear_reconciled_soak_days_incomplete:(\d+)\/(\d+)$/,
  );
  if (incompleteDays) {
    return locale === 'zh'
      ? `清晰且已对账的稳定性观察日不足（${incompleteDays[1]}/${incompleteDays[2]}）`
      : `Clear reconciled soak days are incomplete (${incompleteDays[1]}/${incompleteDays[2]})`;
  }
  const recoveryDrill = value.match(/^recovery_drill_missing:(.+)$/);
  if (recoveryDrill) {
    return locale === 'zh'
      ? `缺少 ${recoveryDrill[1]} 恢复演练`
      : `${recoveryDrill[1]} recovery drill is missing`;
  }
  return evidenceCodeFallback(value, locale);
}

function resolutionLabel(value: string, locale: Locale) {
  return (
    PILOT_RESOLUTION_LABELS[value]?.[locale] ??
    evidenceCodeFallback(value, locale)
  );
}

export function ControlledPerOrderPilotReadinessPanel({
  readiness,
  locale,
}: {
  readiness: ControlledPerOrderPilotReadiness | undefined;
  locale: Locale;
}) {
  if (!readiness) {
    return null;
  }
  const safe = readinessContractIsSafe(readiness);
  const ready = safe && readiness.status === 'ready_for_exact_order_review';
  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid="controlled-pilot-readiness"
      open={safe ? undefined : true}
    >
      <summary className="app-pilot-readiness-summary flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 py-2.5 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--app-focus-ring)] sm:gap-4">
        <span className="min-w-0 break-words">
          {locale === 'zh'
            ? '受控逐单试点准入证据'
            : 'Controlled per-order pilot admission evidence'}
        </span>
        <span className="flex min-w-0 max-w-28 shrink items-center justify-end gap-2 sm:max-w-none">
          <StatusBadge
            className="min-w-0 max-w-full text-right whitespace-normal"
            tone={!safe ? 'danger' : ready ? 'success' : 'neutral'}
          >
            {!safe
              ? locale === 'zh'
                ? '合同阻断'
                : 'Contract blocked'
              : ready
                ? locale === 'zh'
                  ? '可进入复核'
                  : 'Ready for review'
                : locale === 'zh'
                  ? '条件未满足'
                  : 'Prerequisites unmet'}
          </StatusBadge>
          <span
            aria-hidden="true"
            className="app-disclosure-chevron inline-flex h-5 w-5 shrink-0 items-center justify-center text-[var(--app-text-tertiary)] group-open:rotate-180"
          >
            ▾
          </span>
        </span>
      </summary>
      <div className="min-w-0 space-y-4 pb-4 pt-2">
        {!safe ? (
          <EvidenceState
            kind="error"
            title={
              locale === 'zh'
                ? '试点准入合同已阻断'
                : 'Pilot admission contract blocked'
            }
            description={
              locale === 'zh'
                ? '来源违反只读或非授权合同；不得据此进入逐单复核。'
                : 'The source violates the read-only or non-authorizing contract; do not enter exact-order review.'
            }
          />
        ) : (
          <>
            <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
              {locale === 'zh'
                ? '这是可选真实试点的准入前置证据，不是 v1.8 发布完成证明，也不授予订单、券商或资本权限。'
                : 'These are admission prerequisites for an optional real pilot, not proof of v1.8 completion and not order, broker, or capital authority.'}
            </p>
            <GateMatrix
              caption={
                locale === 'zh'
                  ? '受控逐单试点准入门禁'
                  : 'Controlled per-order pilot admission gates'
              }
              labels={{
                gate: locale === 'zh' ? '门禁' : 'Gate',
                state: locale === 'zh' ? '状态' : 'State',
                reason:
                  locale === 'zh' ? '阻断原因 / 结论' : 'Blocker / conclusion',
                evidence:
                  locale === 'zh' ? '证据 / 解除条件' : 'Evidence / unblock',
              }}
              items={readiness.gates.map((gate) => ({
                id: gate.key,
                gate: gateLabel(gate.key, locale),
                state: gate.status === 'pass' ? 'pass' : 'block',
                stateLabel: formatPublicStatus(gate.status, locale),
                reason:
                  gate.blockers.length > 0
                    ? gate.blockers
                        .map((item) => blockerLabel(item, locale))
                        .join(' · ')
                    : locale === 'zh'
                      ? '持久化证据满足当前门禁'
                      : 'Persisted evidence satisfies this gate',
                evidence:
                  gate.evidence_refs.length > 0 ? (
                    <details
                      className="group/evidence min-w-0"
                      data-testid={`pilot-gate-evidence-${gate.key}`}
                    >
                      <summary className="cursor-pointer list-none font-medium text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                        {locale === 'zh'
                          ? `${gate.evidence_refs.length} 条已持久化证据`
                          : `${gate.evidence_refs.length} persisted evidence ${gate.evidence_refs.length === 1 ? 'reference' : 'references'}`}
                        <span
                          aria-hidden="true"
                          className="app-disclosure-chevron ml-1 inline-block text-[var(--app-text-tertiary)] group-open/evidence:rotate-180"
                        >
                          ▾
                        </span>
                      </summary>
                      <div className="mt-1 space-y-1">
                        {gate.evidence_refs.map((reference) => (
                          <code
                            key={reference}
                            className="app-type-micro block break-all text-[var(--app-text-tertiary)]"
                          >
                            {reference}
                          </code>
                        ))}
                      </div>
                    </details>
                  ) : locale === 'zh' ? (
                    '尚无匹配证据标识'
                  ) : (
                    'No matching evidence identity'
                  ),
                unblockCondition:
                  gate.status === 'blocked'
                    ? resolutionLabel(gate.resolution_condition, locale)
                    : undefined,
              }))}
            />
            <dl className="grid gap-3 text-xs sm:grid-cols-2">
              <div>
                <dt className="font-medium text-[var(--app-text-tertiary)]">
                  {locale === 'zh' ? '下一安全步骤' : 'Next safe step'}
                </dt>
                <dd className="mt-1 text-[var(--app-text)]">
                  {actionLabel(readiness.next_safe_action, locale)}
                </dd>
              </div>
              <div>
                <dt className="sr-only">
                  {locale === 'zh'
                    ? '技术证据身份'
                    : 'Technical evidence identity'}
                </dt>
                <dd>
                  <details
                    className="group/identity min-w-0 border-y border-[var(--app-divider)] py-1.5"
                    data-testid="pilot-readiness-identity"
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-2 font-medium text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                      <span>
                        {locale === 'zh'
                          ? '技术证据身份'
                          : 'Technical evidence identity'}
                      </span>
                      <span
                        aria-hidden="true"
                        className="app-disclosure-chevron text-[var(--app-text-tertiary)] group-open/identity:rotate-180"
                      >
                        ▾
                      </span>
                    </summary>
                    <code className="app-type-micro mt-1.5 block break-all font-mono text-[var(--app-text-tertiary)]">
                      {readiness.readiness_fingerprint}
                    </code>
                  </details>
                </dd>
              </div>
            </dl>
            <p className="text-xs leading-5 text-[var(--app-text-secondary)]">
              {locale === 'zh'
                ? '即使所有行通过，每一笔订单仍须重新通过账户事实、决策门禁、风控、模拟与影子检验、资本权限、执行网关、生命周期、对账、入账与短时效人工签名。'
                : 'Even when every row passes, each order must separately re-pass Account Truth, Decision, risk, paper/shadow, capital, gateway, lifecycle, reconciliation, posting, and short-lived human-signature gates.'}
            </p>
          </>
        )}
      </div>
    </details>
  );
}
