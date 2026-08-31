// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const LAYOUT_ROOT = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = resolve(LAYOUT_ROOT, '../..');
const FEATURES_ROOT = resolve(SRC_ROOT, 'features');
const FACADE = resolve(LAYOUT_ROOT, 'app-shell.tsx');
const FEATURE_BOUNDARY = resolve(LAYOUT_ROOT, 'app-shell-feature-boundary.ts');

type Layer =
  | 'composition'
  | 'controller'
  | 'feature-boundary'
  | 'model'
  | 'primitive'
  | 'view';

const FILE_LAYERS: Readonly<Record<string, Layer>> = {
  'app-shell-feature-boundary.ts': 'feature-boundary',
  'app-shell-icons.tsx': 'primitive',
  'app-shell-mobile-navigation.tsx': 'view',
  'app-shell-navigation-config.ts': 'model',
  'app-shell-preferences.tsx': 'view',
  'app-shell-sidebar.tsx': 'view',
  'app-shell-status-model.ts': 'model',
  'app-shell-status.tsx': 'view',
  'app-shell-toolbar.tsx': 'view',
  'app-shell.tsx': 'composition',
  'use-app-shell-controller.ts': 'controller',
  'use-toolbar-status-controller.ts': 'controller',
  'workspace-command-menu.tsx': 'view',
};

const ALLOWED_LOCAL_DEPENDENCIES: Readonly<Record<Layer, Layer[]>> = {
  composition: ['controller', 'view'],
  controller: ['controller', 'feature-boundary', 'model'],
  'feature-boundary': [],
  model: ['model', 'primitive'],
  primitive: [],
  view: ['model', 'primitive', 'view'],
};

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
    /\b(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/g;
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

function resolveLayoutModule(
  files: string[],
  importer: string,
  specifier: string,
) {
  const target = resolve(dirname(importer), specifier);
  return [
    target,
    `${target}.ts`,
    `${target}.tsx`,
    resolve(target, 'index.ts'),
    resolve(target, 'index.tsx'),
  ].find((candidate) => files.includes(candidate));
}

function resolveSourceTarget(importer: string, specifier: string) {
  if (specifier.startsWith('.')) {
    return resolve(dirname(importer), specifier);
  }
  if (specifier.startsWith('@/')) {
    return resolve(SRC_ROOT, specifier.slice(2));
  }
  return null;
}

function dependencyCycle(graph: Map<string, string[]>) {
  const state = new Map<string, 'visiting' | 'visited'>();
  const stack: string[] = [];
  const visit = (node: string): string[] | null => {
    if (state.get(node) === 'visiting') {
      return [...stack.slice(stack.indexOf(node)), node];
    }
    if (state.get(node) === 'visited') {
      return null;
    }
    state.set(node, 'visiting');
    stack.push(node);
    for (const target of graph.get(node) ?? []) {
      const cycle = visit(target);
      if (cycle) {
        return cycle;
      }
    }
    stack.pop();
    state.set(node, 'visited');
    return null;
  };
  for (const node of graph.keys()) {
    const cycle = visit(node);
    if (cycle) {
      return cycle;
    }
  }
  return null;
}

test('app shell production modules and named functions stay bounded', () => {
  const files = productionFiles(LAYOUT_ROOT);
  const oversizedFiles = files
    .map((path) => ({
      path: relative(LAYOUT_ROOT, path),
      lines: readFileSync(path, 'utf8').split(/\r?\n/).length,
    }))
    .filter(({ lines }) => lines > 800);
  const oversizedFunctions = files.flatMap((path) =>
    namedFunctionSpans(path)
      .filter(({ lines }) => lines > 350)
      .map(({ name, lines }) => ({
        path: relative(LAYOUT_ROOT, path),
        name,
        lines,
      })),
  );
  const appShellSpan = namedFunctionSpans(FACADE).find(
    ({ name }) => name === 'AppShell',
  );

  expect(oversizedFiles).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
  expect(appShellSpan?.lines ?? Infinity).toBeLessThanOrEqual(180);
});

test('app shell keeps explicit one-way ownership and no local cycles', () => {
  const files = productionFiles(LAYOUT_ROOT);
  const relativeFiles = files.map((path) => relative(LAYOUT_ROOT, path)).sort();
  const graph = new Map(
    files.map((path) => [
      path,
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .flatMap((specifier) => {
          const target = resolveLayoutModule(files, path, specifier);
          return target ? [target] : [];
        }),
    ]),
  );
  const layerViolations = Array.from(graph).flatMap(([source, targets]) =>
    targets.flatMap((target) => {
      const sourceFile = relative(LAYOUT_ROOT, source);
      const targetFile = relative(LAYOUT_ROOT, target);
      const sourceLayer = FILE_LAYERS[sourceFile];
      const targetLayer = FILE_LAYERS[targetFile];
      return sourceLayer &&
        targetLayer &&
        ALLOWED_LOCAL_DEPENDENCIES[sourceLayer].includes(targetLayer)
        ? []
        : [`${sourceFile} (${sourceLayer}) -> ${targetFile} (${targetLayer})`];
    }),
  );
  const facadeImports = files
    .filter((path) => path !== FACADE)
    .flatMap((path) =>
      (graph.get(path) ?? [])
        .filter((target) => target === FACADE)
        .map(
          (target) =>
            `${relative(LAYOUT_ROOT, path)} -> ${relative(LAYOUT_ROOT, target)}`,
        ),
    );

  expect(relativeFiles).toEqual(Object.keys(FILE_LAYERS).sort());
  expect(layerViolations).toEqual([]);
  expect(
    dependencyCycle(graph)?.map((path) => relative(LAYOUT_ROOT, path)) ?? [],
  ).toEqual([]);
  expect(facadeImports).toEqual([]);
});

test('app shell isolates feature integration behind one named boundary', () => {
  const files = productionFiles(LAYOUT_ROOT);
  const featureImports = files
    .flatMap((path) =>
      moduleSpecifiers(path)
        .map((specifier) => ({
          path,
          specifier,
          target: resolveSourceTarget(path, specifier),
        }))
        .filter(
          ({ target }) => target !== null && isInside(target, FEATURES_ROOT),
        ),
    )
    .map(
      ({ path, specifier }) => `${relative(LAYOUT_ROOT, path)} -> ${specifier}`,
    )
    .sort();
  const reverseImports = productionFiles(FEATURES_ROOT).flatMap((path) =>
    moduleSpecifiers(path)
      .map((specifier) => resolveSourceTarget(path, specifier))
      .filter(
        (target): target is string =>
          target !== null && isInside(target, LAYOUT_ROOT),
      )
      .map(
        (target) =>
          `${relative(FEATURES_ROOT, path)} -> ${relative(LAYOUT_ROOT, target)}`,
      ),
  );

  expect(featureImports).toEqual([
    'app-shell-feature-boundary.ts -> ../../features/account/api',
    'app-shell-feature-boundary.ts -> ../../features/market/api',
  ]);
  expect(moduleSpecifiers(FEATURE_BOUNDARY)).not.toContain('./app-shell');
  expect(reverseImports).toEqual([]);
});

test('app shell keeps one thin facade and one owner per workflow', () => {
  const files = productionFiles(LAYOUT_ROOT);
  const facadeSource = readFileSync(FACADE, 'utf8');
  const owners = (pattern: RegExp) =>
    files
      .filter((path) => pattern.test(readFileSync(path, 'utf8')))
      .map((path) => relative(LAYOUT_ROOT, path))
      .sort();
  const controllers = files.filter(
    (path) => FILE_LAYERS[relative(LAYOUT_ROOT, path)] === 'controller',
  );
  const controllerJsx = controllers.flatMap((path) =>
    /<(?:aside|button|div|header|main|nav|section)\b/.test(
      readFileSync(path, 'utf8'),
    )
      ? [relative(LAYOUT_ROOT, path)]
      : [],
  );

  expect(facadeSource).toContain('export function AppShell');
  expect(facadeSource).toContain('useAppShellController()');
  expect(facadeSource).not.toMatch(
    /\b(?:useEffect|useLayoutEffect|usePreferences|useRef|useRouterState|useState)\b/,
  );
  expect(facadeSource).not.toMatch(/\b(?:window|document)\b/);
  expect(facadeSource).not.toMatch(/\buse[A-Z][A-Za-z]+Query\s*\(/);
  expect(controllerJsx).toEqual([]);
  expect(owners(/\buseRouterState\s*\(/)).toEqual([
    'use-app-shell-controller.ts',
  ]);
  expect(owners(/\busePreferences\s*\(/)).toEqual([
    'use-app-shell-controller.ts',
  ]);
  expect(owners(/\buseCopy\s*\(/)).toEqual(['use-app-shell-controller.ts']);
  expect(owners(/\buse[A-Z][A-Za-z]+Query\s*\(/)).toEqual([
    'use-toolbar-status-controller.ts',
  ]);
});

test('app shell keeps fail-closed query enablement and canonical models', () => {
  const statusController = readFileSync(
    resolve(LAYOUT_ROOT, 'use-toolbar-status-controller.ts'),
    'utf8',
  );
  const statusModel = readFileSync(
    resolve(LAYOUT_ROOT, 'app-shell-status-model.ts'),
    'utf8',
  );
  const files = productionFiles(LAYOUT_ROOT);
  const declarationOwners = (name: string) =>
    files
      .filter((path) =>
        new RegExp(`\\b(?:const|function)\\s+${name}\\b`).test(
          readFileSync(path, 'utf8'),
        ),
      )
      .map((path) => relative(LAYOUT_ROOT, path));
  const navigationRouteOwners = files
    .filter((path) =>
      /['"]\/(?:activity|ai-research|backtest|decision|market|operations|overview|portfolio|risk|settings|trading)['"]/.test(
        readFileSync(path, 'utf8'),
      ),
    )
    .map((path) => relative(LAYOUT_ROOT, path));

  expect(statusController).toContain(
    'statusRailVisible || openStatusPanel !== null',
  );
  expect(statusController).toContain(
    'useAccountOverviewQuery(statusQueriesEnabled)',
  );
  expect(statusController).toContain(
    'useMarketDataHealthQuery(statusQueriesEnabled)',
  );
  expect(statusModel).not.toMatch(/\bfrom ['"]react['"]/);
  expect(statusModel).not.toContain('/features/');
  expect(statusModel).not.toMatch(/return\s*\(\s*<[A-Za-z]/);
  expect(declarationOwners('formatToolbarTimestamp')).toEqual([
    'app-shell-status-model.ts',
  ]);
  expect(declarationOwners('NAVIGATION_GROUPS')).toEqual([
    'app-shell-navigation-config.ts',
  ]);
  expect(declarationOwners('MOBILE_PRIMARY_ITEMS')).toEqual([
    'app-shell-navigation-config.ts',
  ]);
  expect(declarationOwners('isNavigationItemActive')).toEqual([
    'app-shell-navigation-config.ts',
  ]);
  expect(navigationRouteOwners).toEqual(['app-shell-navigation-config.ts']);
});
