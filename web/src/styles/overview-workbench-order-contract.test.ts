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

test('overview stays investment-first and leaves diagnostics to drill-down pages', () => {
  const summary = indexOfRequired('<OverviewSummary');
  const performance = indexOfRequired(
    'data-testid="overview-performance-card"',
  );
  const todayDigest = indexOfRequired('<OverviewTodayDigest');
  const holdings = indexOfRequired('<OverviewHoldingsSection');
  const allocationRisk = indexOfRequired('<OverviewAllocationRiskSection');
  const recommendation = indexOfRequired('<OverviewStrategyRecommendation');
  const attention = indexOfRequired('<DashboardTodayQueue');

  expect(summary).toBeLessThan(performance);
  expect(performance).toBeLessThan(todayDigest);
  expect(todayDigest).toBeLessThan(holdings);
  expect(holdings).toBeLessThan(allocationRisk);
  expect(allocationRisk).toBeLessThan(recommendation);
  expect(recommendation).toBeLessThan(attention);
  expect(source).not.toContain('<OverviewDataStatus');
  expect(source).not.toContain('<OverviewDataTrustStrip');
  expect(source).not.toContain('<OverviewValuationCoverage');
  expect(source).not.toContain('<OverviewDataDetails');
});
