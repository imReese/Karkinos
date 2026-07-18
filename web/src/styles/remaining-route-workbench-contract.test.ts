// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = (path: string) => readFileSync(resolve(SRC_ROOT, path), 'utf8');

const ROUTER = source('app/router.tsx');
const BACKTEST = source('features/backtest/components/backtest-page.tsx');
const TRADING = source('features/trading/components/trading-page.tsx');
const SETTINGS = source('features/settings/components/settings-page.tsx');
const RESEARCH_TASK = source(
  'features/ai-research/components/research-task-panel.tsx',
);
const STRATEGY_RESEARCH = source(
  'features/ai-research/components/strategy-hypothesis-panel.tsx',
);
const CSS = source('styles/globals.css');

describe('remaining route workbench contract', () => {
  it('migrates every phase-four route to the compact workbench shell', () => {
    expect(ROUTER).toContain('data-workbench-route="market"');
    expect(ROUTER).toContain('data-workbench-route="activity"');
    expect(BACKTEST).toContain('data-workbench-route="backtest"');
    expect(TRADING).toContain('data-workbench-route="trading"');
    expect(SETTINGS).toContain('data-workbench-route="settings"');

    for (const page of [ROUTER, BACKTEST, TRADING, SETTINGS]) {
      expect(page).toContain('WorkspaceHeader');
      expect(page).toContain('MetricStrip');
    }
  });

  it('keeps persisted review and ledger history before mutation surfaces', () => {
    const tradingPage = TRADING.slice(
      TRADING.indexOf('export function TradingPage'),
    );
    expect(
      tradingPage.indexOf('data-testid="trading-review-queue"'),
    ).toBeLessThan(tradingPage.indexOf('<KillSwitchPanel'));

    const activityPage = ROUTER.slice(
      ROUTER.indexOf('export function ActivityPage'),
      ROUTER.indexOf('type ActivityEntryTool'),
    );
    expect(activityPage.indexOf('<ActivityFeed')).toBeLessThan(
      activityPage.indexOf('<ActivityEntryToolsPanel'),
    );
  });

  it('marks AI output as cited research rather than deterministic account fact', () => {
    expect(RESEARCH_TASK).toContain('data-evidence-kind="cited-ai-research"');
    expect(STRATEGY_RESEARCH).toContain(
      'data-evidence-kind="cited-ai-research"',
    );
    expect(CSS).toContain('.app-ai-research-boundary');
  });

  it('enforces local overflow, compact shape, touch, and reduced-motion rules', () => {
    expect(CSS).toContain('.app-workbench-route');
    expect(CSS).toContain('overscroll-behavior-inline: contain');
    expect(CSS).toMatch(/max-width:\s*767px[\s\S]*min-height:\s*40px/);
    expect(CSS).toMatch(
      /\.app-shell-sidebar[\s\S]*\.app-toolbar-shell[\s\S]*min-height:\s*40px/,
    );
    expect(CSS).toMatch(
      /\.app-workbench-route a\[href\][\s\S]*display:\s*inline-flex/,
    );
    expect(CSS).toMatch(
      /prefers-reduced-motion:\s*reduce[\s\S]*transition-duration:\s*0\.01ms\s*!important/,
    );
  });

  it('removes superseded route-local metric card components', () => {
    expect(ROUTER).not.toContain('function ActivityMetric');
    expect(TRADING).not.toContain('function StatusTile');
    expect(
      SETTINGS.match(/<ControlledActionZone/g)?.length ?? 0,
    ).toBeGreaterThanOrEqual(2);
  });
});
