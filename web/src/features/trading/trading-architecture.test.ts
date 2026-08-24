// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const TRADING_ROOT = dirname(fileURLToPath(import.meta.url));
const FEATURES_ROOT = resolve(TRADING_ROOT, '..');
const APP_ROOT = resolve(TRADING_ROOT, '../../app');

function productionFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      return productionFiles(path);
    }
    return /\.(?:ts|tsx)$/.test(entry.name) &&
      !/\.(?:test|spec)\.(?:ts|tsx)$/.test(entry.name)
      ? [path]
      : [];
  });
}

function isInside(path: string, directory: string) {
  const pathFromDirectory = relative(directory, path);
  return (
    pathFromDirectory === '' ||
    (!pathFromDirectory.startsWith('..') && !isAbsolute(pathFromDirectory))
  );
}

function moduleSpecifiers(path: string) {
  const source = readFileSync(path, 'utf8');
  const pattern =
    /\b(?:import|export)\s+(?:type\s+)?(?:[^'\"]*?\s+from\s+)?['\"]([^'\"]+)['\"]/g;
  return Array.from(source.matchAll(pattern), (match) => match[1]);
}

function namedFunctionSpans(path: string) {
  const lines = readFileSync(path, 'utf8').split(/\r?\n/);
  const declarations = lines.flatMap((line, index) => {
    const match = line.match(
      /^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(/,
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

function resolveTradingModule(importer: string, specifier: string) {
  const files = productionFiles(TRADING_ROOT);
  const target = resolve(dirname(importer), specifier);
  return [
    target,
    `${target}.ts`,
    `${target}.tsx`,
    resolve(target, 'index.ts'),
    resolve(target, 'index.tsx'),
  ].find((candidate) => files.includes(candidate));
}

function dependencyCycle(graph: Map<string, string[]>) {
  const state = new Map<string, 'visiting' | 'visited'>();
  const stack: string[] = [];
  const visit = (node: string): string[] | null => {
    if (state.get(node) === 'visiting') {
      return [...stack.slice(stack.indexOf(node)), node];
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

test('trading production modules and named functions stay bounded', () => {
  const files = productionFiles(TRADING_ROOT);
  const oversizedFiles = files
    .map((path) => ({
      path: relative(TRADING_ROOT, path),
      lines: readFileSync(path, 'utf8').split(/\r?\n/).length,
    }))
    .filter(({ lines }) => lines > 800);
  const oversizedFunctions = files.flatMap((path) =>
    namedFunctionSpans(path)
      .filter(({ lines }) => lines > 350)
      .map(({ name, lines }) => ({
        path: relative(TRADING_ROOT, path),
        name,
        lines,
      })),
  );

  expect(oversizedFiles).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
});

test('trading imports stay out of app and preserve the reviewed feature boundary', () => {
  const files = productionFiles(TRADING_ROOT);
  const appImports = files.flatMap((path) =>
    moduleSpecifiers(path)
      .filter((specifier) => specifier.startsWith('.'))
      .map((specifier) => resolve(dirname(path), specifier))
      .filter((target) => isInside(target, APP_ROOT))
      .map(
        (target) =>
          `${relative(TRADING_ROOT, path)} -> ${relative(APP_ROOT, target)}`,
      ),
  );
  const featureImports = files
    .flatMap((path) =>
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .map((specifier) => ({
          specifier,
          target: resolve(dirname(path), specifier),
        }))
        .filter(
          ({ target }) =>
            isInside(target, FEATURES_ROOT) && !isInside(target, TRADING_ROOT),
        )
        .map(
          ({ specifier }) => `${relative(TRADING_ROOT, path)} -> ${specifier}`,
        ),
    )
    .sort();

  expect(appImports).toEqual([]);
  expect(featureImports).toEqual([
    'operations-boundary.ts -> ../operations/api',
    'operations-boundary.ts -> ../operations/controlled-broker-write-release-operator-panel',
    'operations-boundary.ts -> ../operations/current-per-order-dossier-operator-panel',
    'operations-boundary.ts -> ../operations/signed-broker-adapter-release-review-operator-panel',
    'portfolio-boundary.ts -> ../portfolio/api',
  ]);
});

test('trading production modules remain acyclic', () => {
  const files = productionFiles(TRADING_ROOT);
  const graph = new Map(
    files.map((path) => [
      path,
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .flatMap((specifier) => {
          const target = resolveTradingModule(path, specifier);
          return target && isInside(target, TRADING_ROOT) ? [target] : [];
        }),
    ]),
  );
  const cycle = dependencyCycle(graph);

  expect(cycle?.map((path) => relative(TRADING_ROOT, path)) ?? []).toEqual([]);
});

test('trading keeps a thin route facade and one query workflow owner', () => {
  const facade = readFileSync(
    resolve(TRADING_ROOT, 'components/trading-page.tsx'),
    'utf8',
  );
  const controller = readFileSync(
    resolve(TRADING_ROOT, 'components/use-trading-page-controller.ts'),
    'utf8',
  );

  expect(facade).toContain('return <TradingWorkspace />');
  expect(facade).not.toMatch(/use[A-Z][A-Za-z]+(?:Query|Mutation)\(/);
  expect(controller).toContain('useManualOrdersQuery(status)');
  expect(controller).not.toMatch(/<(?:section|div|button|form)\b/);
});
