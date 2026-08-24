// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { APP_MOTION } from '../shared/motion';

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
    expect(APP_MOTION.exitDurationMs).toBe(180);
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

  it('limits looping motion to explicit loading indicators', () => {
    const uses = sourceFiles(SRC_ROOT)
      .filter((file) => file !== GLOBALS_PATH)
      .flatMap((path) => {
        const file = relative(SRC_ROOT, path);
        const source = readFileSync(path, 'utf8');
        return Array.from(
          source.matchAll(/(?:motion-safe:)?animate-(?:pulse|spin)/g),
          (match) => ({ file, token: match[0] }),
        );
      });

    expect([...new Set(uses.map(({ file }) => file))].sort()).toEqual([
      'app/layout/app-shell.tsx',
      'features/activity/components/activity-feed.tsx',
      'features/activity/pages/activity-page.tsx',
      'features/market/components/market-instrument-workspace.tsx',
      'features/market/components/market-refresh-button.tsx',
      'shared/ui/workbench/workspace.tsx',
    ]);
    for (const use of uses.filter(({ token }) => token.endsWith('pulse'))) {
      expect(use.token, use.file).toBe('motion-safe:animate-pulse');
    }
  });

  it('keeps dense facts spatially stable on hover', () => {
    for (const path of sourceFiles(SRC_ROOT).filter(
      (file) => file !== GLOBALS_PATH,
    )) {
      expect(readFileSync(path, 'utf8'), relative(SRC_ROOT, path)).not.toMatch(
        /hover:-?translate-y/,
      );
    }
    expect(GLOBALS).toContain(
      "button[aria-pressed]:not([data-motion='stable-fact'])",
    );
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
    expect(GLOBALS).toContain('app-overlay-exit');
    expect(GLOBALS).toContain('app-popover-enter');
    expect(GLOBALS).toContain('app-popover-exit');
    expect(GLOBALS).toContain('app-drawer-enter');
    expect(GLOBALS).toContain('app-drawer-exit');
    expect(GLOBALS).not.toContain('app-chart-enter');
    expect(GLOBALS).not.toMatch(/animation:\s*(?:pulse|spin)\s/);
  });

  it('keeps route, evidence, chart, and public-hero reveals single-layered', () => {
    expect(GLOBALS.match(/\.app-route-stage[^{]*\{/g)).toEqual([
      '.app-route-stage {',
    ]);
    expect(GLOBALS).not.toMatch(
      /\[data-workbench-primitive='(?:evidence-state|data-table)'\][^{]*\{[^}]*animation:/,
    );
    expect(GLOBALS).not.toMatch(
      /\[data-workbench-primitive='(?:exception-list|timeline|gate-matrix)'\][^{]*\{[^}]*animation:/,
    );
    expect(GLOBALS).not.toMatch(/\.app-chart-stage[\s\S]{0,160}animation:/);
    expect(GLOBALS).not.toMatch(
      /\.app-public-evidence-step(?:[^,{]|,(?!\s*\.app-public))*\{[^}]*animation:/,
    );
    expect(GLOBALS).not.toMatch(
      /\.app-chart-tooltip\s*,\s*\.recharts-tooltip-wrapper/,
    );

    const overlayEnter =
      GLOBALS.match(/@keyframes app-overlay-enter\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    const drawerEnter =
      GLOBALS.match(/@keyframes app-drawer-enter\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    const overlayExit =
      GLOBALS.match(/@keyframes app-overlay-exit\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    const drawerExit =
      GLOBALS.match(/@keyframes app-drawer-exit\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    expect(overlayEnter).not.toContain('opacity');
    expect(drawerEnter).not.toContain('opacity');
    expect(overlayExit).not.toContain('opacity');
    expect(drawerExit).not.toContain('opacity');
  });

  it('keeps overlays mounted through a semantic, non-interactive exit', () => {
    const shell = readFileSync(
      join(SRC_ROOT, 'app', 'layout', 'app-shell.tsx'),
      'utf8',
    );
    const drawer = readFileSync(
      join(SRC_ROOT, 'shared', 'ui', 'workbench', 'evidence-drawer.tsx'),
      'utf8',
    );

    for (const source of [shell, drawer]) {
      expect(source).toContain('useMotionPresence(open)');
      expect(source).toContain('data-motion-state={presence.state}');
      expect(source).toContain("presence.state === 'closing'");
    }
    expect(GLOBALS).toContain(
      ".app-command-backdrop[data-motion-state='closing']",
    );
    expect(GLOBALS).toContain(
      ".app-evidence-drawer-root[data-motion-state='closing']",
    );
    expect(GLOBALS).toContain(
      ".app-shell-popover[data-motion-state='closing']",
    );
    expect(GLOBALS).toContain(
      ".app-status-popover-root[data-motion-state='closing']",
    );
    expect(shell.match(/useMotionPresence\(open\)/g)).toHaveLength(3);
    expect(shell).toContain('useMotionPresence(Boolean(popup && expanded))');
  });

  it('removes closed mobile navigation from focus without contaminating desktop easing', () => {
    expect(GLOBALS).toMatch(
      /@media \(max-width: 1279px\)[\s\S]*\.app-shell-sidebar\[data-mobile-open='false'\][\s\S]*visibility: hidden;[\s\S]*visibility 0s linear var\(--app-motion-deliberate\)/,
    );
    expect(GLOBALS).toMatch(
      /@media \(min-width: 1280px\)[\s\S]*\.app-shell-sidebar\[data-desktop-expanded='false'\][\s\S]*var\(--app-ease-exit\)[\s\S]*\.app-shell-sidebar\[data-desktop-expanded='true'\][\s\S]*var\(--app-ease-enter\)/,
    );
    expect(GLOBALS).not.toMatch(
      /\.app-shell-sidebar\[data-mobile-open='false'\]\s*\{\s*transition-timing-function:/,
    );
  });
});
