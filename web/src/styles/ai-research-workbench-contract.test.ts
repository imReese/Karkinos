// @ts-nocheck -- deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const WORKSPACE = readFileSync(
  resolve(
    SRC_ROOT,
    'features/ai-research/components/shadow-research-candidate-workspace.tsx',
  ),
  'utf8',
);
const VIEW = readFileSync(
  resolve(SRC_ROOT, 'features/ai-research/components/shadow-research-view.tsx'),
  'utf8',
);

describe('AI research workbench contract', () => {
  it('uses a candidate registry plus one selected evidence inspector', () => {
    expect(WORKSPACE).toContain(
      'data-testid="shadow-research-candidate-workspace"',
    );
    expect(WORKSPACE).toContain(
      'data-testid="shadow-research-current-registry"',
    );
    expect(WORKSPACE).toContain(
      'data-testid="shadow-research-candidate-inspector"',
    );
    expect(WORKSPACE).toContain('data-testid="shadow-research-candidate-row"');
    expect(WORKSPACE).not.toContain('current.map(renderCandidate)');
    expect(WORKSPACE).not.toContain('historical.map(renderCandidate)');
    expect(VIEW).toContain('data-testid="shadow-research-candidate"');
    expect(VIEW).not.toContain(
      'rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] p-4',
    );
  });
});
