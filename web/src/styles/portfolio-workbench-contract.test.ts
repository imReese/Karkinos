// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const strategyContributionSource = readFileSync(
  resolve(
    SRC_ROOT,
    'features/account-strategy/components/strategy-contribution-gate-card.tsx',
  ),
  'utf8',
);
const constructionRecommendationsSource = readFileSync(
  resolve(
    SRC_ROOT,
    'features/portfolio/components/portfolio-construction-recommendations-card.tsx',
  ),
  'utf8',
);
const positionsTableSource = readFileSync(
  resolve(SRC_ROOT, 'features/portfolio/components/positions-table.tsx'),
  'utf8',
);
const liveHoldingsSource = readFileSync(
  resolve(SRC_ROOT, 'features/portfolio/components/live-holdings-board.tsx'),
  'utf8',
);

test('portfolio strategy evidence uses flat standard workbench primitives', () => {
  expect(strategyContributionSource).toContain('<MetricStrip');
  expect(strategyContributionSource).toContain('<StatusBadge');
  expect(strategyContributionSource).toContain('<EvidenceState');
  expect(strategyContributionSource).not.toMatch(/app-terminal/);
  expect(strategyContributionSource).not.toMatch(/rounded-(?:2xl|3xl)/);

  expect(constructionRecommendationsSource).toContain('<MetricStrip');
  expect(constructionRecommendationsSource).toContain('<StatusBadge');
  expect(constructionRecommendationsSource).toContain('<EvidenceState');
  expect(constructionRecommendationsSource).not.toMatch(/app-panel/);
  expect(constructionRecommendationsSource).not.toMatch(
    /rounded-(?:xl|2xl|3xl|full)/,
  );
});

test('portfolio tables expose decision facts before secondary detail', () => {
  const primaryOrder = [
    "'market-value'",
    "'weight'",
    "'today-change'",
    "'unrealized'",
    "'realized'",
    "'quote-state'",
  ].map((column) => positionsTableSource.indexOf(column, 13_000));

  expect(primaryOrder.every((index) => index >= 0)).toBe(true);
  expect(primaryOrder).toEqual([...primaryOrder].sort((a, b) => a - b));
  expect(liveHoldingsSource).toContain('minmax(84px,1fr)');
  expect(liveHoldingsSource).toContain('overflow-x-auto');
  expect(liveHoldingsSource).not.toContain('overflow-hidden');
});
