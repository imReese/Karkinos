export type ChunkName = string | undefined;

export function normalizeModuleId(id: string) {
  return id.replace(/\\/g, '/');
}

export function appFeatureChunk(id: string): ChunkName {
  const normalizedId = normalizeModuleId(id);

  if (
    normalizedId.includes('node_modules') ||
    !normalizedId.includes('/src/features/')
  ) {
    return undefined;
  }

  if (
    normalizedId.includes('/src/features/account/') ||
    normalizedId.includes('/src/features/account-strategy/') ||
    normalizedId.includes('/src/features/account-truth/')
  ) {
    return 'feature-account';
  }
  if (normalizedId.includes('/src/features/activity/')) {
    return 'feature-activity';
  }
  if (normalizedId.includes('/src/features/backtest/')) {
    return 'feature-backtest';
  }
  if (
    normalizedId.includes('/src/features/market/') ||
    normalizedId.includes('/src/features/portfolio/')
  ) {
    return 'feature-market-portfolio';
  }
  if (normalizedId.includes('/src/features/decision/')) {
    return 'feature-decision';
  }
  if (normalizedId.includes('/src/features/settings/')) {
    return 'feature-settings';
  }
  if (normalizedId.includes('/src/features/trading/')) {
    return 'feature-trading';
  }

  return undefined;
}
