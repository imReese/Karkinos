// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { APP_MOTION } from '../app/motion';

const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const GLOBALS_PATH = join(SRC_ROOT, 'styles', 'globals.css');
const GLOBALS = readFileSync(GLOBALS_PATH, 'utf8');

function sourceFiles(root: string): string[] {
  return readdirSync(root).flatMap((entry) => {
    const path = join(root, entry);
    if (statSync(path).isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(css|ts|tsx)$/.test(entry) && !/\.test\./.test(entry)
      ? [path]
      : [];
  });
}

describe('Karkinos brand motion contract', () => {
  it('declares the semantic duration, easing, distance, and stagger layers', () => {
    const requiredTokens = [
      '--app-motion-instant: 80ms',
      '--app-motion-fast: 120ms',
      '--app-motion-standard: 180ms',
      '--app-motion-deliberate: 240ms',
      '--app-motion-route: 320ms',
      '--app-motion-loading: 1600ms',
      '--app-motion-spin: 900ms',
      '--app-motion-stagger: 36ms',
      '--app-motion-distance-xs: 2px',
      '--app-motion-distance-sm: 6px',
      '--app-motion-distance-md: 12px',
      '--app-space-section: 24px',
      '--app-space-section-relaxed: 32px',
      '--app-ease-standard: cubic-bezier(0.2, 0, 0, 1)',
      '--app-ease-enter: cubic-bezier(0.16, 1, 0.3, 1)',
      '--app-ease-exit: cubic-bezier(0.4, 0, 1, 1)',
    ];

    for (const token of requiredTokens) {
      expect(GLOBALS).toContain(token);
    }
    expect(APP_MOTION.chartDurationMs).toBe(320);
  });

  it('keeps one deterministic reduced-motion override', () => {
    expect(
      GLOBALS.match(/@media \(prefers-reduced-motion: reduce\)/g),
    ).toHaveLength(1);
    expect(GLOBALS).toMatch(
      /prefers-reduced-motion: reduce[\s\S]*animation-delay: 0ms !important;[\s\S]*animation-duration: 0\.01ms !important;[\s\S]*transition-duration: 0\.01ms !important;/,
    );
    expect(APP_MOTION.reducedMotionQuery).toBe(
      '(prefers-reduced-motion: reduce)',
    );
  });

  it('does not leave local duration utilities or easing curves in production components', () => {
    for (const path of sourceFiles(SRC_ROOT).filter(
      (file) => file !== GLOBALS_PATH,
    )) {
      const file = relative(SRC_ROOT, path);
      const source = readFileSync(path, 'utf8');
      expect(source, file).not.toMatch(
        /\bduration-(?:75|100|150|200|300|500)\b/,
      );
      expect(source, file).not.toMatch(/ease-\[cubic-bezier\(/);
      expect(source, file).not.toMatch(/\b\d{2,4}ms\b/);
    }
  });

  it('keeps production animations named and reduced-motion aware', () => {
    const files = sourceFiles(SRC_ROOT);
    const animationFiles = files.filter((file) =>
      /(?:animation:|animate-|@keyframes)/.test(readFileSync(file, 'utf8')),
    );
    const names = animationFiles.map((file) => relative(SRC_ROOT, file));

    expect(names).toContain('styles/globals.css');
    expect(GLOBALS).toContain('app-route-enter');
    expect(GLOBALS).toContain('app-overlay-enter');
    expect(GLOBALS).toContain('app-drawer-enter');
    expect(GLOBALS).toContain('app-chart-enter');
    expect(GLOBALS).not.toMatch(/animation:\s*(?:pulse|spin)\s/);
  });
});
