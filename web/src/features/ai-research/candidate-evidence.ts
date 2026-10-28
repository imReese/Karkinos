import type { ShadowResearchCandidate } from './shadow-research-api';

export type CandidateEvidenceEvaluation = {
  isReportValid: boolean;
  invalidation: Record<string, unknown> | null;
  sourceResultId: number | null;
  metrics: {
    sharpe: number;
    total_return: number;
    max_drawdown: number;
  } | null;
};

export function evaluateCandidateEvidence(
  candidate: ShadowResearchCandidate | null | undefined,
  sourceQuery?: {
    data?: {
      id: number;
      metrics?: { sharpe: number; total_return: number; max_drawdown: number };
      evidence_invalidation?: Record<string, unknown> | null;
    } | null;
    isError: boolean;
  },
): CandidateEvidenceEvaluation {
  if (!candidate) {
    return {
      isReportValid: false,
      invalidation: null,
      sourceResultId: null,
      metrics: null,
    };
  }

  const sourceResultId =
    typeof candidate.candidate_result_id === 'number' &&
    Number.isSafeInteger(candidate.candidate_result_id) &&
    candidate.candidate_result_id > 0
      ? candidate.candidate_result_id
      : null;

  // 1. 候选撤回检查 (Candidate failed closed or evidence explicitly invalidated)
  const candidateInvalidation =
    candidate.status === 'failed_closed'
      ? { status: 'failed_closed', reason: 'candidate_failed_closed' }
      : (candidate.evidence_invalidation ?? null);

  // 2. 报告撤回检查 (Report invalidation)
  const reportInvalidation = sourceQuery?.data?.evidence_invalidation ?? null;
  const invalidation = candidateInvalidation ?? reportInvalidation;

  // 3. 报告 ID 校验 (Report ID positive integer and matching queried report ID)
  const hasWrongId = Boolean(
    sourceQuery?.data &&
    sourceResultId &&
    sourceQuery.data.id !== sourceResultId,
  );
  const isQueryError = Boolean(sourceQuery?.isError);
  const hasValidId = Boolean(sourceResultId);

  // 必须满足：未撤回、无查询错误、具备有效报告 ID、报告 ID 无错配
  const isReportValid =
    !invalidation && !isQueryError && hasValidId && !hasWrongId;

  let metrics: {
    sharpe: number;
    total_return: number;
    max_drawdown: number;
  } | null = null;

  if (isReportValid) {
    if (sourceQuery?.data?.metrics) {
      metrics = {
        sharpe: sourceQuery.data.metrics.sharpe,
        total_return: sourceQuery.data.metrics.total_return,
        max_drawdown: sourceQuery.data.metrics.max_drawdown,
      };
    } else if (candidate.comparison?.candidate) {
      metrics = {
        sharpe: candidate.comparison.candidate.sharpe,
        total_return: candidate.comparison.candidate.total_return,
        max_drawdown: candidate.comparison.candidate.max_drawdown,
      };
    }
  }

  return {
    isReportValid,
    invalidation,
    sourceResultId,
    metrics,
  };
}
