export type StrategyDisplayRecord = {
  strategy_id?: string | null;
  name?: string | null;
  display_name?: string | null;
};

export type StrategyNameMap = Record<string, string>;

export function isShadowStrategy(
  strategyId: string | null | undefined,
): boolean {
  if (!strategyId) {
    return false;
  }
  const normalized = strategyId.trim().toLowerCase();
  return (
    normalized.startsWith('ai_formula_shadow:') ||
    normalized.startsWith('ai-shadow-candidate-') ||
    normalized.includes('shadow')
  );
}

export function formatStrategyDisplayName(
  strategy: StrategyDisplayRecord | null | undefined,
  localizedNames: StrategyNameMap,
) {
  if (!strategy) {
    return '--';
  }
  const strategyId = strategy.strategy_id?.trim();
  const name = strategy.name?.trim();
  const candidate =
    (name ? localizedNames[name] : undefined) ??
    (strategyId ? localizedNames[strategyId] : undefined) ??
    strategy.display_name?.trim() ??
    name ??
    strategyId;

  if (!candidate) {
    return '--';
  }

  if (
    candidate.startsWith('ai_formula_shadow:') ||
    candidate.startsWith('ai-shadow-candidate-') ||
    /(?:shadow[-_]candidate|ai_formula_shadow)/i.test(candidate)
  ) {
    const isEn = Object.values(localizedNames).some(
      (val) =>
        val.toLowerCase().includes('average') ||
        val.toLowerCase().includes('reversion'),
    );
    const candidateNumberMatch = candidate.match(
      /(?:^|[-_: ])candidate[-_]?(\d+)(?:$|[-_: ])/i,
    );
    if (candidateNumberMatch) {
      return isEn
        ? `AI Mined Strategy ${candidateNumberMatch[1]}`
        : `AI 挖掘策略 ${candidateNumberMatch[1]}`;
    }
    return isEn ? 'AI Mined Strategy' : 'AI 挖掘策略';
  }

  return candidate;
}

export function formatStrategyAuditLabel(
  strategyId: string | null | undefined,
  localizedNames: StrategyNameMap,
) {
  const normalized = strategyId?.trim();
  if (!normalized) {
    return '--';
  }
  const displayName = localizedNames[normalized] ?? normalized;
  return displayName === normalized
    ? normalized
    : `${displayName} · ${normalized}`;
}
