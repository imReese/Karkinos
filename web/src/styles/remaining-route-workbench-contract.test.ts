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
const MARKET_INSTRUMENT_WORKSPACE = source(
  'features/market/components/market-instrument-workspace.tsx',
);
const MARKET_DATA_OPERATIONS = ROUTER.slice(
  ROUTER.indexOf('function MarketDataOperationsPanel'),
  ROUTER.indexOf('function formatAge'),
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
const AI_RESEARCH = source(
  'features/ai-research/components/ai-research-page.tsx',
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
    expect(AI_RESEARCH).toContain('data-workbench-route="ai-research"');
    expect(TRADING).toContain('data-workbench-route="trading"');
    expect(SETTINGS).toContain('data-workbench-route="settings"');
    expect(ACCOUNT_TRUTH).toContain('data-workbench-route="account-truth"');

    for (const page of [
      ROUTER,
      BACKTEST,
      AI_RESEARCH,
      TRADING,
      SETTINGS,
      ACCOUNT_TRUTH,
    ]) {
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
    expect(activityPage).toContain('data-activity-surface="audit-history"');
    expect(activityPage).not.toContain(
      'data-activity-surface="priority-and-entry"',
    );
    expect(activityPage).not.toContain('xl:sticky xl:top-24');
    expect(activityPage).toContain('<EvidenceDrawer');
    expect(activityPage).toContain('open={entryDrawerOpen}');
    expect(
      activityPage.indexOf('data-activity-surface="audit-history"'),
    ).toBeLessThan(activityPage.indexOf('<ActivityFeed'));
    expect(ROUTER).toContain('<ControlledActionZone');
    expect(ROUTER).toContain('copy.activity.entryTools.boundary');
  });

  it('marks AI output as cited research rather than deterministic account fact', () => {
    expect(RESEARCH_TASK).toContain('data-evidence-kind="cited-ai-research"');
    expect(AI_RESEARCH).toContain('routePrimary');
    expect(
      AI_RESEARCH.indexOf('data-testid="ai-research-context-metrics"'),
    ).toBeLessThan(
      AI_RESEARCH.indexOf('data-testid="ai-research-primary-canvas"'),
    );
    expect(RESEARCH_TASK).not.toContain("kicker: 'AI research boundary'");
    expect(RESEARCH_TASK).not.toContain('Freeze canonical evidence');
    expect(STRATEGY_RESEARCH).toContain(
      'data-evidence-kind="cited-ai-research"',
    );
    expect(CSS).toContain('.app-ai-research-boundary');
    expect(CSS).toContain(
      "[data-workbench-route='ai-research'] .app-ai-research-boundary",
    );
    expect(RESEARCH_TASK.indexOf('{copy.reviewNote}')).toBeLessThan(
      RESEARCH_TASK.indexOf('<form'),
    );
  });

  it('enforces local overflow, compact shape, touch, and reduced-motion rules', () => {
    expect(CSS).toContain('.app-workbench-route');
    expect(CSS).toContain('overscroll-behavior-inline: contain');
    expect(CSS).toMatch(
      /max-width:\s*767px[\s\S]*\.app-shell-content[\s\S]*min-width:\s*var\(--app-touch-target\)[\s\S]*min-height:\s*var\(--app-touch-target\)/,
    );
    expect(CSS).toContain('summary');
    expect(CSS).toContain("input:not([type='checkbox'])");
    expect(CSS).toContain("[role='dialog']\n    :where(");
    expect(CSS).not.toContain("[data-workbench-route='ai-research'] :is(");
    expect(CSS).toMatch(
      /\.app-shell-sidebar[\s\S]*\.app-toolbar-shell[\s\S]*min-height:\s*var\(--app-touch-target\)/,
    );
    expect(CSS).toMatch(
      /\.app-shell-content a\[href\][\s\S]*display:\s*inline-flex/,
    );
    expect(CSS).toMatch(
      /prefers-reduced-motion:\s*reduce[\s\S]*transition-duration:\s*0\.01ms\s*!important/,
    );
    expect(CSS).toMatch(
      /min-width:\s*1280px[\s\S]*\.app-toolbar-brand\s*{[\s\S]*display:\s*none/,
    );
    expect(APP_SHELL).toContain('xl:relative xl:h-full');
    expect(APP_SHELL).toContain('app-mobile-primary-nav');
    expect(APP_SHELL).toContain('xl:hidden');
    expect(APP_SHELL).not.toContain('lg:relative lg:h-full');
  });

  it('keeps Operations readiness and subsystem metrics visibly scoped', () => {
    expect(CSS).toContain(
      "[data-testid='operations-page'] > .app-metric-strip::before",
    );
    expect(CSS).toMatch(
      /operations-page[^}]+app-metric-strip::before[\s\S]*content:\s*attr\(aria-label\)/,
    );
    expect(CSS).toMatch(
      /operations-page[^}]+app-metric-strip\s*{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/,
    );
    expect(CSS).toMatch(
      /min-width:\s*640px[\s\S]*operations-page[^}]+app-metric-strip[\s\S]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/,
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
    expect(marketPage).toContain('<MarketInstrumentWorkspace');
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain(
      'data-testid="market-instrument-workspace"',
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain(
      'data-testid="market-instrument-list"',
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain(
      'data-mobile-layout="horizontal-rail"',
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain('overflow-x-auto');
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain('md:overflow-x-visible');
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain('overflow-y-auto');
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain('scrollIntoView({');
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain(
      "'(prefers-reduced-motion: reduce)'",
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain(
      'md:grid-cols-[minmax(220px,256px)_minmax(0,1fr)]',
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).toContain(
      'xl:grid-cols-[minmax(264px,296px)_minmax(0,1fr)]',
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).not.toContain('rounded-2xl');
    expect(MARKET_INSTRUMENT_WORKSPACE).not.toContain('rounded-3xl');
    expect(marketPage).toContain('data-testid="market-provider-details"');
    expect(marketPage).toContain('holdingReviewNeedsAttention');
    expect(MARKET_INSTRUMENT_WORKSPACE).not.toContain(
      'selectedItem.price ?? 0',
    );
    expect(MARKET_INSTRUMENT_WORKSPACE).not.toContain(
      'selectedItem.market_value ?? 0',
    );
    expect(marketPage).not.toContain('app-button-secondary rounded-2xl');
    expect(MARKET_DATA_OPERATIONS).toContain('<Timeline');
    expect(MARKET_DATA_OPERATIONS).not.toContain('app-panel');
    expect(MARKET_DATA_OPERATIONS).not.toContain('rounded-2xl');
    expect(PRICE_STRUCTURE_CHART).toContain('<EvidenceState');
    expect(PRICE_STRUCTURE_CHART).not.toContain('rounded-2xl');
    expect(PRICE_STRUCTURE_CHART).not.toContain('rounded-3xl');
    expect(PRICE_STRUCTURE_CHART).not.toContain('changePercent');
    expect(PRICE_STRUCTURE_CHART).not.toContain('formatPercent');
    expect(settingsSection).toContain('border-y border-[var(--app-divider)]');
    expect(settingsSection).not.toContain('app-panel');
    const flatSettingsSurfaces = [
      ...SETTINGS.matchAll(
        /className="([^"]+)"\s+data-settings-surface="flat"/g,
      ),
    ];
    expect(flatSettingsSurfaces).toHaveLength(5);
    for (const [, className] of flatSettingsSurfaces) {
      expect(className).toContain('border-y border-[var(--app-divider)]');
      expect(className).not.toContain('rounded-');
      expect(className).not.toContain('bg-[');
    }
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
    expect(BACKTEST_REPORT).toContain('selectedSummary && !report.data');
    expect(BACKTEST_METRICS.match(/<MetricStrip\s/g)).toHaveLength(2);
    expect(BACKTEST_METRICS.match(/app-backtest-evidence-strip/g)).toHaveLength(
      2,
    );
    expect(CSS).toContain("[data-workbench-route='backtest']");
    expect(CSS).toContain('overflow-wrap: anywhere');

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
      "const chartId = useId().replace(/:/g, '')",
    );
    expect(BACKTEST_REPORT_SECTIONS.join('\n')).toContain(
      'backtest-equity-${chartId}',
    );
    expect(BACKTEST_REPORT_SECTIONS.join('\n')).toContain(
      'backtest-drawdown-${chartId}',
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
    expect(currentWorkspace).toContain('useBacktestResultsQuery()');
    expect(currentWorkspace).toContain("setMobileWorkspaceView('results')");
    expect(currentWorkspace).toContain('labels.resultsWorkspaceTab');
    expect(currentWorkspace).toContain(
      'data-testid="backtest-persisted-evidence"',
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

  it('gives expanded Operations gates and constrained Backtest copy enough width', () => {
    expect(CSS).toMatch(
      /\.app-operations-command-grid:has\(\s*> \[data-testid='controlled-pilot-readiness'\]\[open\]\s*\) \{\s*grid-template-columns: minmax\(0, 1fr\);/,
    );
    expect(BACKTEST).toContain(
      '2xl:grid-cols-[minmax(0,1fr)_minmax(180px,240px)]',
    );
    expect(BACKTEST).not.toContain(
      'sm:grid-cols-[minmax(0,1fr)_minmax(180px,240px)]',
    );
  });
});
