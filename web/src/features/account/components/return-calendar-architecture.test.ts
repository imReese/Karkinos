// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { basename, dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const COMPONENTS_ROOT = dirname(fileURLToPath(import.meta.url));
const ACCOUNT_ROOT = resolve(COMPONENTS_ROOT, '..');
const FEATURES_ROOT = resolve(ACCOUNT_ROOT, '..');
const APP_ROOT = resolve(ACCOUNT_ROOT, '../../app');
const FACADE = resolve(COMPONENTS_ROOT, 'return-calendar-card.tsx');
const CONTROLLER = resolve(
  COMPONENTS_ROOT,
  'use-return-calendar-controller.ts',
);

function calendarFiles() {
  return readdirSync(COMPONENTS_ROOT)
    .filter(
      (name) =>
        (/^return-calendar-.+\.(?:ts|tsx)$/.test(name) ||
          name === 'use-return-calendar-controller.ts') &&
        !/\.(?:test|spec)\.(?:ts|tsx)$/.test(name),
    )
    .map((name) => resolve(COMPONENTS_ROOT, name));
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

function resolveCalendarModule(importer: string, specifier: string) {
  const files = calendarFiles();
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

test('return calendar modules and named functions stay bounded', () => {
  const files = calendarFiles();
  expect(files.length).toBeGreaterThan(5);
  expect(
    files
      .map((path) => ({
        path: basename(path),
        lines: readFileSync(path, 'utf8').split(/\r?\n/).length,
      }))
      .filter(({ lines }) => lines > 800),
  ).toEqual([]);
  expect(
    files.flatMap((path) =>
      namedFunctionSpans(path)
        .filter(({ lines }) => lines > 350)
        .map(({ name, lines }) => ({ path: basename(path), name, lines })),
    ),
  ).toEqual([]);
});

test('return calendar stays account-owned and feature-independent', () => {
  const violations = calendarFiles().flatMap((path) =>
    moduleSpecifiers(path)
      .filter((specifier) => specifier.startsWith('.'))
      .map((specifier) => ({
        specifier,
        target: resolve(dirname(path), specifier),
      }))
      .filter(
        ({ target }) =>
          isInside(target, APP_ROOT) ||
          (isInside(target, FEATURES_ROOT) && !isInside(target, ACCOUNT_ROOT)),
      )
      .map(({ specifier }) => `${basename(path)} -> ${specifier}`),
  );

  expect(violations).toEqual([]);
});

test('return calendar modules remain acyclic', () => {
  const files = calendarFiles();
  const graph = new Map(
    files.map((path) => [
      path,
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .flatMap((specifier) => {
          const target = resolveCalendarModule(path, specifier);
          return target ? [target] : [];
        }),
    ]),
  );

  expect(dependencyCycle(graph)?.map((path) => basename(path)) ?? []).toEqual(
    [],
  );
});

test('return calendar keeps one facade and one controller', () => {
  const facadeSource = readFileSync(FACADE, 'utf8');
  const stateOwners = calendarFiles()
    .filter((path) =>
      /\buseState(?:<[^;\n]+>)?\s*\(/.test(readFileSync(path, 'utf8')),
    )
    .map((path) => basename(path))
    .sort();

  expect(facadeSource).toContain('export function ReturnCalendarCard');
  expect(facadeSource).toContain('useReturnCalendarController');
  expect(readFileSync(CONTROLLER, 'utf8')).toContain(
    'export function useReturnCalendarController',
  );
  expect(stateOwners).toEqual([
    'return-calendar-supporting-views.tsx',
    'use-return-calendar-controller.ts',
  ]);
});
