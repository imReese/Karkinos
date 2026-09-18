// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = (path: string) => readFileSync(resolve(SRC_ROOT, path), 'utf8');

const ACCOUNT_STRATEGY = [
  source('features/backtest/components/account-strategy-panel.tsx'),
  source('features/backtest/components/account-strategy-evidence.tsx'),
].join('\n');

const LEARNING = source(
  'features/backtest/components/strategy-learning-review-panel.tsx',
);
const EVIDENCE_GATE = source(
  'features/backtest/components/strategy-evidence-gate-panel.tsx',
);

describe('backtest evidence register contract', () => {
  it('keeps account strategy evidence on a flat register surface', () => {
    expect(ACCOUNT_STRATEGY).toContain(
      'data-testid="backtest-account-strategy-register"',
    );
    expect(ACCOUNT_STRATEGY).toContain('border-y border-[var(--app-divider)]');
    expect(ACCOUNT_STRATEGY).not.toContain('app-terminal-panel');
    expect(ACCOUNT_STRATEGY).not.toContain('app-terminal-inner');
    expect(ACCOUNT_STRATEGY).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
  });

  it('renders reviewed learning evidence as a ledger-like queue', () => {
    expect(LEARNING).toContain(
      'data-testid="strategy-learning-review-register"',
    );
    expect(LEARNING).toContain('divide-y divide-[var(--app-divider)] border-y');
    expect(LEARNING).not.toContain('app-terminal-panel');
    expect(LEARNING).not.toContain('app-terminal-inner');
    expect(LEARNING).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
  });

  it('keeps the strategy evidence gate as a compact matrix register', () => {
    expect(EVIDENCE_GATE).toContain(
      'data-testid="strategy-evidence-gate-register"',
    );
    expect(EVIDENCE_GATE).toContain('min-w-[1060px] table-fixed');
    expect(EVIDENCE_GATE).not.toContain('app-workbench-section');
    expect(EVIDENCE_GATE).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
  });
});
