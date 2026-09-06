export function drawdownUnavailableLabel(
  blockers: string[] | undefined,
  labels: { drawdownUnavailable: string; drawdownHistoricalCorrection: string },
) {
  const reasons = [];
  if (blockers?.includes('historical_correction_performance_unverified')) {
    reasons.push(labels.drawdownHistoricalCorrection);
  }
  if (!reasons.length || blockers?.includes('drawdown_history_unavailable')) {
    reasons.push(labels.drawdownUnavailable);
  }
  return reasons.join(' · ');
}
