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

test('overview reads from account context into performance, holdings and low-priority diagnostics', () => {
  const status = indexOfRequired('<OverviewDataStatus');
  const summary = indexOfRequired('<OverviewSummary');
  const performance = indexOfRequired(
    'data-testid="overview-performance-card"',
  );
  const todayDigest = indexOfRequired('<OverviewTodayDigest');
  const holdings = indexOfRequired('<OverviewHoldingsSection');
  const allocationRisk = indexOfRequired('<OverviewAllocationRiskSection');
  const recommendation = indexOfRequired('<OverviewStrategyRecommendation');
  const attention = indexOfRequired('<DashboardTodayQueue');
  const dataTrust = indexOfRequired('<OverviewDataTrustStrip');
  const valuationCoverage = indexOfRequired('<OverviewValuationCoverage');
  const details = indexOfRequired('<OverviewDataDetails');

  expect(status).toBeLessThan(summary);
  expect(summary).toBeLessThan(performance);
  expect(performance).toBeLessThan(todayDigest);
  expect(todayDigest).toBeLessThan(holdings);
  expect(holdings).toBeLessThan(allocationRisk);
  expect(allocationRisk).toBeLessThan(recommendation);
  expect(recommendation).toBeLessThan(attention);
  expect(attention).toBeLessThan(dataTrust);
  expect(dataTrust).toBeLessThan(valuationCoverage);
  expect(valuationCoverage).toBeLessThan(details);
});
