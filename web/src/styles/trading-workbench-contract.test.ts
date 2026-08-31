// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = (path: string) => readFileSync(resolve(SRC_ROOT, path), 'utf8');
const TRADING_WORKSPACE = source(
  'features/trading/components/trading-workspace.tsx',
);
const TRADING_REVIEW_QUEUE = source(
  'features/trading/components/trading-review-queue.tsx',
);
const TRADING_HISTORY = source(
  'features/trading/components/trading-history.tsx',
);
const TRADING_SAFETY_RAIL = source(
  'features/trading/components/trading-safety-rail.tsx',
);
const EXECUTION_AUDIT = source(
  'features/trading/components/execution-audit-panel.tsx',
);
const ORDER_QUEUE = source('features/trading/components/order-queue.tsx');
const BROKER_READINESS = source(
  'features/trading/components/broker-readiness-panel.tsx',
);
const KILL_SWITCH = readFileSync(
  resolve(SRC_ROOT, 'features/trading/components/kill-switch-panel.tsx'),
  'utf8',
);
const AUTOMATIC_TRADING = readFileSync(
  resolve(SRC_ROOT, 'features/trading/components/automatic-trading-panel.tsx'),
  'utf8',
);

describe('trading workbench contract', () => {
  it('keeps the default review path flat and mobile filters task-first', () => {
    const tradingPage = [
      TRADING_WORKSPACE,
      TRADING_REVIEW_QUEUE,
      TRADING_SAFETY_RAIL,
      TRADING_HISTORY,
    ].join('\n');

    expect(tradingPage).toContain('data-testid="trading-secondary-filters"');
    expect(tradingPage).toContain('data-testid="trading-review-posture"');
    expect(tradingPage).toContain('data-testid="trading-safety-rail"');
    expect(tradingPage).toContain('app-trading-command-grid');
    expect(tradingPage).not.toContain(
      'xl:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]',
    );
    expect(tradingPage).toContain('sm:grid-cols-2');
    expect(tradingPage).toContain('data-testid="trading-history-disclosure"');
    expect(tradingPage).toContain('border-y border-[var(--app-divider)] py-3');
    expect(tradingPage).toContain('xl:flex-row');
    expect(tradingPage).toContain('xl:max-w-[440px]');
    expect(tradingPage).toContain('group-open:grid sm:grid-cols-2');
    expect(tradingPage).not.toContain('sm:hidden [&::-webkit-details-marker]');
    expect(tradingPage).toContain('app-workbench-section');
    expect(tradingPage).toContain('EvidenceState');
    expect(tradingPage).not.toContain('<FilterBar');
    expect(tradingPage).not.toContain('app-panel');
    expect(tradingPage).not.toMatch(/rounded-(?:2xl|3xl)/);
  });

  it('isolates manual-order and paper-shadow mutations in controlled zones', () => {
    const executionAudit = EXECUTION_AUDIT;
    const orderQueue = ORDER_QUEUE;

    expect(executionAudit).toContain('<ControlledActionZone');
    expect(executionAudit).toContain(
      'data-testid="trading-execution-audit-disclosure"',
    );
    expect(executionAudit).toContain('<summary');
    expect(executionAudit).toContain('onRunShadowReview');
    expect(executionAudit).toContain('onAcceptSimulationReview');
    expect(executionAudit).not.toContain('app-terminal-panel');
    expect(executionAudit).not.toContain('app-terminal-inner');
    expect(executionAudit).not.toMatch(/rounded-(?:2xl|3xl)/);

    expect(orderQueue).toContain('<ControlledActionZone');
    expect(orderQueue).toContain(
      'overflow-x-visible md:overflow-x-auto md:overscroll-x-contain',
    );
    expect(orderQueue).toContain('md:min-w-[1100px] md:table-fixed');
    expect(orderQueue).toContain('grid grid-cols-2');
    expect(orderQueue).toContain('md:table-row');
    expect(orderQueue).toContain('md:hidden');
    expect(orderQueue).not.toContain('className="min-w-[1100px]');
    expect(orderQueue).toContain('onClick={() => void onConfirm()}');
    expect(orderQueue).toContain('onClick={() => void onReject()}');
    expect(orderQueue).toContain('<WorkbenchStatusBadge');
    expect(orderQueue).not.toMatch(/rounded-(?:2xl|3xl)/);
    expect(orderQueue).not.toMatch(
      /text-\[var\(--app-(?:success|warning|danger)\)\]/,
    );
  });

  it('keeps a healthy kill switch quiet while surfacing an active boundary', () => {
    expect(KILL_SWITCH).toContain('if (enabled || killSwitch.isError)');
    expect(KILL_SWITCH).toContain(
      "data-kill-switch-state={snapshot ? 'inactive' : 'checking'}",
    );
    expect(KILL_SWITCH).toContain('<details');
    expect(KILL_SWITCH).toContain('<ControlledActionZone');
    expect(KILL_SWITCH).toContain('{pageLabels.expandOnDemand}');
    expect(KILL_SWITCH).not.toContain('var(--app-success-bg)');
    expect(KILL_SWITCH).not.toContain('var(--app-success-text)');
  });

  it('keeps the bounded automatic gate distinct from and beside the kill switch', () => {
    expect(TRADING_SAFETY_RAIL).toContain('<AutomaticTradingPanel />');
    expect(TRADING_SAFETY_RAIL).toContain('<KillSwitchPanel />');
    expect(AUTOMATIC_TRADING).toContain(
      'data-testid="automatic-trading-panel"',
    );
    expect(AUTOMATIC_TRADING).toContain('<ControlledActionZone');
    expect(AUTOMATIC_TRADING).toContain('labels.noRestart');
    expect(AUTOMATIC_TRADING).toContain(
      'enable_bounded_automatic_trading_gate_without_capital_authority',
    );
    expect(AUTOMATIC_TRADING).not.toContain('KillSwitch');
    expect(AUTOMATIC_TRADING).not.toMatch(/rounded-(?:2xl|3xl)/);
  });

  it('presents broker adapter and soak readiness as flat, read-only evidence', () => {
    const brokerReadiness = BROKER_READINESS.slice(
      BROKER_READINESS.indexOf('export function BrokerAdapterReadinessPanel'),
      BROKER_READINESS.indexOf('function selectSoakPromotionConnector'),
    );
    const readinessMetric = BROKER_READINESS.slice(
      BROKER_READINESS.indexOf('function BrokerReadinessMetric'),
      BROKER_READINESS.indexOf('function brokerAdapterReadinessCopy'),
    );

    expect(brokerReadiness).toContain('app-workbench-section');
    expect(brokerReadiness).toContain('<WorkbenchStatusBadge');
    expect(brokerReadiness).toContain('<EvidenceState');
    expect(brokerReadiness).toContain(
      'data-testid="broker-soak-promotion-readiness"',
    );
    expect(brokerReadiness).not.toContain('app-terminal-panel');
    expect(brokerReadiness).not.toContain('app-terminal-inner');
    expect(brokerReadiness).not.toMatch(/rounded-(?:2xl|3xl)/);
    expect(brokerReadiness).not.toMatch(/rounded-\[(?:27|28)px\]/);
    expect(readinessMetric).toContain('border-t border-[var(--app-divider)]');
    expect(readinessMetric).not.toMatch(/rounded-(?:xl|2xl|3xl)/);
  });
});
