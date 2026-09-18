// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = readFileSync(
  resolve(
    SRC_ROOT,
    'features/account-truth/components/account-truth-review-workspace.tsx',
  ),
  'utf8',
);
const evidence = readFileSync(
  resolve(
    SRC_ROOT,
    'features/account-truth/components/account-truth-evidence-sections.tsx',
  ),
  'utf8',
);

test('Account Truth keeps reconciliation primary and evidence maintenance secondary', () => {
  expect(
    workspace.indexOf('<AccountTruthReconciliationWorkspace'),
  ).toBeLessThan(workspace.indexOf('<AccountTruthEvidenceSections'));

  expect(evidence).toContain(
    'data-testid="account-truth-review-evidence-zone"',
  );
  expect(evidence).toContain('data-testid="account-truth-maintenance-zone"');
  expect(evidence).toContain('testId="account-truth-fee-schedule-disclosure"');
  expect(evidence).toContain(
    'id="account-truth-evidence-readiness-disclosure"',
  );
  expect(evidence).toContain('id="account-truth-import-tools"');
  expect(evidence).not.toContain(
    "defaultOpen={readiness.data?.status !== 'ready'}",
  );
  expect(evidence).not.toContain('defaultOpen={scoreNeedsAttention}');
  expect(evidence).not.toContain('defaultOpen={scoreIsMissing}');
});
