import type {
  BrokerAdapterReadinessRelease,
  BrokerConnectorSoakPromotionStatus,
  ControlledBrokerWriteReleaseOwnerReviewRefs,
  ControlledBrokerWriteReleaseRevocationReason,
} from '../api';

export type Locale = 'en' | 'zh';
export type OwnerReviewRefField =
  keyof ControlledBrokerWriteReleaseOwnerReviewRefs;

export type TrustedSignerIdentity = {
  operator_id: string;
  key_id: string;
  public_key_fingerprint: string;
};

export const OWNER_REVIEW_FIELDS: OwnerReviewRefField[] = [
  'broker_agreement_review',
  'account_permissions_review',
  'program_trading_reporting_review',
  'provider_acceptance_test_report',
  'deployment_authorization',
  'risk_controls_review',
  'rollback_drill_review',
];

export const EMPTY_OWNER_REFS: ControlledBrokerWriteReleaseOwnerReviewRefs = {
  broker_agreement_review: '',
  account_permissions_review: '',
  program_trading_reporting_review: '',
  provider_acceptance_test_report: '',
  deployment_authorization: '',
  risk_controls_review: '',
  rollback_drill_review: '',
};

export const REVOCATION_REASONS: ControlledBrokerWriteReleaseRevocationReason[] =
  [
    'incident_or_anomaly',
    'owner_disabled',
    'adapter_or_deployment_changed',
    'provider_scope_changed',
    'regulatory_or_permission_change',
    'scheduled_expiry_superseded',
  ];

const SENSITIVE_MANIFEST_KEY_PARTS = [
  'password',
  'passwd',
  'secret',
  'token',
  'credential',
  'private_key',
  'api_key',
];

export function mutationError(error: unknown) {
  return error instanceof Error
    ? error.message
    : String(error || 'unknown_error');
}

export function shortenedIdentity(value: string) {
  if (value.length <= 24) {
    return value || '—';
  }
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

export function containsSensitiveManifestKey(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some(containsSensitiveManifestKey);
  }
  if (!value || typeof value !== 'object') {
    return false;
  }
  return Object.entries(value).some(
    ([key, item]) =>
      SENSITIVE_MANIFEST_KEY_PARTS.some((part) =>
        key.toLowerCase().includes(part),
      ) || containsSensitiveManifestKey(item),
  );
}

export function ownerReviewLabel(field: OwnerReviewRefField, locale: Locale) {
  const labels: Record<OwnerReviewRefField, { en: string; zh: string }> = {
    broker_agreement_review: {
      en: 'Broker agreement review',
      zh: '券商协议复核',
    },
    account_permissions_review: {
      en: 'Account permissions review',
      zh: '账户权限复核',
    },
    program_trading_reporting_review: {
      en: 'Program-trading reporting review',
      zh: '程序化交易报告复核',
    },
    provider_acceptance_test_report: {
      en: 'Provider acceptance-test report',
      zh: 'Provider 验收测试报告',
    },
    deployment_authorization: {
      en: 'Deployment authorization',
      zh: '部署授权',
    },
    risk_controls_review: {
      en: 'Risk-controls review',
      zh: '风控复核',
    },
    rollback_drill_review: {
      en: 'Rollback-drill review',
      zh: '回滚演练复核',
    },
  };
  return labels[field][locale];
}

export function revocationReasonLabel(
  reason: ControlledBrokerWriteReleaseRevocationReason,
  locale: Locale,
) {
  const labels: Record<
    ControlledBrokerWriteReleaseRevocationReason,
    { en: string; zh: string }
  > = {
    adapter_or_deployment_changed: {
      en: 'Adapter or deployment changed',
      zh: 'Adapter 或部署已变化',
    },
    incident_or_anomaly: {
      en: 'Incident or anomaly',
      zh: '事故或异常',
    },
    owner_disabled: { en: 'Owner disabled', zh: '所有者主动关闭' },
    provider_scope_changed: {
      en: 'Provider scope changed',
      zh: 'Provider scope 已变化',
    },
    regulatory_or_permission_change: {
      en: 'Regulatory or permission change',
      zh: '监管或权限变化',
    },
    scheduled_expiry_superseded: {
      en: 'Superseded before scheduled expiry',
      zh: '计划到期前被替代',
    },
  };
  return labels[reason][locale];
}

export function exactSoakAcceptance(
  soak: BrokerConnectorSoakPromotionStatus | null,
  release: BrokerAdapterReadinessRelease | null,
) {
  if (!soak || !release) {
    return null;
  }
  return (
    soak.connectors.find(
      (connector) =>
        connector.connector_id === release.collector_id &&
        connector.account_alias === release.account_alias &&
        connector.promotion_ready &&
        connector.owner_acceptance_recorded &&
        Boolean(connector.acceptance?.acceptance_id),
    ) ?? null
  );
}
