// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOLDING_DETAIL_ROOT = resolve(SRC_ROOT, 'features/portfolio/components');
const HOLDING_DETAIL_FILES = readdirSync(HOLDING_DETAIL_ROOT)
  .filter(
    (name) =>
      name.startsWith('holding-detail-') &&
      /\.tsx?$/.test(name) &&
      !name.includes('.test.'),
  )
  .sort();
const REQUIRED_HOLDING_DETAIL_FILES = [
  'holding-detail-controller.tsx',
  'holding-detail-metrics-model.ts',
  'holding-detail-model-contracts.ts',
  'holding-detail-model-values.ts',
  'holding-detail-model.ts',
  'holding-detail-page.tsx',
  'holding-detail-panels.tsx',
  'holding-detail-primitives.tsx',
  'holding-detail-view.tsx',
];
const HOLDING_DETAIL_SOURCES = new Map(
  HOLDING_DETAIL_FILES.map((name) => [
    name,
    readFileSync(resolve(HOLDING_DETAIL_ROOT, name), 'utf8'),
  ]),
);
const HOLDING_DETAIL = [...HOLDING_DETAIL_SOURCES.values()].join('\n');
const PRICE_STRUCTURE = [
  'price-structure-chart.tsx',
  'price-structure-chart-model.ts',
  'price-structure-chart-sections.tsx',
  'price-structure-chart-svg.tsx',
  'price-structure-chart-view.tsx',
  'price-structure-loading-state.tsx',
]
  .map((name) =>
    readFileSync(resolve(SRC_ROOT, 'features/market/components', name), 'utf8'),
  )
  .join('\n');

describe('holding detail workbench contract', () => {
  it('keeps a bounded, explicit controller-model-view component family', () => {
    expect(HOLDING_DETAIL_FILES).toEqual(
      expect.arrayContaining(REQUIRED_HOLDING_DETAIL_FILES),
    );
    expect(new Set(HOLDING_DETAIL_FILES).size).toBe(
      HOLDING_DETAIL_FILES.length,
    );
    expect(HOLDING_DETAIL_FILES.length).toBeLessThanOrEqual(12);
    expect(HOLDING_DETAIL_SOURCES.get('holding-detail-page.tsx')).toContain(
      '<HoldingDetailController',
    );
    expect(
      HOLDING_DETAIL_SOURCES.get('holding-detail-controller.tsx'),
    ).toContain('buildHoldingDetailModel');
    expect(HOLDING_DETAIL_SOURCES.get('holding-detail-model.ts')).toContain(
      "from './holding-detail-model-contracts'",
    );
    expect(HOLDING_DETAIL_SOURCES.get('holding-detail-model.ts')).toContain(
      'buildHoldingMetricsModel',
    );
    expect(
      HOLDING_DETAIL_SOURCES.get('holding-detail-metrics-model.ts'),
    ).toContain('export function buildHoldingMetricsModel');
    expect(
      HOLDING_DETAIL_SOURCES.get('holding-detail-model-contracts.ts'),
    ).toContain('export type HoldingDetailModelSource');
    expect(HOLDING_DETAIL_SOURCES.get('holding-detail-view.tsx')).toContain(
      '<HoldingEvidencePanel',
    );
    expect(HOLDING_DETAIL_SOURCES.get('holding-detail-panels.tsx')).toContain(
      '<ControlledActionZone',
    );
    expect(
      HOLDING_DETAIL_SOURCES.get('holding-detail-primitives.tsx'),
    ).toContain('nextHoldingDetailTab');
  });

  it('keeps every production module and top-level named function bounded', () => {
    const violations: string[] = [];
    for (const [name, source] of HOLDING_DETAIL_SOURCES) {
      const sourceLines = source.split(/\r?\n/);
      const lineCount = sourceLines.length;
      if (lineCount > 800) {
        violations.push(`${name}:module:${lineCount}`);
      }

      for (let start = 0; start < sourceLines.length; start += 1) {
        const declaration = sourceLines[start].match(
          /^(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b/,
        );
        if (!declaration) continue;
        const endOffset = sourceLines
          .slice(start + 1)
          .findIndex((line) => line === '}');
        if (endOffset < 0) continue;
        const functionLines = endOffset + 2;
        if (functionLines > 350) {
          violations.push(`${name}:${declaration[1]}:${functionLines}`);
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it('keeps evidence views explicit, flat, and based on shared primitives', () => {
    expect(HOLDING_DETAIL).toContain('role="tablist"');
    expect(HOLDING_DETAIL).toContain('role="tabpanel"');
    expect(HOLDING_DETAIL).toContain("'position'");
    expect(HOLDING_DETAIL).toContain("'pnl-costs'");
    expect(HOLDING_DETAIL).toContain("'transactions'");
    expect(HOLDING_DETAIL).toContain("'evidence'");
    expect(HOLDING_DETAIL).toContain("'reconciliation'");
    expect(HOLDING_DETAIL).toContain('<WorkbenchMetricStrip');
    expect(HOLDING_DETAIL).toContain('<WorkbenchEvidenceState');
    expect(HOLDING_DETAIL).not.toContain('app-panel');
    expect(HOLDING_DETAIL).not.toContain('app-terminal-panel');
    expect(HOLDING_DETAIL).not.toMatch(/rounded-(?:2xl|3xl)/);
    expect(HOLDING_DETAIL).not.toMatch(/rounded-\[(?:27|28)px\]/);
  });

  it('isolates explicit quote ingestion without changing its command shape', () => {
    const controller = HOLDING_DETAIL_SOURCES.get(
      'holding-detail-controller.tsx',
    );
    expect(HOLDING_DETAIL).toContain('<ControlledActionZone');
    expect(controller).toContain('refreshQuote.mutate({');
    expect(controller).toContain('symbols: [position.symbol]');
    expect(controller).toContain('force: true');
  });

  it('keeps the overview single-axis on tablet and distinguishes missing price evidence', () => {
    expect(HOLDING_DETAIL).toContain(
      'data-testid="holding-price-structure-fallback"',
    );
    expect(HOLDING_DETAIL).toContain('<PriceStructureLoadingState');
    expect(PRICE_STRUCTURE).toContain('kind="loading"');
    expect(HOLDING_DETAIL).toContain('kind="error"');
    expect(HOLDING_DETAIL).toContain('kind="missing"');
    expect(HOLDING_DETAIL).toContain(
      'xl:grid-cols-[minmax(0,1.55fr)_minmax(280px,0.75fr)]',
    );
    expect(HOLDING_DETAIL).not.toContain(
      'md:grid-cols-[minmax(0,1.55fr)_minmax(280px,0.75fr)]',
    );
  });

  it('uses semantic tokens instead of raw status or hardcoded colors', () => {
    expect(HOLDING_DETAIL).not.toMatch(/var\(--app-warning\)/);
    expect(HOLDING_DETAIL).not.toMatch(
      /(?:#[\da-f]{3,8}\b|\brgba?\(|\bhsla?\()/i,
    );
  });
});
