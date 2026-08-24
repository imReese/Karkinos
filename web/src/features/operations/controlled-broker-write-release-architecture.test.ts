// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const OPERATIONS_ROOT = dirname(fileURLToPath(import.meta.url));
const ENTRY = resolve(
  OPERATIONS_ROOT,
  'controlled-broker-write-release-operator-panel.tsx',
);
const MODULE_ROOT = resolve(OPERATIONS_ROOT, 'controlled-broker-write-release');
const PRODUCTION_FILES = [ENTRY].concat(
  readdirSync(MODULE_ROOT)
    .filter((name) => name.endsWith('.ts') || name.endsWith('.tsx'))
    .map((name) => resolve(MODULE_ROOT, name)),
);

function functionLineCounts(path: string) {
  const source = readFileSync(path, 'utf8');
  const starts = Array.from(
    source.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{/gs),
  );
  return starts.map((match) => {
    const start = match.index;
    const openingBrace = source.indexOf('{', start);
    let depth = 0;
    let end = openingBrace;
    for (; end < source.length; end += 1) {
      if (source[end] === '{') depth += 1;
      if (source[end] === '}') depth -= 1;
      if (depth === 0) break;
    }
    return {
      name: match[1],
      lines: source.slice(start, end + 1).split('\n').length,
    };
  });
}

test('write-release operator modules have zero oversized module or function debt', () => {
  const oversizedModules = PRODUCTION_FILES.map((path) => ({
    path: relative(OPERATIONS_ROOT, path),
    lines: readFileSync(path, 'utf8').split('\n').length,
  })).filter(({ lines }) => lines > 800);
  const oversizedFunctions = PRODUCTION_FILES.flatMap((path) =>
    functionLineCounts(path)
      .filter(({ lines }) => lines > 350)
      .map(({ name, lines }) => ({
        path: relative(OPERATIONS_ROOT, path),
        name,
        lines,
      })),
  );

  expect(oversizedModules).toEqual([]);
  expect(oversizedFunctions).toEqual([]);
});

test('entry remains a composition layer with one compatible public component', () => {
  const source = readFileSync(ENTRY, 'utf8');

  expect(
    Array.from(
      source.matchAll(/^export function ([A-Za-z_$][\w$]*)/gm),
      (match) => match[1],
    ),
  ).toEqual(['ControlledBrokerWriteReleaseOperatorPanel']);
  expect(source).toContain(
    "from './controlled-broker-write-release/issue-flow'",
  );
  expect(source).toContain(
    "from './controlled-broker-write-release/revocation-flow'",
  );
  expect(source).not.toMatch(
    /useControlledBrokerWriteRelease(?:Approval|Dossier|Issue|Revocation)/,
  );
});

test('exact non-authorizing acknowledgements each have one canonical UI owner', () => {
  const source = PRODUCTION_FILES.map((path) =>
    readFileSync(path, 'utf8'),
  ).join('\n');
  const issueAcknowledgement =
    'issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority';
  const revokeAcknowledgement =
    'revoke_exact_broker_write_release_without_resume_or_broker_action';

  expect(source.split(issueAcknowledgement)).toHaveLength(2);
  expect(source.split(revokeAcknowledgement)).toHaveLength(2);
  expect(source).not.toMatch(
    /useControlledBroker(?:Submission|Cancellation).*Mutation/,
  );
});
