export type AttributionReviewPrerequisiteLike = {
  key: string;
  passed: boolean;
  evidence_count: number;
};

export type AttributionReviewPrerequisiteKey =
  | 'strategy_signal'
  | 'candidate_action'
  | 'risk_gate'
  | 'manual_review'
  | 'order_evidence'
  | 'fill_evidence';

export type AttributionReadinessLabels = {
  signalLinked: string;
  signalMissing: string;
  actionLinked: string;
  actionMissing: string;
  reviewLinked: string;
  reviewMissing: string;
  riskLinked: string;
  riskMissing: string;
  orderLinked: string;
  orderMissing: string;
  fillLinked: string;
  fillMissing: string;
  unknownLinked: string;
  unknownMissing: string;
};

export type AttributionReadinessItem = {
  key: string;
  passed: boolean;
  label: string;
};

export function buildAttributionReadinessItems(
  report: {
    signal_count: number;
    action_count?: number;
    review_count?: number;
    risk_decision_count: number;
    order_count: number;
    fill_count: number;
    review_prerequisites?: AttributionReviewPrerequisiteLike[];
  },
  labels: AttributionReadinessLabels,
): AttributionReadinessItem[] {
  const structuredPrerequisites = report.review_prerequisites ?? [];
  if (structuredPrerequisites.length > 0) {
    return structuredPrerequisites.map((prerequisite) => ({
      key: prerequisite.key,
      passed: prerequisite.passed,
      label: formatAttributionPrerequisiteLabel(prerequisite, labels),
    }));
  }

  const actionCount = report.action_count ?? 0;
  const reviewCount = report.review_count ?? report.signal_count;
  return [
    {
      key: 'strategy_signal',
      passed: report.signal_count > 0,
      label:
        report.signal_count > 0 ? labels.signalLinked : labels.signalMissing,
    },
    {
      key: 'candidate_action',
      passed: actionCount > 0,
      label: actionCount > 0 ? labels.actionLinked : labels.actionMissing,
    },
    {
      key: 'manual_review',
      passed: reviewCount > 0,
      label: reviewCount > 0 ? labels.reviewLinked : labels.reviewMissing,
    },
    {
      key: 'risk_gate',
      passed: report.risk_decision_count > 0,
      label:
        report.risk_decision_count > 0 ? labels.riskLinked : labels.riskMissing,
    },
    {
      key: 'order_evidence',
      passed: report.order_count > 0,
      label: report.order_count > 0 ? labels.orderLinked : labels.orderMissing,
    },
    {
      key: 'fill_evidence',
      passed: report.fill_count > 0,
      label: report.fill_count > 0 ? labels.fillLinked : labels.fillMissing,
    },
  ];
}

function formatAttributionPrerequisiteLabel(
  prerequisite: AttributionReviewPrerequisiteLike,
  labels: AttributionReadinessLabels,
) {
  const key = prerequisite.key as AttributionReviewPrerequisiteKey;
  if (key === 'strategy_signal') {
    return prerequisite.passed ? labels.signalLinked : labels.signalMissing;
  }
  if (key === 'candidate_action') {
    return prerequisite.passed ? labels.actionLinked : labels.actionMissing;
  }
  if (key === 'risk_gate') {
    return prerequisite.passed ? labels.riskLinked : labels.riskMissing;
  }
  if (key === 'manual_review') {
    return prerequisite.passed ? labels.reviewLinked : labels.reviewMissing;
  }
  if (key === 'order_evidence') {
    return prerequisite.passed ? labels.orderLinked : labels.orderMissing;
  }
  if (key === 'fill_evidence') {
    return prerequisite.passed ? labels.fillLinked : labels.fillMissing;
  }
  return prerequisite.passed ? labels.unknownLinked : labels.unknownMissing;
}
