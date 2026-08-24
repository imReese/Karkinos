// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const APP_ROOT = resolve(SRC_ROOT, 'app');
const SHARED_ROOT = resolve(SRC_ROOT, 'shared');
const FEATURES_ROOT = resolve(SRC_ROOT, 'features');
const LEGACY_LIB_ROOT = resolve(SRC_ROOT, 'lib');
const WIDGETS_ROOT = resolve(SRC_ROOT, 'widgets');
const PAGES_ROOT = resolve(SRC_ROOT, 'pages');
const ACCOUNT_FEATURE_ROOT = resolve(FEATURES_ROOT, 'account');
const OVERVIEW_FEATURE_ROOT = resolve(FEATURES_ROOT, 'overview');
const OVERVIEW_PAGE_SOURCE = resolve(
  OVERVIEW_FEATURE_ROOT,
  'pages/overview-page.tsx',
);
const OVERVIEW_TODAY_QUEUE_SOURCE = resolve(
  OVERVIEW_FEATURE_ROOT,
  'pages/overview-today-queue.tsx',
);
const OVERVIEW_TODAY_QUEUE = resolve(
  OVERVIEW_FEATURE_ROOT,
  'pages/overview-today-queue',
);
const APP_ROUTER = resolve(APP_ROOT, 'router');
const APP_ROUTER_SOURCE = resolve(APP_ROOT, 'router.tsx');
const PREFERENCES_CONTEXT_SOURCE = resolve(
  SHARED_ROOT,
  'preferences/context.tsx',
);
const PREFERENCES_PROVIDER_SOURCE = resolve(
  APP_ROOT,
  'providers/preferences-provider.tsx',
);
const APP_SHELL = resolve(APP_ROOT, 'layout/app-shell');
const RETURN_CALENDAR = resolve(
  ACCOUNT_FEATURE_ROOT,
  'components/return-calendar-card.tsx',
);
const LAZY_ROUTE_PAGES = [
  {
    path: resolve(FEATURES_ROOT, 'home/pages/public-home-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'home'),
    routePath: '/',
  },
  {
    path: resolve(FEATURES_ROOT, 'activity/pages/activity-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'activity'),
    routePath: '/activity',
  },
  {
    path: resolve(FEATURES_ROOT, 'account-truth/pages/account-truth-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'account-truth'),
    routePath: '/account-truth',
  },
  {
    path: resolve(FEATURES_ROOT, 'ai-research/pages/ai-research-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'ai-research'),
    routePath: '/ai-research',
  },
  {
    path: resolve(FEATURES_ROOT, 'backtest/pages/backtest-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'backtest'),
    routePath: '/backtest',
  },
  {
    path: resolve(FEATURES_ROOT, 'decision/pages/decision-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'decision'),
    routePath: '/decision',
  },
  {
    path: resolve(FEATURES_ROOT, 'market/pages/market-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'market'),
    routePath: '/market',
  },
  {
    path: resolve(FEATURES_ROOT, 'operations/pages/operations-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'operations'),
    routePath: '/operations',
  },
  {
    path: OVERVIEW_PAGE_SOURCE,
    featureRoot: OVERVIEW_FEATURE_ROOT,
    routePath: '/overview',
  },
  {
    path: resolve(FEATURES_ROOT, 'portfolio/pages/portfolio-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'portfolio'),
    routePath: '/portfolio',
  },
  {
    path: resolve(FEATURES_ROOT, 'portfolio/pages/holding-detail-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'portfolio'),
    routePath: '/portfolio/$symbol',
  },
  {
    path: resolve(FEATURES_ROOT, 'risk/pages/risk-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'risk'),
    routePath: '/risk',
  },
  {
    path: resolve(FEATURES_ROOT, 'settings/pages/settings-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'settings'),
    routePath: '/settings',
  },
  {
    path: resolve(FEATURES_ROOT, 'trading/pages/trading-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'trading'),
    routePath: '/trading',
  },
];

// Temporary copy-only debt ratchet. This exact set may shrink but must never be
// replaced or expanded. The copy decomposition slice removes this list.
const LEGACY_FEATURE_TO_APP_EDGES = new Set([
  'features/account/components/daily-operations-tower.tsx -> app/copy',
  'features/account/components/dashboard-quick-actions.tsx -> app/copy',
  'features/account/components/equity-curve-card.tsx -> app/copy',
  'features/account/components/live-holdings-summary-card.tsx -> app/copy',
  'features/account/components/overview-cards.tsx -> app/copy',
  'features/account/components/performance-breakdown-card.tsx -> app/copy',
  'features/account/components/portfolio-exposure-summary.tsx -> app/copy',
  'features/account/components/return-calendar-card.tsx -> app/copy',
  'features/account/components/risk-summary-card.tsx -> app/copy',
  'features/account-strategy/components/strategy-contribution-gate-card.tsx -> app/copy',
  'features/activity/components/activity-feed.tsx -> app/copy',
  'features/activity/components/cash-flow-form.tsx -> app/copy',
  'features/activity/components/dividend-form.tsx -> app/copy',
  'features/activity/components/fund-batch-form.tsx -> app/copy',
  'features/activity/components/manual-adjustment-form.tsx -> app/copy',
  'features/activity/components/trade-form.tsx -> app/copy',
  'features/activity/pages/activity-page.tsx -> app/copy',
  'features/ai-research/components/ai-research-page.tsx -> app/copy',
  'features/ai-research/components/research-task-panel.tsx -> app/copy',
  'features/backtest/components/backtest-page.tsx -> app/copy',
  'features/backtest/components/backtest-report-view.tsx -> app/copy',
  'features/backtest/components/dataset-snapshot-panel.tsx -> app/copy',
  'features/backtest/components/equity-drawdown-chart.tsx -> app/copy',
  'features/backtest/components/fills-table.tsx -> app/copy',
  'features/backtest/components/metrics-grid.tsx -> app/copy',
  'features/backtest/components/parameter-compare-panel.tsx -> app/copy',
  'features/backtest/components/parameter-sweep-panel.tsx -> app/copy',
  'features/backtest/components/strategy-metadata-snapshot-panel.tsx -> app/copy',
  'features/backtest/components/validation-evidence-panel.tsx -> app/copy',
  'features/decision/components/decision-cockpit-page.tsx -> app/copy',
  'features/decision/components/decision-outcome-review-panel.tsx -> app/copy',
  'features/market/components/confirmed-fund-nav-refresh-button.tsx -> app/copy',
  'features/market/components/current-holding-market-evidence-review-panel.tsx -> app/copy',
  'features/market/components/market-instrument-workspace.tsx -> app/copy',
  'features/market/components/market-refresh-button.tsx -> app/copy',
  'features/market/pages/market-page.tsx -> app/copy',
  'features/operations/components/operations-page.tsx -> app/copy',
  'features/overview/pages/overview-page.tsx -> app/copy',
  'features/overview/pages/overview-today-queue.tsx -> app/copy',
  'features/portfolio/components/allocation-card.tsx -> app/copy',
  'features/portfolio/components/allocation-groups-card.tsx -> app/copy',
  'features/portfolio/components/holding-detail-page.tsx -> app/copy',
  'features/portfolio/components/live-holdings-board.tsx -> app/copy',
  'features/portfolio/components/positions-table.tsx -> app/copy',
  'features/portfolio/components/workspace-toolbar.tsx -> app/copy',
  'features/portfolio/pages/portfolio-page.tsx -> app/copy',
  'features/risk/pages/risk-page.tsx -> app/copy',
  'features/settings/components/settings-page.tsx -> app/copy',
  'features/trading/components/kill-switch-panel.tsx -> app/copy',
  'features/trading/components/order-approval-table.tsx -> app/copy',
  'features/trading/components/trading-page.tsx -> app/copy',
]);

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(?:ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

function relativeImportTargets(path: string) {
  const source = readFileSync(path, 'utf8');
  const specifiers = new Set<string>();
  const staticImports =
    /\b(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/g;
  const dynamicImports = /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g;

  for (const pattern of [staticImports, dynamicImports]) {
    for (const match of source.matchAll(pattern)) {
      const specifier = match[1];
      if (specifier.startsWith('.')) {
        specifiers.add(resolve(dirname(path), specifier));
      }
    }
  }

  return Array.from(specifiers);
}

function staticRelativeImportTargets(path: string) {
  const source = readFileSync(path, 'utf8');
  const targets = new Set<string>();
  const staticImports =
    /\b(?:import|export)\s+(?:type\s+)?(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]/g;

  for (const match of source.matchAll(staticImports)) {
    const specifier = match[1];
    if (specifier.startsWith('.')) {
      targets.add(resolve(dirname(path), specifier));
    }
  }

  return Array.from(targets);
}

function isInside(path: string, directory: string) {
  const pathFromDirectory = relative(directory, path);
  return (
    pathFromDirectory === '' ||
    (!pathFromDirectory.startsWith('..') && !isAbsolute(pathFromDirectory))
  );
}

function describeImport(importer: string, target: string) {
  return `${relative(SRC_ROOT, importer)} -> ${relative(SRC_ROOT, target)}`;
}

test('shared modules do not depend on legacy or higher application layers', () => {
  const forbiddenRoots = [
    LEGACY_LIB_ROOT,
    APP_ROOT,
    FEATURES_ROOT,
    WIDGETS_ROOT,
    PAGES_ROOT,
  ];
  const violations = sourceFiles(SHARED_ROOT).flatMap((path) =>
    relativeImportTargets(path)
      .filter((target) =>
        forbiddenRoots.some((directory) => isInside(target, directory)),
      )
      .map((target) => describeImport(path, target)),
  );

  expect(violations).toEqual([]);
});

test('feature modules have no app dependencies beyond shrinking copy debt', () => {
  const actualEdges = new Set(
    sourceFiles(FEATURES_ROOT)
      .filter((path) => !/\.(?:test|spec)\.(?:ts|tsx)$/.test(path))
      .flatMap((path) =>
        relativeImportTargets(path)
          .filter((target) => isInside(target, APP_ROOT))
          .map((target) => describeImport(path, target)),
      ),
  );
  const unexpectedEdges = Array.from(actualEdges)
    .filter((edge) => !LEGACY_FEATURE_TO_APP_EDGES.has(edge))
    .sort();

  expect(unexpectedEdges).toEqual([]);
  expect(Array.from(actualEdges).sort()).toEqual(
    Array.from(LEGACY_FEATURE_TO_APP_EDGES).sort(),
  );
});

test('browser preference effects stay in the app provider', () => {
  const contextSource = readFileSync(PREFERENCES_CONTEXT_SOURCE, 'utf8');
  const providerSource = readFileSync(PREFERENCES_PROVIDER_SOURCE, 'utf8');

  expect(contextSource).not.toMatch(/\b(?:document|localStorage|matchMedia)\b/);
  expect(providerSource).toContain("from '../../shared/preferences/context'");
  expect(providerSource).toContain('window.localStorage');
  expect(providerSource).toContain('window.matchMedia');
  expect(providerSource).toContain('document.documentElement');
});

test('the return calendar slice does not depend on another feature or router', () => {
  const violations = relativeImportTargets(RETURN_CALENDAR)
    .filter(
      (target) =>
        (isInside(target, FEATURES_ROOT) &&
          !isInside(target, ACCOUNT_FEATURE_ROOT)) ||
        target === APP_ROUTER,
    )
    .map((target) => describeImport(RETURN_CALENDAR, target));

  expect(violations).toEqual([]);
});

test('lazy route pages do not import router or another feature page', () => {
  const violations = LAZY_ROUTE_PAGES.flatMap(({ path, featureRoot }) =>
    relativeImportTargets(path)
      .filter((target) => {
        const targetFromFeatures = relative(FEATURES_ROOT, target).replace(
          /\\/g,
          '/',
        );
        const importsAnotherFeaturePage =
          isInside(target, FEATURES_ROOT) &&
          !isInside(target, featureRoot) &&
          targetFromFeatures.includes('/pages/');
        return target === APP_ROUTER || importsAnotherFeaturePage;
      })
      .map((target) => describeImport(path, target)),
  );

  expect(violations).toEqual([]);
});

test('the overview page delegates its today queue to one same-feature route module', () => {
  const pageSource = readFileSync(OVERVIEW_PAGE_SOURCE, 'utf8');
  const queueSource = readFileSync(OVERVIEW_TODAY_QUEUE_SOURCE, 'utf8');
  const sameFeatureTargets = staticRelativeImportTargets(
    OVERVIEW_PAGE_SOURCE,
  ).filter((target) => isInside(target, OVERVIEW_FEATURE_ROOT));

  expect(sameFeatureTargets).toEqual([OVERVIEW_TODAY_QUEUE]);
  expect(pageSource).toContain('<DashboardTodayQueue');
  expect(pageSource).not.toMatch(/\bfunction\s+DashboardTodayQueue\s*\(/);
  expect(queueSource).toMatch(/\bexport\s+function\s+DashboardTodayQueue\s*\(/);
  expect(queueSource.match(/^export\s+/gm)).toEqual(['export ']);
});

test('the overview today queue does not import any feature page', () => {
  const violations = relativeImportTargets(OVERVIEW_TODAY_QUEUE_SOURCE)
    .filter((target) => {
      const targetFromFeatures = relative(FEATURES_ROOT, target).replace(
        /\\/g,
        '/',
      );
      return (
        isInside(target, FEATURES_ROOT) &&
        targetFromFeatures.includes('/pages/')
      );
    })
    .map((target) => describeImport(OVERVIEW_TODAY_QUEUE_SOURCE, target));

  expect(violations).toEqual([]);
});

test('the composition root does not define or export the overview page', () => {
  const source = readFileSync(APP_ROUTER_SOURCE, 'utf8');

  expect(source).not.toMatch(/\b(?:export\s+)?function\s+OverviewPage\s*\(/);
  expect(source).not.toMatch(/\bexport\s*\{[^}]*\bOverviewPage\b[^}]*\}/s);
  expect(source).not.toMatch(/\bcomponent:\s*OverviewPage\b/);
});

test('the composition root does not statically import feature implementations', () => {
  const violations = staticRelativeImportTargets(APP_ROUTER_SOURCE)
    .filter((target) => isInside(target, FEATURES_ROOT))
    .map((target) => describeImport(APP_ROUTER_SOURCE, target));

  expect(violations).toEqual([]);
});

test('the composition root keeps the workspace shell behind a dynamic boundary', () => {
  const staticTargets = staticRelativeImportTargets(APP_ROUTER_SOURCE);
  const allTargets = relativeImportTargets(APP_ROUTER_SOURCE);

  expect(staticTargets).not.toContain(APP_SHELL);
  expect(allTargets).toContain(APP_SHELL);
});

test('the router publishes an immediate non-interactive pending route contract', () => {
  const source = readFileSync(APP_ROUTER_SOURCE, 'utf8');

  expect(source).toContain('defaultPendingComponent: RoutePending');
  expect(source).toContain('defaultPendingMs: 0');
  expect(source).toContain('defaultPendingMinMs: 0');
  expect(source).toContain("defaultPreload: 'intent'");
  expect(source).toContain("declare module '@tanstack/react-router'");
  expect(source).toContain('router: typeof router');
});

test('the composition root lazy-loads every feature route page', () => {
  const routerTargets = relativeImportTargets(APP_ROUTER_SOURCE);

  for (const { path, routePath } of LAZY_ROUTE_PAGES) {
    const modulePath = path.replace(/\.tsx$/, '');
    expect(routerTargets).toContain(modulePath);
    expect(readFileSync(path, 'utf8')).toContain(
      `createLazyRoute('${routePath}')`,
    );
  }
});
