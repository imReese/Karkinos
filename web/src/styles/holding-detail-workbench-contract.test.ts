// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const HOLDING_DETAIL = readFileSync(
  resolve(SRC_ROOT, 'features/portfolio/components/holding-detail-page.tsx'),
  'utf8',
);

describe('holding detail workbench contract', () => {
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
    expect(HOLDING_DETAIL).toContain('<ControlledActionZone');
    expect(HOLDING_DETAIL).toContain('refreshQuote.mutate({');
    expect(HOLDING_DETAIL).toContain('symbols: [position.symbol]');
    expect(HOLDING_DETAIL).toContain('force: true');
  });

  it('uses semantic tokens instead of raw status or hardcoded colors', () => {
    expect(HOLDING_DETAIL).not.toMatch(/var\(--app-warning\)/);
    expect(HOLDING_DETAIL).not.toMatch(
      /(?:#[\da-f]{3,8}\b|\brgba?\(|\bhsla?\()/i,
    );
  });
});
