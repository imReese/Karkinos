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

// Numeric typography is permitted only where a semantic role itself is being
// defined or where the public brand surface deliberately uses responsive
// display type. The exact selector/property/value tuple is frozen so this list
// cannot silently broaden into a generic CSS escape hatch.
const CSS_NUMERIC_TYPOGRAPHY_EXCEPTIONS = new Set([
  '.app-product-mark|line-height|1',
  '.app-workspace-title|letter-spacing|-0.035em',
  '.app-page-title|letter-spacing|-0.025em',
  '.app-card-title|letter-spacing|-0.025em',
  '.app-toolbar-section-title|letter-spacing|-0.015em',
  '.app-public-eyebrow|line-height|1.5',
  '.app-public-hero-title|font-size|clamp(2.8rem, 7vw, 4.5rem)',
  '.app-public-hero-title|letter-spacing|-0.047em',
  '.app-public-hero-title|line-height|0.97',
  '.app-public-hero-title|word-spacing|0.07em',
  ':lang(zh) .app-public-hero-title|letter-spacing|-0.042em',
  ':lang(zh) .app-public-hero-title|line-height|1.07',
  '.app-public-hero-body|font-size|clamp(0.96rem, 1.25vw, 1.1rem)',
  '.app-public-hero-body|line-height|1.68',
  '.app-public-route-identity small|letter-spacing|0.06em',
  '.app-public-evidence-heading h2|font-size|clamp(1.6rem, 2.6vw, 2.25rem)',
  '.app-public-evidence-heading h2|letter-spacing|-0.038em',
  '.app-public-evidence-heading h2|line-height|1.1',
  '.app-public-preview-metrics dt, .app-public-priority-preview dt|letter-spacing|0.06em',
  '.app-public-priority-preview h3|font-size|clamp(1.15rem, 1.8vw, 1.45rem)',
  '.app-public-priority-preview h3|letter-spacing|-0.03em',
  '.app-public-priority-preview h3|line-height|1.18',
  '.app-public-priority-preview dd|line-height|1.55',
  '.app-public-evidence-state|letter-spacing|0.04em',
  '.app-public-evidence-boundary small|letter-spacing|0.07em',
  '.app-public-evidence-boundary span span|line-height|1.5',
  '.app-public-evidence-frame figcaption|line-height|1.55',
  '.app-public-section-heading h2, .app-public-cta-section h2|font-size|clamp(2.1rem, 4.4vw, 4.1rem)',
  '.app-public-section-heading h2, .app-public-cta-section h2|letter-spacing|-0.058em',
  '.app-public-section-heading h2, .app-public-cta-section h2|line-height|0.99',
  ':lang(zh) .app-public-section-heading h2, :lang(zh) .app-public-cta-section h2|letter-spacing|-0.045em',
  ':lang(zh) .app-public-section-heading h2, :lang(zh) .app-public-cta-section h2|line-height|1.08',
  '.app-public-section-heading > p:last-child, .app-public-cta-section > div > p:last-child|line-height|1.75',
  '.app-public-proof-route span, .app-public-workflow li > span|letter-spacing|0.08em',
  '.app-public-proof-grid h3, .app-public-workflow h3|font-size|1.25rem',
  '.app-public-proof-grid h3, .app-public-workflow h3|letter-spacing|-0.025em',
  '.app-public-proof-grid p, .app-public-workflow p|line-height|1.7',
  '.app-public-principle-list dd|line-height|1.7',
  '.app-public-cta-section h2|font-size|clamp(1.95rem, 3.6vw, 3.2rem)',
  '.app-public-cta-section h2|line-height|1.04',
  '.app-public-footer-grid h2|letter-spacing|0.12em',
  '.app-public-footer-brand p|line-height|1.65',
  '.app-public-footer-note|line-height|1.5',
  '.app-public-hero-title|font-size|clamp(3.6rem, 4.5vw, 5.1rem)',
  '.app-public-hero-title|font-size|clamp(2.65rem, 11.5vw, 3.2rem)',
  '.app-public-hero-title|letter-spacing|-0.038em',
  '.app-public-hero-title|line-height|1.01',
  '.app-public-hero-title|word-spacing|0.1em',
]);

const CERTIFIED_CORE_SURFACES = [
  'shared/ui/workbench/workspace.tsx',
  'app/layout/app-shell.tsx',
  'features/account-truth/components/account-truth-review-workspace.tsx',
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

function numericCssTypographyDeclarations(css: string): string[] {
  return Array.from(css.matchAll(/([^{}]+)\{([^{}]*)\}/g)).flatMap(
    ([, rawSelector, body]) => {
      const selector = rawSelector.trim().replace(/\s+/g, ' ');
      return Array.from(
        body.matchAll(
          /\b(font-size|font-weight|line-height|letter-spacing|word-spacing):\s*([^;]+);/g,
        ),
      ).flatMap(([, property, rawValue]) => {
        const value = rawValue.trim();
        return /[0-9]/.test(value) && !value.includes('var(')
          ? [`${selector}|${property}|${value}`]
          : [];
      });
    },
  );
}

describe('Karkinos typography certification ratchet', () => {
  it('keeps one deterministic cross-platform sans fallback order', () => {
    const css = readFileSync(join(SRC_ROOT, 'styles/globals.css'), 'utf8')
      .replace(/\s+/g, ' ')
      .trim();

    expect(css).toContain(
      "--app-font-sans: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif;",
    );
  });

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

  it('keeps CSS numeric typography on the exact audited exception list', () => {
    const observed = numericCssTypographyDeclarations(
      readFileSync(join(SRC_ROOT, 'styles/globals.css'), 'utf8'),
    );
    const observedSet = new Set(observed);

    expect({
      staleExceptions: [...CSS_NUMERIC_TYPOGRAPHY_EXCEPTIONS].filter(
        (exception) => !observedSet.has(exception),
      ),
      unexpected: observed.filter(
        (declaration) => !CSS_NUMERIC_TYPOGRAPHY_EXCEPTIONS.has(declaration),
      ),
    }).toEqual({ staleExceptions: [], unexpected: [] });
  });
});
