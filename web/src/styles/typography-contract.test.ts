// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const NUMERIC_TYPOGRAPHY_OVERRIDE =
  /text-\[[0-9.]+(?:px|rem)\]|tracking-\[[^\]]+\]|leading-\[[^\]]+\]/g;

// This is a one-way debt ratchet, not the 9.5 certification target. Every
// ceiling may only decrease; certification requires this inventory to be empty.
const NUMERIC_OVERRIDE_CEILINGS: Readonly<Record<string, number>> = {};

const CERTIFIED_CORE_SURFACES = [
  'app/components/workbench/workspace.tsx',
  'app/layout/app-shell.tsx',
  'features/account-truth/components/account-truth-review-page.tsx',
  'features/account/components/overview-cards.tsx',
  'features/backtest/components/backtest-page.tsx',
  'features/decision/components/decision-cockpit-page.tsx',
] as const;

function productionSourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      return productionSourceFiles(path);
    }
    return /\.tsx$/.test(entry) && !/\.test\./.test(entry) ? [path] : [];
  });
}

function numericOverrideCount(path: string): number {
  return (
    readFileSync(path, 'utf8').match(NUMERIC_TYPOGRAPHY_OVERRIDE)?.length ?? 0
  );
}

describe('Karkinos typography certification ratchet', () => {
  it('defines the overline role from semantic typography tokens', () => {
    const css = readFileSync(join(SRC_ROOT, 'styles/globals.css'), 'utf8');
    const overline = css.match(/\.app-type-overline\s*\{[^}]+\}/)?.[0] ?? '';

    expect(overline).toContain('var(--app-font-size-micro)');
    expect(overline).toContain('var(--app-line-height-micro)');
    expect(overline).toContain('var(--app-font-weight-semibold)');
    expect(overline).toContain('var(--app-letter-spacing-overline)');
    expect(overline).toContain('text-transform: uppercase');
  });

  it('keeps certified core surfaces on semantic typography roles', () => {
    const violations = CERTIFIED_CORE_SURFACES.flatMap((file) => {
      const count = numericOverrideCount(join(SRC_ROOT, file));
      return count > 0 ? [{ file, count }] : [];
    });

    expect(violations).toEqual([]);
  });

  it('does not allow numeric typography debt to grow or spread', () => {
    const violations = productionSourceFiles(SRC_ROOT).flatMap((path) => {
      const file = relative(SRC_ROOT, path);
      const count = numericOverrideCount(path);
      const ceiling = NUMERIC_OVERRIDE_CEILINGS[file] ?? 0;
      return count > ceiling ? [{ file, count, ceiling }] : [];
    });

    expect(violations).toEqual([]);
  });
});
