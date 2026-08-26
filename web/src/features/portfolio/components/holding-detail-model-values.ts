import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicEvidenceReference } from '../../../shared/public-labels';
import type { AttributionReadinessItem } from '../portfolio-feature-boundary';

export type DetailMetric = {
  detail?: string;
  label: string;
  value: string;
  tone?: 'pnl-positive' | 'pnl-negative' | 'warning';
};

export type HoldingDetailTab =
  'position' | 'pnl-costs' | 'transactions' | 'evidence' | 'reconciliation';

export const HOLDING_DETAIL_TABS: HoldingDetailTab[] = [
  'position',
  'pnl-costs',
  'transactions',
  'evidence',
  'reconciliation',
];

type EvidenceRefType =
  'signal' | 'action' | 'risk' | 'review' | 'order' | 'fill' | 'unknown';

export type EvidenceRefItem = {
  kind: EvidenceRefType;
  label: string;
  auditRef: string;
};

export type AttributionNextAction = {
  detail: string;
  href: string;
  label: string;
};

const EVIDENCE_REF_TYPES = new Set<EvidenceRefType>([
  'signal',
  'action',
  'risk',
  'review',
  'order',
  'fill',
]);

export function normalizeSymbol(symbol: string) {
  return symbol.trim().toLowerCase();
}

export function safeDecodeSymbol(symbol: string) {
  try {
    return decodeURIComponent(symbol);
  } catch {
    return symbol;
  }
}

export function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(0, Math.round(seconds))}s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours}h`;
  }
  return `${Math.round(hours / 24)}d`;
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function sameEvidenceIdentity(
  snapshotId: string | null | undefined,
  ledgerCutoffId: number | undefined,
  comparisonSnapshotId: string | null | undefined,
  comparisonLedgerCutoffId: number | undefined,
) {
  return (
    Boolean(snapshotId) &&
    Boolean(comparisonSnapshotId) &&
    Number.isInteger(ledgerCutoffId) &&
    Number.isInteger(comparisonLedgerCutoffId) &&
    snapshotId === comparisonSnapshotId &&
    ledgerCutoffId === comparisonLedgerCutoffId
  );
}

export function buildBacktestHandoffHref(symbol: string, assetClass: string) {
  const params = new URLSearchParams();
  params.set('symbol', symbol);
  params.set('assetClass', assetClass);
  params.set('source', 'portfolio');
  return `/backtest?${params.toString()}`;
}

export function buildEvidenceRefItems(
  refs: string[],
  labels: Record<EvidenceRefType, string>,
  locale: Locale,
) {
  return refs.map((ref): EvidenceRefItem => {
    const [rawKind, ...auditParts] = ref.split(':');
    const kind = EVIDENCE_REF_TYPES.has(rawKind as EvidenceRefType)
      ? (rawKind as EvidenceRefType)
      : 'unknown';
    const publicReference = formatPublicEvidenceReference(ref, locale);
    const [publicLabel, publicAuditRef] = publicReference.split(' · ');
    const auditRef =
      kind === 'unknown'
        ? publicAuditRef || publicReference
        : auditParts.join(':') || ref;
    return {
      kind,
      label:
        kind === 'unknown'
          ? publicLabel || labels.unknown
          : (labels[kind] ?? labels.unknown),
      auditRef,
    };
  });
}

export function buildAttributionNextAction({
  missingItem,
  symbol,
  assetClass,
  labels,
  shouldStartResearchReview = false,
}: {
  missingItem: AttributionReadinessItem | null;
  symbol: string;
  assetClass: string;
  labels: ReturnType<typeof useCopy>['portfolio']['detail'];
  shouldStartResearchReview?: boolean;
}): AttributionNextAction | null {
  if (!missingItem) {
    return shouldStartResearchReview
      ? {
          detail: labels.strategyAttributionNextActionResearch,
          href: buildBacktestHandoffHref(symbol, assetClass),
          label: labels.actionStrategyEvidence,
        }
      : null;
  }
  if (
    missingItem.key === 'strategy_signal' ||
    missingItem.key === 'candidate_action' ||
    missingItem.key === 'risk_gate'
  ) {
    return {
      detail: labels.strategyAttributionNextActionResearch,
      href: buildBacktestHandoffHref(symbol, assetClass),
      label: labels.actionStrategyEvidence,
    };
  }
  if (missingItem.key === 'manual_review') {
    return {
      detail: labels.strategyAttributionNextActionManualReview,
      href: '/decision',
      label: labels.strategyAttributionOpenDecisionReview,
    };
  }
  if (
    missingItem.key === 'order_evidence' ||
    missingItem.key === 'fill_evidence'
  ) {
    return {
      detail: labels.strategyAttributionNextActionExecution,
      href: '/trading',
      label: labels.strategyAttributionOpenExecutionReview,
    };
  }
  return {
    detail: labels.strategyAttributionNextActionGeneric,
    href: buildBacktestHandoffHref(symbol, assetClass),
    label: labels.actionStrategyEvidence,
  };
}

export function nextHoldingDetailTab(
  currentTab: HoldingDetailTab,
  key: string,
): HoldingDetailTab | null {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(key)) {
    return null;
  }
  const currentIndex = HOLDING_DETAIL_TABS.indexOf(currentTab);
  const nextIndex =
    key === 'Home'
      ? 0
      : key === 'End'
        ? HOLDING_DETAIL_TABS.length - 1
        : key === 'ArrowRight'
          ? (currentIndex + 1) % HOLDING_DETAIL_TABS.length
          : (currentIndex - 1 + HOLDING_DETAIL_TABS.length) %
            HOLDING_DETAIL_TABS.length;
  return HOLDING_DETAIL_TABS[nextIndex];
}
