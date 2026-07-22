// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DECISION = readFileSync(
  resolve(SRC_ROOT, 'features/decision/components/decision-cockpit-page.tsx'),
  'utf8',
);
const DECISION_CORE = DECISION.slice(
  DECISION.indexOf('function DecisionSummaryCollapsedPanel'),
);

describe('decision workbench contract', () => {
  it('keeps the core human-review path flat and evidence-first', () => {
    expect(DECISION_CORE).toContain('ControlledActionZone');
    expect(DECISION_CORE).toContain('StatusBadge');
    expect(DECISION_CORE).toContain('<dl');
    expect(DECISION_CORE).toContain('<dt');
    expect(DECISION_CORE).not.toMatch(/rounded-(?:2xl|3xl)/);
    expect(DECISION_CORE).not.toMatch(/rounded-\[(?:18|20|22|27|28)px\]/);
    expect(DECISION_CORE).not.toContain('app-terminal-panel');
    expect(DECISION_CORE).not.toContain('app-terminal-inner');
    expect(DECISION_CORE).not.toMatch(
      /text-\[var\(--app-(?:success|warning|danger)\)\]/,
    );
  });

  it('keeps manual order preparation inside the controlled action primitive', () => {
    const signalQueue = DECISION_CORE.slice(
      DECISION_CORE.indexOf('function SignalQueuePanel'),
      DECISION_CORE.indexOf('function SummaryTile'),
    );
    const controlledZone = signalQueue.indexOf('<ControlledActionZone');
    const quantityInput = signalQueue.indexOf('<input', controlledZone);
    const prepareButton = signalQueue.indexOf('<button', quantityInput);
    const controlledZoneEnd = signalQueue.indexOf(
      '</ControlledActionZone>',
      prepareButton,
    );

    expect(controlledZone).toBeGreaterThanOrEqual(0);
    expect(quantityInput).toBeGreaterThan(controlledZone);
    expect(prepareButton).toBeGreaterThan(quantityInput);
    expect(controlledZoneEnd).toBeGreaterThan(prepareButton);
    expect(signalQueue).toContain(
      "action.manual_confirmation_status ===\n                            'ready_for_manual_confirmation'",
    );
  });
});
