// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const APP_ROOT = resolve(SRC_ROOT, 'app');
const SHARED_ROOT = resolve(SRC_ROOT, 'shared');
const FEATURES_ROOT = resolve(SRC_ROOT, 'features');
const ACCOUNT_FEATURE_ROOT = resolve(FEATURES_ROOT, 'account');
const APP_ROUTER = resolve(APP_ROOT, 'router');
const APP_ROUTER_SOURCE = resolve(APP_ROOT, 'router.tsx');
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
    path: resolve(FEATURES_ROOT, 'overview/pages/overview-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'overview'),
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

test('shared modules do not depend on the app composition layer', () => {
  const violations = sourceFiles(SHARED_ROOT).flatMap((path) =>
    relativeImportTargets(path)
      .filter((target) => isInside(target, APP_ROOT))
      .map((target) => describeImport(path, target)),
  );

  expect(violations).toEqual([]);
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
