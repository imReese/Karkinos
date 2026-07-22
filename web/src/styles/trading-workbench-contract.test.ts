// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TRADING = readFileSync(
  resolve(SRC_ROOT, 'features/trading/components/trading-page.tsx'),
  'utf8',
);

describe('trading workbench contract', () => {
  it('keeps the default review path flat and mobile filters task-first', () => {
    const tradingPage = TRADING.slice(
      TRADING.indexOf('export function TradingPage'),
      TRADING.indexOf('function BrokerAdapterReadinessPanel'),
    );

    expect(tradingPage).toContain('data-testid="trading-secondary-filters"');
    expect(tradingPage).toContain('group-open:grid sm:contents');
    expect(tradingPage).toContain('app-workbench-section');
    expect(tradingPage).toContain('EvidenceState');
    expect(tradingPage).not.toContain('app-panel');
    expect(tradingPage).not.toMatch(/rounded-(?:2xl|3xl)/);
  });

  it('isolates manual-order and paper-shadow mutations in controlled zones', () => {
    const executionAudit = TRADING.slice(
      TRADING.indexOf('function ExecutionAuditPanel'),
      TRADING.indexOf('function manualTicketFormFromResult'),
    );
    const orderQueue = TRADING.slice(TRADING.indexOf('function OrderQueue'));

    expect(executionAudit).toContain('<ControlledActionZone');
    expect(executionAudit).toContain('onRunShadowReview');
    expect(executionAudit).toContain('onAcceptSimulationReview');
    expect(executionAudit).not.toContain('app-terminal-panel');
    expect(executionAudit).not.toContain('app-terminal-inner');
    expect(executionAudit).not.toMatch(/rounded-(?:2xl|3xl)/);

    expect(orderQueue).toContain('<ControlledActionZone');
    expect(orderQueue).toContain('onClick={() => void onConfirm()}');
    expect(orderQueue).toContain('onClick={() => void onReject()}');
    expect(orderQueue).toContain('<WorkbenchStatusBadge');
    expect(orderQueue).not.toMatch(/rounded-(?:2xl|3xl)/);
    expect(orderQueue).not.toMatch(
      /text-\[var\(--app-(?:success|warning|danger)\)\]/,
    );
  });
});
