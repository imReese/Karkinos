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
const ACCOUNT_TRUTH = source(
  'features/account-truth/components/account-truth-review-page.tsx',
);
const ACTIVITY_FEED = source('features/activity/components/activity-feed.tsx');
const PRICE_STRUCTURE_CHART = source(
  'features/market/components/price-structure-chart.tsx',
);
const MARKET_DATA_OPERATIONS = ROUTER.slice(
  ROUTER.indexOf('function MarketDataOperationsPanel'),
  ROUTER.indexOf('function MetricBlock'),
);
const ACTIVITY_FORMS = [
  source('features/activity/components/trade-form.tsx'),
  source('features/activity/components/cash-flow-form.tsx'),
  source('features/activity/components/dividend-form.tsx'),
  source('features/activity/components/manual-adjustment-form.tsx'),
  source('features/activity/components/fund-batch-form.tsx'),
];
const APP_SHELL = source('app/layout/app-shell.tsx');
const RESEARCH_TASK = source(
  'features/ai-research/components/research-task-panel.tsx',
);
const STRATEGY_RESEARCH = source(
  'features/ai-research/components/strategy-hypothesis-panel.tsx',
);
const BACKTEST_REPORT = source(
  'features/backtest/components/backtest-report-view.tsx',
);
const BACKTEST_METRICS = source(
  'features/backtest/components/metrics-grid.tsx',
);
const BACKTEST_REPORT_SECTIONS = [
  source('features/backtest/components/validation-evidence-panel.tsx'),
  source('features/backtest/components/strategy-metadata-snapshot-panel.tsx'),
  source('features/backtest/components/dataset-snapshot-panel.tsx'),
  source('features/backtest/components/equity-drawdown-chart.tsx'),
  source('features/backtest/components/fills-table.tsx'),
];
const CSS = source('styles/globals.css');

describe('remaining route workbench contract', () => {
  it('migrates every phase-four route to the compact workbench shell', () => {
    expect(ROUTER).toContain('data-workbench-route="market"');
    expect(ROUTER).toContain('data-workbench-route="activity"');
    expect(BACKTEST).toContain('data-workbench-route="backtest"');
    expect(TRADING).toContain('data-workbench-route="trading"');
    expect(SETTINGS).toContain('data-workbench-route="settings"');
    expect(ACCOUNT_TRUTH).toContain('data-workbench-route="account-truth"');

    for (const page of [ROUTER, BACKTEST, TRADING, SETTINGS, ACCOUNT_TRUTH]) {
      expect(page).toContain('WorkspaceHeader');
      expect(page).toContain('MetricStrip');
    }
  });

  it('keeps controlled review first and makes Activity history primary by viewport', () => {
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
    expect(
      activityPage.indexOf('data-activity-surface="audit-history"'),
    ).toBeLessThan(
      activityPage.indexOf('data-activity-surface="priority-and-entry"'),
    );
    expect(activityPage).toContain(
      'xl:sticky xl:top-24 xl:col-start-2 xl:row-start-1',
    );
    expect(activityPage).toContain('xl:col-start-1 xl:row-start-1');
    expect(
      activityPage.indexOf('data-activity-surface="audit-history"'),
    ).toBeLessThan(activityPage.indexOf('<ActivityFeed'));
    expect(ROUTER).toContain('<ControlledActionZone');
    expect(ROUTER).toContain('copy.activity.entryTools.boundary');
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
    expect(CSS).toMatch(
      /max-width:\s*767px[\s\S]*min-width:\s*var\(--app-touch-target\)[\s\S]*min-height:\s*var\(--app-touch-target\)/,
    );
    expect(CSS).toMatch(
      /\.app-shell-sidebar[\s\S]*\.app-toolbar-shell[\s\S]*min-height:\s*var\(--app-touch-target\)/,
    );
    expect(CSS).toMatch(
      /\.app-workbench-route a\[href\][\s\S]*display:\s*inline-flex/,
    );
    expect(CSS).toMatch(
      /prefers-reduced-motion:\s*reduce[\s\S]*transition-duration:\s*0\.01ms\s*!important/,
    );
    expect(CSS).toMatch(
      /min-width:\s*1024px[\s\S]*\.app-toolbar-brand\s*{[\s\S]*display:\s*none/,
    );
  });

  it('removes superseded route-local metric card components', () => {
    expect(ROUTER).not.toContain('function ActivityMetric');
    expect(TRADING).not.toContain('function StatusTile');
    expect(
      SETTINGS.match(/<ControlledActionZone/g)?.length ?? 0,
    ).toBeGreaterThanOrEqual(2);
  });

  it('keeps routine route structure flat and mobile preferences compact', () => {
    const activityFeed = ACTIVITY_FEED.slice(
      ACTIVITY_FEED.indexOf('export function ActivityFeed'),
      ACTIVITY_FEED.indexOf('function activityAmountClass'),
    );
    const marketPage = ROUTER.slice(
      ROUTER.indexOf('export function MarketPage'),
      ROUTER.indexOf('export function ActivityPage'),
    );
    const settingsSection = SETTINGS.slice(
      SETTINGS.indexOf('function SettingsSection'),
      SETTINGS.indexOf('function SettingsDisclosure'),
    );

    expect(activityFeed).toContain('app-workbench-section');
    expect(activityFeed).toContain('max-h-[min(68vh,42rem)]');
    expect(activityFeed).toContain('<thead className="sticky top-0 z-10">');
    expect(ACTIVITY_FEED).toContain('max-w-[240px] flex-wrap');
    expect(activityFeed).not.toContain(
      'app-panel min-w-0 overflow-hidden rounded-2xl',
    );
    expect(marketPage).not.toContain('app-panel rounded-2xl p-0');
    expect(
      marketPage.match(/app-workbench-section min-w-0 overflow-hidden/g),
    ).toHaveLength(1);
    expect(marketPage).toContain('data-testid="market-research-table"');
    expect(marketPage).toContain('data-testid="market-research-table-scroll"');
    expect(marketPage).toContain('data-testid="market-provider-details"');
    expect(marketPage).toContain('holdingReviewNeedsAttention');
    expect(marketPage).not.toContain('selectedItem.price ?? 0');
    expect(marketPage).not.toContain('selectedItem.market_value ?? 0');
    expect(marketPage).not.toContain('app-button-secondary rounded-2xl');
    expect(MARKET_DATA_OPERATIONS).toContain('<Timeline');
    expect(MARKET_DATA_OPERATIONS).not.toContain('app-panel');
    expect(MARKET_DATA_OPERATIONS).not.toContain('rounded-2xl');
    expect(PRICE_STRUCTURE_CHART).toContain('<EvidenceState');
    expect(PRICE_STRUCTURE_CHART).not.toContain('rounded-2xl');
    expect(PRICE_STRUCTURE_CHART).not.toContain('rounded-3xl');
    expect(settingsSection).toContain('border-y border-[var(--app-divider)]');
    expect(settingsSection).not.toContain('app-panel');
    expect(APP_SHELL).toContain('data-testid="mobile-preferences-toggle"');
    expect(APP_SHELL).toContain(
      'hidden min-w-0 flex-row items-center gap-2 sm:flex',
    );
    expect(ACCOUNT_TRUTH).toContain(
      'data-testid="account-truth-review-workspace"',
    );
    expect(ACCOUNT_TRUTH).toContain('EvidenceIdentityDisclosure');
    expect(ACCOUNT_TRUTH).not.toContain('rounded-2xl');
    expect(ACCOUNT_TRUTH).not.toContain('rounded-3xl');
    expect(ACCOUNT_TRUTH).not.toMatch(
      /style=\{\{[\s\S]*var\(--app-(?:success|warning|danger)\)/,
    );
  });

  it('keeps Activity ledger entry surfaces flat and token-shaped', () => {
    const activityTools = ROUTER.slice(
      ROUTER.indexOf('function ActivityEntryToolsPanel'),
      ROUTER.indexOf('function formatPendingStatus'),
    );

    expect(activityTools).toContain('<ControlledActionZone');
    expect(activityTools).toContain('app-workbench-section');
    expect(activityTools).not.toContain('app-panel');
    expect(activityTools).not.toContain('rounded-2xl');

    for (const form of ACTIVITY_FORMS) {
      expect(form).not.toContain('app-panel');
      expect(form).not.toContain('rounded-2xl');
      expect(form).toContain('rounded-[var(--app-radius-control)]');
    }
  });

  it('treats saved backtests as flat reproducible evidence instead of metric cards', () => {
    expect(BACKTEST_REPORT).toContain(
      'data-backtest-report-workspace="saved-evidence"',
    );
    expect(BACKTEST_REPORT).toContain('<FilterBar');
    expect(BACKTEST_REPORT).toContain('<MetricStrip');
    expect(BACKTEST_REPORT).toContain('<EvidenceState');
    expect(BACKTEST_METRICS.match(/<MetricStrip\s/g)).toHaveLength(2);

    for (const reportSurface of [
      BACKTEST_REPORT,
      BACKTEST_METRICS,
      ...BACKTEST_REPORT_SECTIONS,
    ]) {
      expect(reportSurface).not.toContain('app-panel');
      expect(reportSurface).not.toContain('rounded-2xl');
      expect(reportSurface).not.toMatch(/#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z_-])/);
      expect(reportSurface).not.toContain('backdrop-blur');
      expect(reportSurface).not.toMatch(/shadow-\[0_/);
    }

    expect(BACKTEST_METRICS).toContain("tone: 'pnl-negative'");
    expect(BACKTEST_METRICS).not.toContain("tone: 'danger'");
    expect(BACKTEST_REPORT_SECTIONS.join('\n')).toContain('<DataTable');
    expect(BACKTEST_REPORT_SECTIONS.join('\n')).toContain(
      'var(--app-chart-grid)',
    );
    expect(BACKTEST_REPORT_SECTIONS.join('\n')).not.toContain(
      '<ResponsiveContainer',
    );
    expect(
      BACKTEST_REPORT_SECTIONS.join('\n').match(/<ResponsiveChartFrame\s/g),
    ).toHaveLength(2);
    expect(
      BACKTEST_REPORT_SECTIONS.join('\n').match(/accessibilityLayer/g),
    ).toHaveLength(2);
    expect(
      BACKTEST_REPORT_SECTIONS.join('\n').match(/isAnimationActive=\{false\}/g),
    ).toHaveLength(2);
    expect(BACKTEST_REPORT_SECTIONS.join('\n')).toContain(
      'backtest-drawdown-${useId().replace',
    );
  });

  it('keeps the current backtest workspace flat and separates PnL from system danger', () => {
    const currentWorkspace = BACKTEST.slice(
      BACKTEST.indexOf('export function BacktestPage'),
      BACKTEST.indexOf('function BacktestResponsiveDisclosure'),
    );
    const strategyMetadata = BACKTEST.slice(
      BACKTEST.indexOf('function StrategyMetadataPanel'),
      BACKTEST.indexOf('function formatMetadataList'),
    );
    const summaryValue = BACKTEST.slice(
      BACKTEST.indexOf('function SummaryValue'),
    );

    expect(currentWorkspace).toContain(
      'data-testid="backtest-primary-workbench"',
    );
    expect(currentWorkspace).toContain('<StatusBadge tone="warning">');
    expect(currentWorkspace).toContain('rounded-[var(--app-radius-control)]');
    expect(currentWorkspace).not.toContain('rounded-2xl');
    expect(currentWorkspace).not.toContain('rounded-3xl');
    expect(currentWorkspace).not.toContain('backdrop-blur');
    expect(currentWorkspace).not.toMatch(/shadow-\[0_/);
    expect(strategyMetadata).not.toContain('rounded-2xl');
    expect(strategyMetadata).not.toContain('rounded-xl');
    expect(summaryValue).toContain('var(--app-pnl-negative)');
    expect(summaryValue).not.toContain('var(--app-danger)');
  });
});
