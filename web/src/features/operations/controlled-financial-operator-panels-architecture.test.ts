// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const OPERATIONS_ROOT = dirname(fileURLToPath(import.meta.url));
const FAMILY_STEMS = [
  'controlled-ledger-correction-operator',
  'controlled-ledger-posting-operator',
  'controlled-terminal-clearance-operator',
  'current-per-order-dossier-operator',
];
const FAMILY_FILES = FAMILY_STEMS.flatMap((stem) => [
  resolve(OPERATIONS_ROOT, `${stem}-panel.tsx`),
  resolve(OPERATIONS_ROOT, `${stem}-model.ts`),
  resolve(OPERATIONS_ROOT, `${stem}-controller.ts`),
  resolve(OPERATIONS_ROOT, `${stem}-view.tsx`),
]);
const PRODUCTION_FILES = [
  resolve(OPERATIONS_ROOT, 'controlled-operation-panel-primitives.tsx'),
  ...FAMILY_FILES,
];

function functionLineCounts(path: string) {
  const source = readFileSync(path, 'utf8');
  const starts = Array.from(
    source.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{/gs),
  );
  return starts.map((match) => {
    const start = match.index;
    const openingBrace = start + match[0].lastIndexOf('{');
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

test('controlled financial operator panels have zero oversized module or function debt', () => {
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

test('compatible panel entries remain composition-only facades', () => {
  const expectedExports = [
    'ControlledLedgerCorrectionOperatorPanel',
    'ControlledLedgerPostingOperatorPanel',
    'ControlledTerminalClearanceOperatorPanel',
    'CurrentPerOrderDossierOperatorPanel',
  ];

  FAMILY_STEMS.forEach((stem, index) => {
    const source = readFileSync(
      resolve(OPERATIONS_ROOT, `${stem}-panel.tsx`),
      'utf8',
    );
    expect(
      Array.from(
        source.matchAll(/^export function ([A-Za-z_$][\w$]*)/gm),
        (match) => match[1],
      ),
    ).toEqual([expectedExports[index]]);
    expect(source).toContain(`from './${stem}-controller'`);
    expect(source).toContain(`from './${stem}-model'`);
    expect(source).toContain(`from './${stem}-view'`);
    expect(source).not.toMatch(/from '\.\/api'|\.mutate\(|\buseState\b/);
  });
});

test('models and views cannot own request orchestration', () => {
  const modelSources = FAMILY_STEMS.map((stem) =>
    readFileSync(resolve(OPERATIONS_ROOT, `${stem}-model.ts`), 'utf8'),
  );
  const viewSources = FAMILY_STEMS.map((stem) =>
    readFileSync(resolve(OPERATIONS_ROOT, `${stem}-view.tsx`), 'utf8'),
  );

  modelSources.forEach((source) => {
    expect(source).not.toMatch(
      /from 'react'|\.mutate\(|\buse[A-Za-z_$][\w$]*(?:Mutation|Query)\b/,
    );
  });
  viewSources.forEach((source) => {
    expect(source).not.toMatch(
      /from '\.\/api'|\.mutate\(|\buseState\b|\buse[A-Za-z_$][\w$]*(?:Mutation|Query)\b/,
    );
  });
});

test('exact acknowledgements retain one controller owner and no broker command authority', () => {
  const source = PRODUCTION_FILES.map((path) =>
    readFileSync(path, 'utf8'),
  ).join('\n');
  const acknowledgements = [
    'apply_exact_compensating_ledger_correction_once',
    'apply_exact_reconciled_ledger_posting_once',
    'clear_exact_terminal_outcome_without_automatic_ledger_mutation',
    'confirm_exact_non_submitting_dossier_for_review',
  ];

  acknowledgements.forEach((acknowledgement) => {
    expect(source.split(acknowledgement)).toHaveLength(2);
  });
  expect(source).not.toMatch(
    /useControlledBroker(?:Submission|Cancellation|WriteRelease).*Mutation/,
  );
});

test('manual-control and non-authorizing view contracts remain explicit', () => {
  const views = FAMILY_STEMS.map((stem) =>
    readFileSync(resolve(OPERATIONS_ROOT, `${stem}-view.tsx`), 'utf8'),
  ).join('\n');

  expect(views).toContain('data-testid="controlled-ledger-correction-review"');
  expect(views).toContain('data-testid="current-per-order-dossier-panel"');
  expect(views).toContain(
    'I confirm appending only the exact previewed compensation once; the original ledger history must remain.',
  );
  expect(views).toContain(
    'I confirm applying only the ${preview.data?.ledger_entry_count ?? 0} previewed reconciled ledger event(s), once.',
  );
  expect(views).toContain('this step does not post the production ledger.');
  expect(views).toContain(
    'It is not a broker instruction and cannot restore or expand authority.',
  );
});
