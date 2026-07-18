// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CSS_PATH = resolve(SRC_ROOT, 'styles/globals.css');
const CSS = readFileSync(CSS_PATH, 'utf8');

const DEPRECATED_TOKEN_BUDGETS = {
  '--app-base': 2,
  '--app-mantle': 14,
  '--app-panel': 4,
  '--app-panel-strong': 26,
  '--app-surface-0': 215,
  '--app-surface-1': 35,
  '--app-foreground': 1,
  '--app-muted': 146,
  '--app-subtext-0': 37,
  '--app-soft': 111,
  '--app-button': 1,
  '--app-button-text': 1,
  '--app-accent-secondary': 8,
  '--app-accent-ghost': 6,
  '--app-accent-strong': 5,
  '--app-success': 88,
  '--app-warning': 192,
  '--app-danger': 127,
  '--app-teal': 1,
  '--app-overlay-0': 1,
  '--app-radius-lg': 1,
} as const;

const HARDCODED_COLOR_BUDGETS = {
  'features/account/components/live-holdings-summary-card.tsx': 2,
  'features/backtest/components/backtest-report-view.tsx': 3,
  'features/backtest/components/dataset-snapshot-panel.tsx': 9,
  'features/backtest/components/equity-drawdown-chart.tsx': 5,
  'features/backtest/components/fills-table.tsx': 2,
  'features/backtest/components/parameter-compare-panel.tsx': 3,
  'features/backtest/components/parameter-sweep-panel.tsx': 3,
  'features/backtest/components/strategy-metadata-snapshot-panel.tsx': 1,
  'features/backtest/components/validation-evidence-panel.tsx': 3,
  'features/trading/components/trading-page.tsx': 1,
} as const;

const THEME_COLOR_TOKENS = [
  '--app-bg',
  '--app-surface',
  '--app-surface-raised',
  '--app-surface-overlay',
  '--app-border',
  '--app-divider',
  '--app-text',
  '--app-text-secondary',
  '--app-text-tertiary',
  '--app-text-inverse',
  '--app-accent',
  '--app-accent-hover',
  '--app-accent-bg',
  '--app-accent-border',
  '--app-focus-ring',
  '--app-focus-shadow',
  '--app-success-text',
  '--app-success-bg',
  '--app-success-border',
  '--app-success-indicator',
  '--app-warning-text',
  '--app-warning-bg',
  '--app-warning-border',
  '--app-warning-indicator',
  '--app-danger-text',
  '--app-danger-bg',
  '--app-danger-border',
  '--app-danger-indicator',
  '--app-info-text',
  '--app-info-bg',
  '--app-info-border',
  '--app-info-indicator',
  '--app-pnl-positive',
  '--app-pnl-negative',
  '--app-pnl-neutral',
  '--app-shadow-overlay',
  '--app-shadow-sticky',
  '--app-chart-grid',
  '--app-chart-label',
  '--app-chart-buy',
  '--app-chart-sell',
] as const;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(path) : [path];
  });
}

const AUDITED_FILES = sourceFiles(SRC_ROOT).filter(
  (path) =>
    /\.(css|ts|tsx)$/.test(path) && !/\.(test|spec)\.(ts|tsx)$/.test(path),
);

function blockFor(selector: string): string {
  const selectorIndex = CSS.indexOf(selector);
  const openingBrace = CSS.indexOf('{', selectorIndex);
  let depth = 0;
  for (let index = openingBrace; index < CSS.length; index += 1) {
    if (CSS[index] === '{') depth += 1;
    if (CSS[index] === '}') depth -= 1;
    if (depth === 0) return CSS.slice(openingBrace + 1, index);
  }
  throw new Error(`Unclosed CSS block: ${selector}`);
}

function declarations(block: string): Map<string, string> {
  return new Map(
    [...block.matchAll(/(--(?:app|ctp)-[a-z0-9-]+)\s*:\s*([^;]+);/g)].map(
      ([, name, value]) => [name, value.trim()],
    ),
  );
}

function declarationNames(block: string): string[] {
  return [...block.matchAll(/(--app-[a-z0-9-]+)\s*:/g)].map(([, name]) => name);
}

const MOCHA_BLOCK = blockFor(':root {');
const LATTE_BLOCK = blockFor(":root[data-theme='light']");
const MOCHA = declarations(MOCHA_BLOCK);
const LATTE = new Map([...MOCHA, ...declarations(LATTE_BLOCK)]);

function tokenReferences(): Array<{ token: string; path: string }> {
  return AUDITED_FILES.flatMap((path) => {
    const source = readFileSync(path, 'utf8');
    return [...source.matchAll(/var\((--app-[a-z0-9-]+)/g)].map(
      ([, token]) => ({ token, path: relative(SRC_ROOT, path) }),
    );
  });
}

function resolveColor(
  token: string,
  theme: Map<string, string>,
  seen = new Set<string>(),
): string {
  if (seen.has(token)) throw new Error(`Circular token reference: ${token}`);
  seen.add(token);
  const raw = theme.get(token);
  if (!raw) throw new Error(`Missing color token: ${token}`);
  const reference = raw.match(/^var\((--[a-z0-9-]+)\)$/)?.[1];
  return reference ? resolveColor(reference, theme, seen) : raw;
}

type Rgb = [number, number, number];

function rgb(color: string, underlay?: Rgb): Rgb {
  const hex = color.match(/^#([0-9a-f]{6})$/i)?.[1];
  if (hex) {
    return [0, 2, 4].map((offset) =>
      Number.parseInt(hex.slice(offset, offset + 2), 16),
    ) as Rgb;
  }
  const rgba = color.match(
    /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/,
  );
  if (rgba && underlay) {
    const alpha = Number(rgba[4]);
    return [0, 1, 2].map(
      (index) =>
        Number(rgba[index + 1]) * alpha + underlay[index] * (1 - alpha),
    ) as Rgb;
  }
  throw new Error(`Unsupported deterministic color: ${color}`);
}

function luminance([red, green, blue]: Rgb): number {
  const channel = (value: number) => {
    const normalized = value / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  return (
    0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
  );
}

function contrast(foreground: Rgb, background: Rgb): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort(
    (a, b) => b - a,
  );
  return (light + 0.05) / (dark + 0.05);
}

describe('application design token contract', () => {
  it('has no duplicate, unresolved, or unused --app-* tokens', () => {
    const mochaNames = declarationNames(MOCHA_BLOCK);
    const latteNames = declarationNames(LATTE_BLOCK);
    expect(new Set(mochaNames).size).toBe(mochaNames.length);
    expect(new Set(latteNames).size).toBe(latteNames.length);

    const references = tokenReferences();
    const unresolved = references.filter(({ token }) => !MOCHA.has(token));
    expect(unresolved).toEqual([]);

    const referencedTokens = new Set(references.map(({ token }) => token));
    const unused = mochaNames.filter((token) => !referencedTokens.has(token));
    expect(unused).toEqual([]);
  });

  it('keeps Latte and Mocha theme roles symmetric', () => {
    const latteOverrides = declarations(LATTE_BLOCK);
    expect(
      THEME_COLOR_TOKENS.filter(
        (token) => !MOCHA.has(token) || !latteOverrides.has(token),
      ),
    ).toEqual([]);
  });

  it.each([
    ['Mocha', MOCHA],
    ['Latte', LATTE],
  ])('%s maintains text, state, PnL, and focus contrast', (_name, theme) => {
    const surfaces = [
      '--app-bg',
      '--app-surface',
      '--app-surface-raised',
      '--app-surface-overlay',
    ];
    const textTokens = [
      '--app-text',
      '--app-text-secondary',
      '--app-text-tertiary',
      '--app-pnl-positive',
      '--app-pnl-negative',
      '--app-pnl-neutral',
    ];
    for (const surface of surfaces) {
      const background = rgb(resolveColor(surface, theme));
      for (const text of textTokens) {
        expect(
          contrast(rgb(resolveColor(text, theme)), background),
          `${text} on ${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      expect(
        contrast(rgb(resolveColor('--app-focus-ring', theme)), background),
        `focus ring on ${surface}`,
      ).toBeGreaterThanOrEqual(3);
    }

    const stateSurface = rgb(resolveColor('--app-surface', theme));
    for (const state of ['success', 'warning', 'danger', 'info']) {
      const background = rgb(
        resolveColor(`--app-${state}-bg`, theme),
        stateSurface,
      );
      expect(
        contrast(rgb(resolveColor(`--app-${state}-text`, theme)), background),
        `${state} text on state background`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('does not increase deprecated token consumers', () => {
    const references = tokenReferences();
    for (const [token, budget] of Object.entries(DEPRECATED_TOKEN_BUDGETS)) {
      expect(
        references.filter((reference) => reference.token === token).length,
        token,
      ).toBeLessThanOrEqual(budget);
    }
  });

  it('does not add component-level hardcoded colors', () => {
    const pattern =
      /#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?(?![0-9a-fA-F])|#[0-9a-fA-F]{3}(?![0-9a-zA-Z])|rgba?\(/g;
    const violations = AUDITED_FILES.flatMap((path) => {
      if (path === CSS_PATH) return [];
      const source = readFileSync(path, 'utf8');
      const count = source.match(pattern)?.length ?? 0;
      const sourcePath = relative(SRC_ROOT, path);
      const budget = HARDCODED_COLOR_BUDGETS[sourcePath] ?? 0;
      return count > budget ? [{ sourcePath, count, budget }] : [];
    });
    expect(violations).toEqual([]);
  });

  it('keeps financial direction helpers independent from state aliases', () => {
    const financialFiles = [
      'app/router.tsx',
      'features/account/components/overview-cards.tsx',
      'features/account/components/live-holdings-summary-card.tsx',
      'features/account-strategy/components/strategy-contribution-gate-card.tsx',
      'features/backtest/components/metrics-grid.tsx',
      'features/market/components/price-structure-chart.tsx',
      'features/portfolio/components/holding-detail-page.tsx',
      'features/portfolio/components/positions-table.tsx',
      'features/portfolio/components/live-holdings-board.tsx',
    ];
    for (const sourcePath of financialFiles) {
      const source = readFileSync(resolve(SRC_ROOT, sourcePath), 'utf8');
      expect(source, sourcePath).not.toMatch(
        /var\(--app-(positive|negative|profit)\)/,
      );
    }
  });
});
