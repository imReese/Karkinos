// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = (path: string) => readFileSync(resolve(SRC_ROOT, path), 'utf8');

const CONTROLLED_OPERATORS = [
  source(
    'features/operations/controlled-broker-write-release-operator-panel.tsx',
  ),
  source('features/operations/current-per-order-dossier-operator-view.tsx'),
  source(
    'features/operations/signed-broker-adapter-release-review-operator-view.tsx',
  ),
].join('\n');

describe('controlled operator register contract', () => {
  it('keeps high-authority review surfaces on flat register boundaries', () => {
    expect(CONTROLLED_OPERATORS).toContain(
      'data-testid="controlled-broker-write-release-panel"',
    );
    expect(CONTROLLED_OPERATORS).toContain(
      'data-testid="current-per-order-dossier-panel"',
    );
    expect(CONTROLLED_OPERATORS).toContain(
      'data-testid="signed-broker-adapter-release-review-panel"',
    );
    expect(CONTROLLED_OPERATORS).toContain(
      'border-y border-[var(--app-divider)]',
    );
    expect(CONTROLLED_OPERATORS).not.toContain('app-terminal-panel');
    expect(CONTROLLED_OPERATORS).not.toContain('app-terminal-inner');
    expect(CONTROLLED_OPERATORS).not.toMatch(/rounded-\[(?:27|28)px\]/);
  });

  it('uses control radius for inputs and buttons instead of action-card shells', () => {
    expect(CONTROLLED_OPERATORS).toContain(
      'rounded-[var(--app-radius-control)]',
    );
    expect(CONTROLLED_OPERATORS).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
  });
});
