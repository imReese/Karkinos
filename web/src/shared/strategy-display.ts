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
  return (
    (name ? localizedNames[name] : undefined) ??
    (strategyId ? localizedNames[strategyId] : undefined) ??
    strategy.display_name?.trim() ??
    name ??
    strategyId ??
    '--'
  );
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
