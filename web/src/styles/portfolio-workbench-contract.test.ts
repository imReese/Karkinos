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
const portfolioApiSource = readFileSync(
  resolve(SRC_ROOT, 'features/portfolio/api.ts'),
  'utf8',
);
const globalStyles = readFileSync(
  resolve(SRC_ROOT, 'styles/globals.css'),
  'utf8',
);
const routerSource = readFileSync(resolve(SRC_ROOT, 'app/router.tsx'), 'utf8');
const portfolioPageSource = routerSource.slice(
  routerSource.indexOf('export function PortfolioPage()'),
  routerSource.indexOf('export function RiskPage()'),
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

test('portfolio tables expose primary facts and a mobile master-detail list', () => {
  expect(positionsTableSource).toContain("id: 'market-value'");
  expect(positionsTableSource).toContain("id: 'weight'");
  expect(positionsTableSource).toContain("id: 'today-change'");
  expect(positionsTableSource).toContain("id: 'unrealized'");
  expect(positionsTableSource).toContain("id: 'realized'");
  expect(positionsTableSource).toContain("id: 'quote-state'");
  expect(positionsTableSource).toContain('positions-mobile-list');
  expect(positionsTableSource).toContain('position-mobile-row-');
  expect(positionsTableSource).toContain('app-position-mobile-row');
  expect(positionsTableSource).toContain('md:hidden');
  expect(positionsTableSource).toContain('hidden min-w-0 md:block');
  expect(globalStyles).toContain(
    '.app-shell-content a.app-position-mobile-row',
  );
  expect(positionsTableSource).not.toContain('useRefreshMarketQuotesMutation');
  expect(positionsTableSource).not.toContain("id: 'actions'");
  expect(liveHoldingsSource).toContain('minmax(84px,1fr)');
  expect(liveHoldingsSource).toContain('overflow-x-auto');
  expect(liveHoldingsSource).not.toContain('overflow-hidden');
});

test('portfolio lifecycle states stay flat instead of rebuilding a card wall', () => {
  expect(portfolioPageSource).toContain('<EvidenceState');
  expect(portfolioPageSource).not.toContain('<StatusCard');
  expect(portfolioPageSource).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
});

test('portfolio defers secondary read models until primary holdings facts settle', () => {
  expect(portfolioPageSource).toContain(
    'const primaryPortfolioQueriesSettled =',
  );
  expect(portfolioPageSource).toContain('const isInitialPortfolioLoad =');
  expect(portfolioPageSource).toContain('<EvidenceLoadingLayout');
  expect(portfolioPageSource).toContain(
    'usePortfolioCockpitQuery(primaryPortfolioQueriesSettled)',
  );
  expect(portfolioPageSource).toContain(
    'useLiveHoldingsQuery(primaryPortfolioQueriesSettled)',
  );
  expect(portfolioPageSource).toContain(
    'useAccountStrategyContributionQuery(\n    primaryPortfolioQueriesSettled,',
  );
  expect(portfolioPageSource).toContain(
    'description={portfolioPrimaryFailureDetail}',
  );
  expect(portfolioPageSource).not.toContain(
    '!primaryPortfolioQueriesSettled || liveHoldings.isLoading',
  );
  expect(portfolioApiSource).toContain(
    'export function usePortfolioCockpitQuery(enabled = true)',
  );
  expect(portfolioApiSource).toContain(
    'export function useLiveHoldingsQuery(enabled = true)',
  );
});
