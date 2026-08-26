// @ts-nocheck -- Node and TypeScript compiler APIs are used for source audits.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const FEATURES_ROOT = resolve(SRC_ROOT, 'features');
const MAX_PRODUCTION_MODULE_LINES = 600;
const MAX_NAMED_FUNCTION_LINES = 200;

const REFACTORED_PRODUCTION_FAMILIES = {
  decisionApi: [
    'features/decision/api.ts',
    'features/decision/api-contracts.ts',
    'features/decision/api-hooks.ts',
  ],
  accountEquityCurve: [
    'features/account/components/equity-curve-chart-support.tsx',
    'features/account/components/equity-curve-chart-model.ts',
    'features/account/components/equity-curve-chart-view.tsx',
  ],
  strategyHypothesis: [
    'features/research-workflow/components/strategy-hypothesis-panel.tsx',
    'features/research-workflow/components/strategy-hypothesis-copy.ts',
    'features/research-workflow/components/strategy-hypothesis-view.tsx',
    'features/research-workflow/components/use-strategy-hypothesis-controller.ts',
  ],
  feeScheduleReview: [
    'features/account-truth/components/fee-schedule-review-panel.tsx',
    'features/account-truth/components/fee-schedule-review-copy.ts',
    'features/account-truth/components/use-fee-schedule-review-controller.ts',
  ],
  portfolioCopy: [
    'features/portfolio/copy.ts',
    'features/portfolio/copy.en.ts',
    'features/portfolio/copy.zh.ts',
  ],
  operationsPage: [
    'features/operations/components/operations-page.tsx',
    'features/operations/components/operations-page-model.ts',
    'features/operations/components/use-operations-page-controller.tsx',
  ],
  backtestApi: [
    'features/backtest/api.ts',
    'features/backtest/api-contracts.ts',
    'features/backtest/api-governance-contracts.ts',
    'features/backtest/api-hooks.ts',
  ],
} as const;

const STABLE_STAR_EXPORT_FACADES = new Set(['features/backtest/api.ts']);

function familyModules() {
  return Object.values(REFACTORED_PRODUCTION_FAMILIES).flat();
}

function moduleSpecifiers(source: string) {
  const pattern =
    /\b(?:import|export)\s+(?:type\s+)?(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]/g;
  return Array.from(source.matchAll(pattern), (match) => match[1]);
}

function resolveSourceModule(importer: string, specifier: string) {
  const target = resolve(dirname(importer), specifier);
  return [target, `${target}.ts`, `${target}.tsx`].find(existsSync) ?? null;
}

function isInside(path: string, directory: string) {
  const pathFromDirectory = relative(directory, path);
  return (
    pathFromDirectory === '' ||
    (!pathFromDirectory.startsWith('..') && !isAbsolute(pathFromDirectory))
  );
}

function featureOwner(path: string) {
  return isInside(path, FEATURES_ROOT)
    ? relative(FEATURES_ROOT, path).split(/[\\/]/)[0]
    : null;
}

function namedFunctionSpans(path: string) {
  const lines = readFileSync(path, 'utf8').split(/\r?\n/);
  const declarations = lines.flatMap((line, index) => {
    const match = line.match(
      /^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)(?:<[^>]+>)?\s*\(/,
    );
    return match ? [{ name: match[1], index }] : [];
  });
  const topLevelBoundaries = lines.flatMap((line, index) =>
    /^(?:(?:export|declare)\s+)?(?:async\s+)?(?:function|const|let|class|interface|type)\b/.test(
      line,
    )
      ? [index]
      : [],
  );
  return declarations.map(({ name, index }) => {
    const end =
      topLevelBoundaries.find((boundary) => boundary > index) ?? lines.length;
    return { name, lines: end - index };
  });
}

function dependencyCycle(graph: Map<string, string[]>) {
  const state = new Map<string, 'visiting' | 'visited'>();
  const stack: string[] = [];
  const visit = (node: string): string[] | null => {
    if (state.get(node) === 'visiting') {
      const start = stack.indexOf(node);
      return [...stack.slice(start), node];
    }
    if (state.get(node) === 'visited') return null;
    state.set(node, 'visiting');
    stack.push(node);
    for (const target of graph.get(node) ?? []) {
      const cycle = visit(target);
      if (cycle) return cycle;
    }
    stack.pop();
    state.set(node, 'visited');
    return null;
  };
  for (const node of graph.keys()) {
    const cycle = visit(node);
    if (cycle) return cycle;
  }
  return null;
}

test('refactored production family inventory stays within reviewed budgets', () => {
  const oversizedModules = familyModules().flatMap((module) => {
    const lines = readFileSync(resolve(SRC_ROOT, module), 'utf8').split(
      /\r?\n/,
    ).length;
    return lines > MAX_PRODUCTION_MODULE_LINES ? [{ module, lines }] : [];
  });
  const oversizedFunctions = familyModules().flatMap((module) =>
    namedFunctionSpans(resolve(SRC_ROOT, module))
      .filter(({ lines }) => lines > MAX_NAMED_FUNCTION_LINES)
      .map(({ name, lines }) => ({ module, name, lines })),
  );

  expect(oversizedModules).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
});

test('refactored production families stay acyclic and feature-owned', () => {
  const modules = new Set(
    familyModules().map((module) => resolve(SRC_ROOT, module)),
  );
  const graph = new Map(
    Array.from(modules, (module) => [
      module,
      moduleSpecifiers(readFileSync(module, 'utf8')).flatMap((specifier) => {
        if (!specifier.startsWith('.')) return [];
        const target = resolveSourceModule(module, specifier);
        return target && modules.has(target) ? [target] : [];
      }),
    ]),
  );
  const privateCrossFeatureImports = Array.from(modules).flatMap((module) =>
    moduleSpecifiers(readFileSync(module, 'utf8')).flatMap((specifier) => {
      if (!specifier.startsWith('.')) return [];
      const target = resolveSourceModule(module, specifier);
      if (!target || !isInside(target, FEATURES_ROOT)) return [];
      const sourceOwner = featureOwner(module);
      const targetOwner = featureOwner(target);
      return sourceOwner !== targetOwner
        ? [`${relative(SRC_ROOT, module)} -> ${specifier}`]
        : [];
    }),
  );

  expect(
    dependencyCycle(graph)?.map((path) => relative(SRC_ROOT, path)) ?? [],
  ).toEqual([]);
  expect(privateCrossFeatureImports).toEqual([]);
});

test('new family modules do not add implicit star-export barrels', () => {
  const unexpectedStarExports = familyModules().flatMap((module) => {
    if (STABLE_STAR_EXPORT_FACADES.has(module)) return [];
    return /\bexport\s+\*\s+from\b/.test(
      readFileSync(resolve(SRC_ROOT, module), 'utf8'),
    )
      ? [module]
      : [];
  });

  expect(unexpectedStarExports).toEqual([]);
});
