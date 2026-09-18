// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const resolved = readFileSync(
  resolve(SRC_ROOT, 'features/risk/components/risk-resolved-workspace.tsx'),
  'utf8',
);
const command = readFileSync(
  resolve(SRC_ROOT, 'features/risk/components/risk-command-workspace.tsx'),
  'utf8',
);
const control = readFileSync(
  resolve(
    SRC_ROOT,
    'features/risk/components/risk-controlled-action-disclosure.tsx',
  ),
  'utf8',
);

function requiredIndex(source: string, fragment: string) {
  const index = source.indexOf(fragment);
  expect(index).toBeGreaterThanOrEqual(0);
  return index;
}

test('risk keeps canonical facts separate from controlled action', () => {
  const exceptions = requiredIndex(resolved, '<RiskCommandWorkspace');
  const thresholds = requiredIndex(resolved, '<RiskThresholdEvidence');
  const controlled = requiredIndex(resolved, '<RiskControlledActionDisclosure');
  const handoff = requiredIndex(resolved, '<RiskDecisionHandoff');
  const structure = requiredIndex(resolved, '<RiskAnalysisDisclosure');

  expect(exceptions).toBeLessThan(thresholds);
  expect(thresholds).toBeLessThan(controlled);
  expect(controlled).toBeLessThan(handoff);
  expect(handoff).toBeLessThan(structure);
  expect(command).not.toContain('<MetricStrip');
  expect(command).not.toContain('risk-metric-rail');
  expect(control).toContain('data-testid="risk-controlled-action-disclosure"');
  expect(control).toContain('<KillSwitchPanel');
});
