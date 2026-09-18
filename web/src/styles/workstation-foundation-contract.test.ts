// @ts-nocheck -- deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CSS = readFileSync(resolve(SRC_ROOT, 'styles/globals.css'), 'utf8');
const WORKBENCH_INDEX = readFileSync(
  resolve(SRC_ROOT, 'shared/ui/workbench/index.ts'),
  'utf8',
);

function sourceTree(directory: string): string {
  return readdirSync(resolve(SRC_ROOT, directory), { withFileTypes: true })
    .filter(
      (entry) =>
        entry.isDirectory() ||
        (/\.(?:ts|tsx)$/.test(entry.name) && !/\.test\./.test(entry.name)),
    )
    .map((entry) =>
      entry.isDirectory()
        ? sourceTree(`${directory}/${entry.name}`)
        : readFileSync(resolve(SRC_ROOT, directory, entry.name), 'utf8'),
    )
    .join('\n');
}
const OVERVIEW = sourceTree('features/overview');
const PORTFOLIO = sourceTree('features/portfolio');

function cssBlock(selector: string) {
  const start = CSS.indexOf(selector);
  if (start < 0) return '';
  const open = CSS.indexOf('{', start);
  const close = CSS.indexOf('}', open);
  return CSS.slice(start, close + 1);
}

describe('Karkinos workstation foundation contract', () => {
  it('exports the semantic workstation primitives', () => {
    for (const primitive of [
      'Button',
      'Disclosure',
      'ExceptionBoundary',
      'Register',
      'RegisterRow',
      'SectionHeader',
      'DataTable',
      'WorkspaceHeader',
    ]) {
      expect(WORKBENCH_INDEX).toContain(primitive);
    }
  });

  it('keeps Overview on the wide financial canvas without legacy cards', () => {
    expect(OVERVIEW).toContain('data-workbench-width="wide"');
    expect(OVERVIEW).toContain('<WorkspaceHeader');
    expect(OVERVIEW).toContain('<SectionHeader');
    expect(OVERVIEW).toContain('<MetricStrip');
    expect(OVERVIEW).not.toMatch(/rounded-(?:2xl|3xl)/);
    expect(OVERVIEW).not.toMatch(/\btext-(?:xl|2xl|3xl)\b/);
    expect(OVERVIEW).not.toContain('xl:grid-cols-[minmax(0,1fr)_18rem]');
  });
  it('keeps Portfolio on the wide canvas with secondary analysis delayed on laptops', () => {
    expect(PORTFOLIO).toContain('data-workbench-width="wide"');
    expect(PORTFOLIO).toContain('<SectionHeader');
    expect(PORTFOLIO).toContain('<Button');
    expect(PORTFOLIO).toContain(
      'min-[1440px]:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.5fr)]',
    );
    expect(PORTFOLIO).not.toContain(
      'xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,0.65fr)]',
    );
  });

  it('defines bounded workspace width modes', () => {
    expect(cssBlock('.app-workbench-route')).toContain('max-width: 1560px');
    expect(CSS).toContain(
      ".app-workbench-route[data-workbench-width='compact']",
    );
    expect(CSS).toContain('max-width: 1120px');
    expect(CSS).toContain(
      ".app-workbench-route[data-workbench-width='standard']",
    );
    expect(CSS).toContain('max-width: 1360px');
    expect(CSS).toContain(".app-workbench-route[data-workbench-width='wide']");
    expect(CSS).toContain('max-width: 2048px');
    expect(CSS).toContain(".app-workbench-route[data-workbench-width='full']");
    expect(CSS).toContain('max-width: none');
  });

  it('keeps workstation buttons sized and spatially stable', () => {
    expect(cssBlock('.app-button')).toContain(
      'font-size: var(--app-font-size-compact)',
    );
    expect(cssBlock('.app-button-sm')).toContain('min-height: 30px');
    expect(cssBlock('.app-button-md')).toContain('min-height: 34px');
    expect(CSS).toMatch(
      /@media \(pointer: coarse\)[\s\S]*\.app-button\s*\{[\s\S]*min-height:\s*var\(--app-touch-target\)/,
    );
    expect(CSS).not.toMatch(
      /\.app-button-(?:primary|secondary|danger):active[\s\S]{0,180}translate:/,
    );
  });
  it('uses calm route and drawer motion', () => {
    const route = cssBlock('@keyframes app-route-enter');
    const drawer = cssBlock('@keyframes app-drawer-enter');
    expect(route).toContain('opacity: 0');
    expect(route).not.toContain('translate');
    expect(drawer).toContain(
      'translate: calc(-1 * var(--app-motion-distance-md)) 0',
    );
    expect(drawer).not.toContain('scale');
    expect(CSS).toContain('--app-motion-route: 100ms');
    expect(CSS).toContain('--app-motion-deliberate: 160ms');
  });
});
