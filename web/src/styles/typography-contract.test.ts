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
const NUMERIC_OVERRIDE_CEILINGS: Readonly<Record<string, number>> = {
  'app/router.tsx': 53,
  'features/account-truth/components/account-truth-review-page.tsx': 12,
  'features/account/components/dashboard-quick-actions.tsx': 1,
  'features/account/components/equity-curve-card.tsx': 7,
  'features/account/components/performance-breakdown-card.tsx': 2,
  'features/activity/components/activity-feed.tsx': 7,
  'features/activity/components/trade-form.tsx': 1,
  'features/ai-research/components/research-task-panel.tsx': 7,
  'features/backtest/components/backtest-page.tsx': 27,
  'features/backtest/components/dataset-snapshot-panel.tsx': 3,
  'features/backtest/components/equity-drawdown-chart.tsx': 2,
  'features/backtest/components/fills-table.tsx': 1,
  'features/backtest/components/parameter-compare-panel.tsx': 3,
  'features/backtest/components/parameter-sweep-panel.tsx': 3,
  'features/backtest/components/strategy-learning-review-panel.tsx': 4,
  'features/backtest/components/strategy-metadata-snapshot-panel.tsx': 7,
  'features/backtest/components/validation-evidence-panel.tsx': 3,
  'features/decision/components/decision-cockpit-page.tsx': 8,
  'features/decision/components/decision-outcome-review-panel.tsx': 10,
  'features/decision/components/decision-quality-panel.tsx': 6,
  'features/market/components/confirmed-fund-nav-refresh-button.tsx': 1,
  'features/market/components/current-holding-market-evidence-review-panel.tsx': 7,
  'features/market/components/market-instrument-workspace.tsx': 12,
  'features/market/components/market-refresh-button.tsx': 1,
  'features/market/components/price-structure-chart.tsx': 6,
  'features/operations/components/operations-page.tsx': 1,
  'features/operations/controlled-broker-recovery-operator-panel.tsx': 2,
  'features/operations/controlled-broker-rejection-evidence-panel.tsx': 6,
  'features/operations/controlled-ledger-correction-operator-panel.tsx': 1,
  'features/operations/controlled-ledger-posting-operator-panel.tsx': 1,
  'features/operations/controlled-per-order-pilot-readiness-panel.tsx': 2,
  'features/operations/controlled-session-revocation-operator-panel.tsx': 3,
  'features/operations/controlled-terminal-clearance-operator-panel.tsx': 3,
  'features/operations/current-per-order-dossier-operator-panel.tsx': 1,
  'features/operations/manual-broker-cancellation-ticket-panel.tsx': 3,
  'features/operations/signed-broker-adapter-release-review-operator-panel.tsx': 1,
  'features/portfolio/components/holding-detail-page.tsx': 3,
  'features/portfolio/components/live-holdings-board.tsx': 1,
  'features/portfolio/components/portfolio-construction-recommendations-card.tsx': 2,
  'features/portfolio/components/positions-table.tsx': 2,
  'features/settings/components/settings-page.tsx': 5,
  'features/trading/components/kill-switch-panel.tsx': 1,
  'features/trading/components/order-approval-table.tsx': 3,
  'features/trading/components/trading-page.tsx': 2,
};

const CERTIFIED_CORE_SURFACES = [
  'app/components/workbench/workspace.tsx',
  'app/layout/app-shell.tsx',
  'features/account/components/overview-cards.tsx',
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

describe('Karkinos typography certification ratchet', () => {
  it('keeps certified shared account surfaces on semantic typography roles', () => {
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
});
