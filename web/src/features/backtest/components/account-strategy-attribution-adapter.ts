import { useCopy } from '../../../shared/i18n/context';
import type { HoldingStrategyAttributionReport } from '../backtest-feature-boundary';
import {
  buildAttributionReadinessItems,
  type AttributionReadinessItem,
} from '../backtest-feature-boundary';
import type { BacktestAttributionPreviewResponse } from '../api';

type BacktestAttributionNextAction = {
  detail: string;
  href: string;
  label: string;
};

type BacktestAttributionEvidenceChainItem = {
  key: string;
  label: string;
  present: boolean;
};

export function buildHoldingAttributionReviewHref(symbol: string) {
  return `/portfolio/${encodeURIComponent(
    symbol,
  )}#holding-strategy-attribution-boundary`;
}

export function buildBacktestHoldingAttributionNextAction({
  missingItem,
  labels,
  holdingLabels,
}: {
  missingItem: AttributionReadinessItem | null;
  labels: ReturnType<typeof useCopy>['backtest']['page'];
  holdingLabels: ReturnType<typeof useCopy>['portfolio']['detail'];
}): BacktestAttributionNextAction | null {
  if (!missingItem) {
    return null;
  }
  if (
    missingItem.key === 'strategy_signal' ||
    missingItem.key === 'candidate_action' ||
    missingItem.key === 'risk_gate'
  ) {
    return {
      detail: holdingLabels.strategyAttributionNextActionResearch,
      href: '#backtest-signal-review-evidence',
      label: labels.singleInstrumentLoopSignalEvidence,
    };
  }
  if (missingItem.key === 'manual_review') {
    return {
      detail: holdingLabels.strategyAttributionNextActionManualReview,
      href: '/decision',
      label: holdingLabels.strategyAttributionOpenDecisionReview,
    };
  }
  if (
    missingItem.key === 'order_evidence' ||
    missingItem.key === 'fill_evidence'
  ) {
    return {
      detail: holdingLabels.strategyAttributionNextActionExecution,
      href: '/trading',
      label: holdingLabels.strategyAttributionOpenExecutionReview,
    };
  }
  return {
    detail: holdingLabels.strategyAttributionNextActionGeneric,
    href: '#backtest-signal-review-evidence',
    label: labels.singleInstrumentLoopAttributionEvidence,
  };
}

function hasAttributionEvidenceRef(
  result: BacktestAttributionPreviewResponse,
  prefix: string,
) {
  return result.evidence_refs.some((ref) => ref.startsWith(`${prefix}:`));
}

export function buildBacktestAttributionEvidenceChainItems(
  result: BacktestAttributionPreviewResponse,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
): BacktestAttributionEvidenceChainItem[] {
  return [
    {
      key: 'signal_preview',
      label: labels.signalPreviewEvidenceChainSignal,
      present:
        result.evidence_counts.signal_preview > 0 &&
        hasAttributionEvidenceRef(result, 'signal_preview'),
    },
    {
      key: 'dataset_snapshot',
      label: labels.signalPreviewEvidenceChainDataset,
      present: hasAttributionEvidenceRef(result, 'dataset_snapshot'),
    },
    {
      key: 'risk_preview',
      label: labels.signalPreviewEvidenceChainRisk,
      present:
        result.evidence_counts.risk_preview > 0 &&
        hasAttributionEvidenceRef(result, 'risk_preview'),
    },
    {
      key: 'paper_shadow_order',
      label: labels.signalPreviewEvidenceChainPaperOrder,
      present:
        result.evidence_counts.paper_shadow_order > 0 &&
        hasAttributionEvidenceRef(result, 'paper_shadow_order'),
    },
    {
      key: 'paper_shadow_fill',
      label: labels.signalPreviewEvidenceChainPaperFill,
      present:
        result.evidence_counts.paper_shadow_fill > 0 &&
        hasAttributionEvidenceRef(result, 'paper_shadow_fill'),
    },
  ];
}

export function buildBacktestHoldingAttributionReadinessItems(
  report: HoldingStrategyAttributionReport,
  holdingLabels: ReturnType<typeof useCopy>['portfolio']['detail'],
) {
  return buildAttributionReadinessItems(
    {
      signal_count: report.signal_count,
      action_count: report.action_count,
      review_count: report.evidence_refs.filter((ref) =>
        ref.startsWith('review:'),
      ).length,
      risk_decision_count: report.risk_decision_count,
      order_count: report.order_count,
      fill_count: report.fill_count,
      review_prerequisites: report.review_prerequisites,
    },
    holdingLabels.strategyAttributionReadinessItems,
  );
}
