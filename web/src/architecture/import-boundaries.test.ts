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
const RETURN_CALENDAR = resolve(
  ACCOUNT_FEATURE_ROOT,
  'components/return-calendar-card.tsx',
);
const MIGRATED_LEAF_PAGES = [
  {
    path: resolve(FEATURES_ROOT, 'activity/pages/activity-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'activity'),
    routePath: '/activity',
  },
  {
    path: resolve(FEATURES_ROOT, 'market/pages/market-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'market'),
    routePath: '/market',
  },
  {
    path: resolve(FEATURES_ROOT, 'portfolio/pages/portfolio-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'portfolio'),
    routePath: '/portfolio',
  },
  {
    path: resolve(FEATURES_ROOT, 'risk/pages/risk-page.tsx'),
    featureRoot: resolve(FEATURES_ROOT, 'risk'),
    routePath: '/risk',
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

test('migrated leaf pages do not import router or another feature page', () => {
  const violations = MIGRATED_LEAF_PAGES.flatMap(({ path, featureRoot }) =>
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

test('the composition root lazy-loads every migrated leaf page', () => {
  const routerTargets = relativeImportTargets(APP_ROUTER_SOURCE);

  for (const { path, routePath } of MIGRATED_LEAF_PAGES) {
    const modulePath = path.replace(/\.tsx$/, '');
    expect(routerTargets).toContain(modulePath);
    expect(readFileSync(path, 'utf8')).toContain(
      `createLazyRoute('${routePath}')`,
    );
  }
});
