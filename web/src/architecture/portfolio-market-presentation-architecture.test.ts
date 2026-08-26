// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const POSITIONS_TABLE_FILES = [
  'features/portfolio/components/positions-table.tsx',
  'features/portfolio/components/positions-table-model.ts',
  'features/portfolio/components/positions-table-columns.tsx',
  'features/portfolio/components/positions-table-mobile-list.tsx',
  'features/portfolio/components/positions-table-view.tsx',
];
const PORTFOLIO_PAGE_FILES = [
  'features/portfolio/pages/portfolio-page.tsx',
  'features/portfolio/pages/portfolio-page-controller.tsx',
  'features/portfolio/pages/portfolio-page-model.ts',
  'features/portfolio/pages/portfolio-page-view.tsx',
  'features/portfolio/pages/portfolio-page-sections.tsx',
  'features/portfolio/pages/portfolio-page-loading-view.tsx',
  'features/portfolio/pages/portfolio-evidence-review-panel.tsx',
];
const PRICE_STRUCTURE_FILES = [
  'features/market/components/price-structure-chart.tsx',
  'features/market/components/price-structure-chart-model.ts',
  'features/market/components/price-structure-chart-sections.tsx',
  'features/market/components/price-structure-chart-svg.tsx',
  'features/market/components/price-structure-chart-view.tsx',
  'features/market/components/price-structure-loading-state.tsx',
];
const PRODUCTION_FILES = [
  ...POSITIONS_TABLE_FILES,
  ...PORTFOLIO_PAGE_FILES,
  ...PRICE_STRUCTURE_FILES,
];
const SOURCES = new Map(
  PRODUCTION_FILES.map((path) => [
    path,
    readFileSync(resolve(SRC_ROOT, path), 'utf8'),
  ]),
);

function familySource(paths: string[]) {
  return paths.map((path) => SOURCES.get(path)).join('\n');
}

test('portfolio and price presentation families stay structurally bounded', () => {
  const violations: string[] = [];
  for (const [path, source] of SOURCES) {
    const sourceLines = source.split(/\r?\n/);
    if (sourceLines.length > 800) {
      violations.push(`${path}: module has ${sourceLines.length} lines`);
    }
    for (let start = 0; start < sourceLines.length; start += 1) {
      const declaration = sourceLines[start].match(
        /^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b/,
      );
      if (!declaration) continue;
      const endOffset = sourceLines
        .slice(start + 1)
        .findIndex((line) => line === '}');
      if (endOffset < 0) continue;
      const functionLines = endOffset + 2;
      if (functionLines > 350) {
        violations.push(
          `${path}:${start + 1} ${declaration[1]} has ${functionLines} lines`,
        );
      }
    }
  }
  expect(violations).toEqual([]);
});

test('public facades delegate to explicit controller-model-view families', () => {
  const positionsFacade = SOURCES.get(POSITIONS_TABLE_FILES[0]);
  const portfolioFacade = SOURCES.get(PORTFOLIO_PAGE_FILES[0]);
  const chartFacade = SOURCES.get(PRICE_STRUCTURE_FILES[0]);
  expect(positionsFacade).toContain('buildPositionsTableModel');
  expect(positionsFacade).toContain('<PositionsTableView');
  expect(portfolioFacade).toContain('<PortfolioPageController');
  expect(portfolioFacade).toContain("createLazyRoute('/portfolio')");
  expect(chartFacade).toContain('buildPriceStructureChartModel');
  expect(chartFacade).toContain('<PriceStructureChartView');
  expect(chartFacade).toContain("from './price-structure-loading-state'");
});

test('portfolio consumes market presentation only through its explicit boundary', () => {
  const portfolioSource = familySource([
    ...POSITIONS_TABLE_FILES,
    ...PORTFOLIO_PAGE_FILES,
  ]);
  const boundarySource = readFileSync(
    resolve(SRC_ROOT, 'features/portfolio/portfolio-feature-boundary.ts'),
    'utf8',
  );
  expect(portfolioSource).not.toMatch(/from ['"]\.\.\/market\//);
  expect(boundarySource).toContain(
    "from '../market/components/price-structure-chart'",
  );
});

test('financial evidence remains provider-free and fails closed', () => {
  const positionsSource = familySource(POSITIONS_TABLE_FILES);
  const portfolioSource = familySource(PORTFOLIO_PAGE_FILES);
  const chartSource = familySource(PRICE_STRUCTURE_FILES);
  expect(positionsSource).toContain('quoteNeedsReview(position.quote_status)');
  expect(positionsSource).toContain(
    '? formatPublicStatus(position.quote_status',
  );
  expect(positionsSource).not.toContain('useRefreshMarketQuotesMutation');
  expect(portfolioSource).toContain(
    'const primaryPortfolioQueriesSettled = snapshot.data !== undefined',
  );
  expect(portfolioSource).toContain(
    "primaryPortfolioQueriesSettled && mode === 'account'",
  );
  expect(portfolioSource).toContain(
    "primaryPortfolioQueriesSettled && mode === 'strategy'",
  );
  expect(portfolioSource).not.toContain('useRefreshMarketQuotesMutation');
  expect(chartSource).toContain('.filter((bar) => Number.isFinite(bar.close))');
  expect(chartSource).toContain('if (validBars.length === 0)');
  expect(chartSource).toContain('return null;');
  expect(chartSource).toContain(
    'const plottedReferenceLines = referenceLines.filter',
  );
  expect(chartSource).toContain('Number.isFinite(line.value)');
});
