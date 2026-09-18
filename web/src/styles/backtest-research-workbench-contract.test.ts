// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = (path: string) => readFileSync(resolve(SRC_ROOT, path), 'utf8');

const ADVANCED_RESEARCH = [
  source('features/backtest/components/parameter-sweep-panel.tsx'),
  source('features/backtest/components/parameter-compare-panel.tsx'),
].join('\n');

const SIGNAL_REVIEW = [
  source('features/backtest/components/strategy-signal-preview-panel.tsx'),
  source('features/backtest/components/strategy-preview-results.tsx'),
].join('\n');

describe('backtest research workbench contract', () => {
  it('keeps parameter sweep and compare inside flat advanced-research registers', () => {
    expect(ADVANCED_RESEARCH).toContain('border-y border-[var(--app-divider)]');
    expect(ADVANCED_RESEARCH).toContain('rounded-[var(--app-radius-control)]');
    expect(ADVANCED_RESEARCH).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
    expect(ADVANCED_RESEARCH).not.toContain('active:scale');
  });

  it('keeps signal, risk, paper-shadow, and attribution preview as evidence rows', () => {
    expect(SIGNAL_REVIEW).toContain(
      'data-testid="backtest-signal-preview-register"',
    );
    expect(SIGNAL_REVIEW).toContain('border-y border-[var(--app-divider)]');
    expect(SIGNAL_REVIEW).toContain('border-l-2');
    expect(SIGNAL_REVIEW).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
    expect(SIGNAL_REVIEW).not.toMatch(
      /rounded-(?:xl|2xl|3xl)[^\n]*bg-\[color-mix\(in_srgb,var\(--app-surface-[01]\)/,
    );
  });
});
