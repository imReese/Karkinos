// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const COMPONENT_ROOT = dirname(fileURLToPath(import.meta.url));
const REVIEW_MODULES = [
  'account-truth-broker-evidence-import.tsx',
  'account-truth-citic-batch-preview.ts',
  'account-truth-citic-directory-evidence.tsx',
  'account-truth-citic-file.ts',
  'account-truth-citic-intake-history.tsx',
  'account-truth-citic-preview-result.tsx',
  'account-truth-citic-preview.tsx',
  'account-truth-citic-review.tsx',
  'account-truth-citic-shared-state.ts',
  'account-truth-citic-source-review-form.tsx',
  'account-truth-citic-source-review.ts',
  'account-truth-citic-types.ts',
  'account-truth-evidence-readiness.tsx',
  'account-truth-evidence-sections.tsx',
  'account-truth-reconciliation-workspace.tsx',
  'account-truth-review-format.ts',
  'account-truth-review-labels.en.ts',
  'account-truth-review-labels.ts',
  'account-truth-review-labels.zh.ts',
  'account-truth-review-page.tsx',
  'account-truth-review-state.ts',
  'account-truth-review-workspace.tsx',
  'account-truth-reconciliation-review.tsx',
] as const;

function source(fileName: string) {
  return readFileSync(resolve(COMPONENT_ROOT, fileName), 'utf8');
}

function functionLineCounts(fileName: string) {
  const value = source(fileName);
  const starts = Array.from(
    value.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/g),
  );
  return starts.map((match) => {
    const start = match.index;
    const openingParenthesis = value.indexOf('(', start);
    let parenthesisDepth = 0;
    let closingParenthesis = openingParenthesis;
    for (; closingParenthesis < value.length; closingParenthesis += 1) {
      if (value[closingParenthesis] === '(') parenthesisDepth += 1;
      if (value[closingParenthesis] === ')') parenthesisDepth -= 1;
      if (parenthesisDepth === 0) break;
    }
    const openingBrace = value.indexOf('{', closingParenthesis + 1);
    let depth = 0;
    let end = openingBrace;
    for (; end < value.length; end += 1) {
      if (value[end] === '{') depth += 1;
      if (value[end] === '}') depth -= 1;
      if (depth === 0) break;
    }
    return {
      name: match[1],
      lines: value.slice(start, end + 1).split('\n').length,
    };
  });
}

function localDependencies(fileName: string) {
  return Array.from(
    source(fileName).matchAll(/from ['"]\.\/([^'"]+)['"]/g),
    (match) => match[1],
  )
    .map((dependency) =>
      REVIEW_MODULES.find(
        (candidate) => candidate.replace(/\.[^.]+$/, '') === dependency,
      ),
    )
    .filter((dependency): dependency is (typeof REVIEW_MODULES)[number] =>
      Boolean(dependency),
    );
}

test('Account Truth review has zero oversized production module or function debt', () => {
  const oversizedModules = REVIEW_MODULES.flatMap((fileName) => {
    const lineCount = source(fileName).split('\n').length;
    return lineCount > 800 ? [`${fileName}: ${lineCount}`] : [];
  });
  const oversizedFunctions = REVIEW_MODULES.flatMap((fileName) =>
    functionLineCounts(fileName)
      .filter(({ lines }) => lines > 350)
      .map(({ name, lines }) => `${fileName}: ${name} (${lines})`),
  );

  expect(oversizedModules).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
});

test('Account Truth review modules keep an acyclic local dependency graph', () => {
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const cycles: string[] = [];

  function visit(fileName: (typeof REVIEW_MODULES)[number], path: string[]) {
    if (visiting.has(fileName)) {
      cycles.push([...path, fileName].join(' -> '));
      return;
    }
    if (visited.has(fileName)) return;
    visiting.add(fileName);
    for (const dependency of localDependencies(fileName)) {
      visit(dependency, [...path, fileName]);
    }
    visiting.delete(fileName);
    visited.add(fileName);
  }

  for (const fileName of REVIEW_MODULES) visit(fileName, []);
  expect(cycles).toEqual([]);
});

test('Account Truth review keeps a thin public page and isolated query owner', () => {
  expect(source('account-truth-review-page.tsx').trim()).toBe(
    "export { AccountTruthReviewPage } from './account-truth-review-workspace';",
  );

  const workspace = source('account-truth-review-workspace.tsx');
  expect(workspace).toContain('useAccountTruthReviewState(locale)');
  expect(workspace).toContain('<AccountTruthReconciliationWorkspace');
  expect(workspace).toContain('<AccountTruthEvidenceSections');
  expect(workspace).not.toContain("from '../api'");

  const state = source('account-truth-review-state.ts');
  expect(state).toContain("from '../api'");
  expect(state).not.toMatch(/<(?:section|div|button|form)\b/);
});
