// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const RISK_ROOT = dirname(fileURLToPath(import.meta.url));
const FEATURES_ROOT = resolve(RISK_ROOT, '..');
const APP_ROOT = resolve(RISK_ROOT, '../../app');
const PAGES_ROOT = resolve(RISK_ROOT, 'pages');
const BOUNDARY = resolve(RISK_ROOT, 'risk-feature-boundary.ts');
const ROUTE = resolve(PAGES_ROOT, 'risk-page.tsx');
const CONTROLLER = resolve(RISK_ROOT, 'model/use-risk-page-controller.ts');

function productionFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return productionFiles(path);
    return /\.(?:ts|tsx)$/.test(entry.name) &&
      !/\.(?:test|spec)\.(?:ts|tsx)$/.test(entry.name)
      ? [path]
      : [];
  });
}

function isInside(path: string, directory: string) {
  const fromDirectory = relative(directory, path);
  return (
    fromDirectory === '' ||
    (!fromDirectory.startsWith('..') && !isAbsolute(fromDirectory))
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
  const boundaries = lines.flatMap((line, index) =>
    /^(?:(?:export|declare)\s+)?(?:async\s+)?(?:function|const|let|class|interface|type)\b/.test(
      line,
    )
      ? [index]
      : [],
  );
  return declarations.map(({ name, index }) => ({
    name,
    lines:
      (boundaries.find((boundary) => boundary > index) ?? lines.length) - index,
  }));
}

function resolveRiskModule(importer: string, specifier: string) {
  const files = productionFiles(RISK_ROOT);
  const target = resolve(dirname(importer), specifier);
  return [target, `${target}.ts`, `${target}.tsx`].find((candidate) =>
    files.includes(candidate),
  );
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

test('risk production modules and named functions stay bounded', () => {
  const files = productionFiles(RISK_ROOT);
  expect(
    files
      .map((path) => ({
        path: relative(RISK_ROOT, path),
        lines: readFileSync(path, 'utf8').split(/\r?\n/).length,
      }))
      .filter(({ lines }) => lines > 800),
  ).toEqual([]);
  expect(
    files.flatMap((path) =>
      namedFunctionSpans(path)
        .filter(({ lines }) => lines > 350)
        .map(({ name, lines }) => ({
          path: relative(RISK_ROOT, path),
          name,
          lines,
        })),
    ),
  ).toEqual([]);
});

test('risk keeps cross-feature imports at its explicit boundary', () => {
  const files = productionFiles(RISK_ROOT);
  const appImports = files.flatMap((path) =>
    moduleSpecifiers(path)
      .filter((specifier) => specifier.startsWith('.'))
      .map((specifier) => resolve(dirname(path), specifier))
      .filter((target) => isInside(target, APP_ROOT))
      .map((target) => `${relative(RISK_ROOT, path)} -> ${target}`),
  );
  const crossFeatureImports = files.flatMap((path) =>
    moduleSpecifiers(path)
      .filter((specifier) => specifier.startsWith('.'))
      .map((specifier) => ({
        specifier,
        target: resolve(dirname(path), specifier),
      }))
      .filter(
        ({ target }) =>
          isInside(target, FEATURES_ROOT) && !isInside(target, RISK_ROOT),
      )
      .map(({ specifier }) => ({ path, specifier })),
  );

  expect(appImports).toEqual([]);
  expect(crossFeatureImports.length).toBeGreaterThan(0);
  expect(
    crossFeatureImports
      .filter(
        ({ path, specifier }) =>
          path !== BOUNDARY || specifier.includes('/pages/'),
      )
      .map(
        ({ path, specifier }) => `${relative(RISK_ROOT, path)} -> ${specifier}`,
      ),
  ).toEqual([]);
});

test('risk modules remain acyclic and lower layers avoid pages', () => {
  const files = productionFiles(RISK_ROOT);
  const graph = new Map(
    files.map((path) => [
      path,
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .flatMap((specifier) => {
          const target = resolveRiskModule(path, specifier);
          return target && isInside(target, RISK_ROOT) ? [target] : [];
        }),
    ]),
  );
  const upwardPageImports = files
    .filter((path) => !isInside(path, PAGES_ROOT))
    .flatMap((path) =>
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .map((specifier) => resolve(dirname(path), specifier))
        .filter((target) => isInside(target, PAGES_ROOT)),
    );

  expect(
    dependencyCycle(graph)?.map((path) => relative(RISK_ROOT, path)) ?? [],
  ).toEqual([]);
  expect(upwardPageImports).toEqual([]);
});

test('risk keeps a thin route and one query workflow owner', () => {
  const routeSource = readFileSync(ROUTE, 'utf8');
  const queryOwners = productionFiles(RISK_ROOT)
    .filter((path) =>
      /\buse[A-Z][A-Za-z]+(?:Query|Mutation)\s*\(/.test(
        readFileSync(path, 'utf8'),
      ),
    )
    .map((path) => relative(RISK_ROOT, path));

  expect(routeSource).toContain("createLazyRoute('/risk')");
  expect(routeSource).toContain('<RiskLoadingWorkspace');
  expect(routeSource).toContain('<RiskResolvedWorkspace');
  expect(routeSource).not.toMatch(/\buse[A-Z][A-Za-z]+(?:Query|Mutation)\s*\(/);
  expect(queryOwners).toEqual([relative(RISK_ROOT, CONTROLLER)]);
});
