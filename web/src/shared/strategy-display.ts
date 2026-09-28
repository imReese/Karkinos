export type StrategyDisplayRecord = {
  strategy_id?: string | null;
  name?: string | null;
  display_name?: string | null;
};

export type StrategyNameMap = Record<string, string>;

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

  const shadowMatch = candidate.match(
    /(?:shadow[-_]candidate|ai_formula_shadow)[-_:]([a-f0-9]{6,})/i,
  );
  if (shadowMatch) {
    const hash = shadowMatch[1].slice(0, 6);
    const isEn = Object.values(localizedNames).some(
      (val) =>
        val.toLowerCase().includes('average') ||
        val.toLowerCase().includes('reversion'),
    );
    return isEn ? `Shadow Candidate (#${hash})` : `影子策略候选 (#${hash})`;
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
