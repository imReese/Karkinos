// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(
  resolve(
    SRC_ROOT,
    'features/overview/components/overview-resolved-workspace.tsx',
  ),
  'utf8',
);

function indexOfRequired(fragment: string) {
  const index = source.indexOf(fragment);
  expect(index).toBeGreaterThanOrEqual(0);
  return index;
}

test('overview reads like an investment summary before diagnostics', () => {
  const summary = indexOfRequired('<OverviewSummary');
  const status = indexOfRequired('<OverviewDataStatus');
  const attention = indexOfRequired('<DashboardTodayQueue');
  const holdings = indexOfRequired('<OverviewHoldingsSection');
  const performance = indexOfRequired(
    'data-testid="overview-performance-card"',
  );
  const recommendation = indexOfRequired('<OverviewStrategyRecommendation');
  const valuationCoverage = indexOfRequired('<OverviewValuationCoverage');
  const marketStatus = indexOfRequired('<OverviewMarketStatus');
  const details = indexOfRequired('<OverviewDataDetails');

  expect(summary).toBeLessThan(status);
  expect(status).toBeLessThan(attention);
  expect(attention).toBeLessThan(holdings);
  expect(holdings).toBeLessThan(performance);
  expect(performance).toBeLessThan(recommendation);
  expect(recommendation).toBeLessThan(valuationCoverage);
  expect(valuationCoverage).toBeLessThan(marketStatus);
  expect(marketStatus).toBeLessThan(details);
});
