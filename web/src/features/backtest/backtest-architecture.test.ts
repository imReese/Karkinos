// @ts-nocheck -- Node and TypeScript compiler APIs are used for source audits.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const BACKTEST_ROOT = dirname(fileURLToPath(import.meta.url));
const FEATURES_ROOT = resolve(BACKTEST_ROOT, '..');
const APP_ROOT = resolve(BACKTEST_ROOT, '../../app');
const API_FACADE = resolve(BACKTEST_ROOT, 'api.ts');
const API_CONTRACTS = resolve(BACKTEST_ROOT, 'api-contracts.ts');
const API_GOVERNANCE_CONTRACTS = resolve(
  BACKTEST_ROOT,
  'api-governance-contracts.ts',
);
const API_HOOKS = resolve(BACKTEST_ROOT, 'api-hooks.ts');

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

function resolveBacktestModule(importer: string, specifier: string) {
  const target = resolve(dirname(importer), specifier);
  const candidates = [
    target,
    `${target}.ts`,
    `${target}.tsx`,
    resolve(target, 'index.ts'),
    resolve(target, 'index.tsx'),
  ];
  return candidates.find((candidate) =>
    productionFiles(BACKTEST_ROOT).includes(candidate),
  );
}

function dependencyCycle(graph: Map<string, string[]>) {
  const state = new Map<string, 'visiting' | 'visited'>();
  const stack: string[] = [];
  const visit = (node: string): string[] | null => {
    if (state.get(node) === 'visiting') {
      const cycleStart = stack.indexOf(node);
      return [...stack.slice(cycleStart), node];
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

const PUBLIC_API_EXPORTS = `
AcceptanceAuditCriterion
AcceptanceAuditExport
AcceptanceAuditSummary
AccountStrategyAssignment
AccountStrategyAssignmentUpdate
AccountStrategyAttributionSummary
AccountStrategyContributionReport
AfterCostEvidence
BacktestAttributionPreviewRequest
BacktestAttributionPreviewResponse
BacktestCompareRequest
BacktestCompareResponse
BacktestCompareResult
BacktestCompareRunRequest
BacktestEquityPoint
BacktestFill
BacktestMetrics
BacktestPaperShadowPreviewRequest
BacktestPaperShadowPreviewResponse
BacktestReport
BacktestRiskPreviewRequest
BacktestRiskPreviewResponse
BacktestRunRequest
BacktestStrategyInfo
BacktestSummary
BacktestSweepRequest
BacktestSweepResponse
BacktestSweepResult
CostSummary
DatasetQuality
DatasetQualityIssue
DatasetSnapshot
DatasetSnapshotSymbol
OutOfSampleValidation
StrategyLearningResearchHandoff
StrategyLearningReviewItem
StrategyLearningReviewQueue
StrategyMetadataSnapshot
StrategyParameterSchema
StrategyPromotionReadiness
StrategyPromotionReadinessRow
StrategySignalPreviewOutput
StrategySignalPreviewRequest
StrategySignalPreviewResponse
StrategyValidationMatrix
StrategyValidationRow
ValidationSegmentEvidence
useAccountStrategyAssignmentQuery
useAccountStrategyAssignmentsQuery
useAccountStrategyAttributionQuery
useAccountStrategyContributionQuery
useBacktestAttributionPreviewMutation
useBacktestPaperShadowPreviewMutation
useBacktestResultQuery
useBacktestResultsQuery
useBacktestRiskPreviewMutation
useBacktestStrategiesQuery
useRunBacktestCompareMutation
useRunBacktestMutation
useRunBacktestSweepMutation
useSingleInstrumentStrategyLoopAcceptanceAuditQuery
useStrategyLearningReviewQuery
useStrategyPromotionReadinessQuery
useStrategySignalPreviewMutation
useStrategyValidationQuery
useUpdateAccountStrategyAssignmentMutation
useUpdateScopedAccountStrategyAssignmentMutation
`
  .trim()
  .split('\n')
  .sort();

test('backtest production modules and named functions stay bounded', () => {
  const files = productionFiles(BACKTEST_ROOT);
  const oversizedFiles = files
    .map((path) => ({
      path: relative(BACKTEST_ROOT, path),
      lines: readFileSync(path, 'utf8').split(/\r?\n/).length,
    }))
    .filter(({ lines }) => lines > 800);
  const oversizedFunctions = files.flatMap((path) =>
    namedFunctionSpans(path)
      .filter(({ lines }) => lines > 350)
      .map(({ name, lines }) => ({
        path: relative(BACKTEST_ROOT, path),
        name,
        lines,
      })),
  );

  expect(oversizedFiles).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
});

test('backtest imports stay out of app and at the reviewed feature boundary', () => {
  const files = productionFiles(BACKTEST_ROOT);
  const appImports = files.flatMap((path) =>
    moduleSpecifiers(path)
      .filter((specifier) => specifier.startsWith('.'))
      .map((specifier) => resolve(dirname(path), specifier))
      .filter((target) => isInside(target, APP_ROOT))
      .map(
        (target) =>
          `${relative(BACKTEST_ROOT, path)} -> ${relative(APP_ROOT, target)}`,
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
            isInside(target, FEATURES_ROOT) && !isInside(target, BACKTEST_ROOT),
        )
        .map(
          ({ specifier }) => `${relative(BACKTEST_ROOT, path)} -> ${specifier}`,
        ),
    )
    .sort();

  expect(appImports).toEqual([]);
  expect(featureImports).toEqual([
    'backtest-feature-boundary.ts -> ../account-strategy/api',
    'backtest-feature-boundary.ts -> ../account-strategy/attribution-readiness',
    'backtest-feature-boundary.ts -> ../research-workflow/components/research-task-panel',
    'backtest-feature-boundary.ts -> ../research-workflow/components/strategy-hypothesis-panel',
  ]);
});

test('backtest production modules remain acyclic', () => {
  const files = productionFiles(BACKTEST_ROOT);
  const graph = new Map(
    files.map((path) => [
      path,
      moduleSpecifiers(path)
        .filter((specifier) => specifier.startsWith('.'))
        .flatMap((specifier) => {
          const target = resolveBacktestModule(path, specifier);
          return target && isInside(target, BACKTEST_ROOT) ? [target] : [];
        }),
    ]),
  );
  const cycle = dependencyCycle(graph);

  expect(cycle?.map((path) => relative(BACKTEST_ROOT, path)) ?? []).toEqual([]);
});

test('backtest API facade preserves its public export surface', () => {
  expect(readFileSync(API_FACADE, 'utf8').trim().split('\n')).toEqual([
    "export * from './api-contracts';",
    "export * from './api-hooks';",
  ]);
  const exportPattern = /^export (?:type|function) ([A-Za-z0-9_]+)/gm;
  const actualExports = [API_CONTRACTS, API_GOVERNANCE_CONTRACTS, API_HOOKS]
    .flatMap((path) =>
      Array.from(
        readFileSync(path, 'utf8').matchAll(exportPattern),
        (match) => match[1],
      ),
    )
    .sort();

  expect(actualExports).toEqual(PUBLIC_API_EXPORTS);
});

test('backtest request URLs stay at the reviewed contract', () => {
  const source = productionFiles(BACKTEST_ROOT)
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n');
  const urls = Array.from(
    source.matchAll(/['"`]((?:\/api\/)[^'"`]*)['"`]/g),
    (match) => match[1],
  ).sort();

  expect(urls).toEqual(
    [
      '/api/acceptance-audits/single_instrument_strategy_loop',
      '/api/account-strategy',
      '/api/account-strategy',
      '/api/account-strategy/assignments',
      '/api/account-strategy/assignments',
      '/api/account-strategy/attribution',
      '/api/account-strategy/contribution',
      '/api/backtest/attribution-preview',
      '/api/backtest/compare',
      '/api/backtest/paper-shadow-preview',
      '/api/backtest/results',
      '/api/backtest/results/${resultId}',
      '/api/backtest/risk-preview',
      '/api/backtest/run',
      '/api/backtest/signal-preview',
      '/api/backtest/strategies',
      '/api/backtest/strategy-promotion-readiness',
      '/api/backtest/strategy-validation',
      '/api/backtest/sweep',
      '/api/portfolio',
      '/api/strategy-learning/review-queue',
    ].sort(),
  );
});

test('backtest query and invalidation keys stay at the reviewed contract', () => {
  const source = [
    readFileSync(API_HOOKS, 'utf8'),
    readFileSync(
      resolve(BACKTEST_ROOT, 'components/backtest-portfolio-query.ts'),
      'utf8',
    ),
  ].join('\n');
  const queryKeys = Array.from(
    source.matchAll(/queryKey:\s*(\[[^\]]+\])/g),
    (match) => match[1].replace(/\s+/g, ' '),
  ).sort();

  expect(queryKeys).toEqual(
    [
      "['acceptance-audit', 'single_instrument_strategy_loop']",
      "['account-strategy-assignment']",
      "['account-strategy-assignments']",
      "['account-strategy-assignments']",
      "['account-strategy-attribution']",
      "['account-strategy-attribution']",
      "['account-strategy-attribution']",
      "['account-strategy-contribution']",
      "['account-strategy-contribution']",
      "['account-strategy-contribution']",
      "['backtest-result', report.id]",
      "['backtest-result', resultId]",
      "['backtest-results']",
      "['backtest-results']",
      "['backtest-portfolio-instruments']",
      "['backtest-results']",
      "['backtest-results']",
      "['backtest-strategies']",
      "['backtest-strategy-promotion-readiness']",
      "['backtest-strategy-validation']",
      "['strategy-learning-review']",
    ].sort(),
  );
});
