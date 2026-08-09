import { expect, test, type Page, type Route } from '@playwright/test';

const overviewAcceptanceViewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 834, height: 1112 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
] as const;

const workbenchRoutePaths = [
  '/overview',
  '/portfolio',
  '/activity',
  '/risk',
  '/account-truth',
  '/decision',
  '/operations',
  '/market',
  '/trading',
  '/backtest',
  '/ai-research',
  '/settings',
] as const;

const certificationRoutePaths = [
  '/',
  ...workbenchRoutePaths,
  '/portfolio/TEST-MISSING',
] as const;

async function selectMobileTheme(page: Page, theme: 'light' | 'dark') {
  await page.getByTestId('mobile-preferences-toggle').click();
  const preferences = page.getByRole('dialog', {
    name: /Theme · Language|主题 · 语言/,
  });
  await preferences
    .getByRole('button', {
      name: theme === 'light' ? /Light theme|浅色主题/ : /Dark theme|深色主题/,
    })
    .click();
  await expect(preferences).toBeHidden();
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/market/kline/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
});

test('all workbench routes keep mobile interaction targets at least 44px', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });

  for (const path of workbenchRoutePaths) {
    await page.goto(path);
    const route = page.locator('.app-shell-content');
    await expect(route, path).toBeVisible({ timeout: 15_000 });

    const undersizedTargets = await route.evaluate((element) => {
      const selector = [
        'button',
        '[role="button"]',
        'a[href]',
        'select',
        'summary',
        'textarea',
        'input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="hidden"])',
      ].join(',');

      return Array.from(element.querySelectorAll<HTMLElement>(selector))
        .filter((target) => {
          const style = getComputedStyle(target);
          const bounds = target.getBoundingClientRect();
          return (
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            bounds.width > 0 &&
            bounds.height > 0
          );
        })
        .map((target) => {
          const bounds = target.getBoundingClientRect();
          return {
            height: Math.round(bounds.height * 10) / 10,
            label:
              target.getAttribute('aria-label') ??
              target.textContent?.trim().replace(/\s+/g, ' ').slice(0, 80) ??
              target.tagName.toLowerCase(),
            tag: target.tagName.toLowerCase(),
            width: Math.round(bounds.width * 10) / 10,
          };
        })
        .filter((target) => target.height < 44 || target.width < 44);
    });

    expect(undersizedTargets, path).toEqual([]);
    const overflow = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      return {
        content: content.scrollWidth - content.clientWidth,
        document:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      };
    });
    expect(overflow.document, path).toBeLessThanOrEqual(0);
    expect(overflow.content, path).toBeLessThanOrEqual(0);
  }
});

test('all route identities remain visible at a 200 percent layout-zoom equivalent', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 720, height: 450 });

  for (const path of certificationRoutePaths) {
    await page.goto(path);
    const heading = page.locator('h1').first();
    await expect(heading, path).toBeVisible({ timeout: 15_000 });

    const geometry = await page.evaluate(() => {
      const heading = document.querySelector('h1') as HTMLElement;
      const main = document.querySelector('main') as HTMLElement;
      const headingBounds = heading.getBoundingClientRect();
      return {
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        headingBottom: headingBounds.bottom,
        headingTop: headingBounds.top,
        mainOverflow: main.scrollWidth - main.clientWidth,
      };
    });

    expect(geometry.documentOverflow, path).toBeLessThanOrEqual(0);
    expect(geometry.mainOverflow, path).toBeLessThanOrEqual(0);
    expect(geometry.headingTop, path).toBeGreaterThanOrEqual(0);
    expect(geometry.headingBottom, path).toBeLessThanOrEqual(450);
  }
});

test('exemplar pages keep one evidence-first desktop reading path', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto('/overview');
  const overviewPrimary = page.getByTestId('overview-daily-workbench');
  const overviewQueue = page.getByTestId('overview-today-queue');
  const overviewHoldings = page.getByTestId('overview-holdings-section');
  const overviewPerformance = page.getByTestId('overview-performance-card');
  await expect(overviewPrimary).toBeVisible({ timeout: 15_000 });
  await expect(
    overviewPrimary.getByTestId('overview-today-queue'),
  ).toBeVisible();
  await expect(
    overviewPrimary.getByTestId('overview-holdings-section'),
  ).toBeVisible();
  const overviewQueueBox = (await overviewQueue.boundingBox())!;
  const overviewHoldingsBox = (await overviewHoldings.boundingBox())!;
  expect(overviewHoldingsBox.x).toBeLessThan(overviewQueueBox.x);
  expect(overviewHoldingsBox.width).toBeGreaterThan(overviewQueueBox.width);
  expect((await overviewPerformance.boundingBox())!.y).toBeGreaterThan(
    Math.max(overviewQueueBox.y, overviewHoldingsBox.y),
  );

  await page.goto('/risk');
  const blockingRegister = page.getByTestId('risk-blocking-register');
  const riskMetrics = page.getByLabel('Risk metrics');
  const thresholdTable = page.getByTestId('risk-threshold-table');
  const controlledActions = page.getByTestId('risk-trading-control-grid');
  const analysisDisclosure = page.getByTestId('risk-analysis-disclosure');
  const riskHistory = page.getByTestId('risk-history-disclosure');
  await expect(blockingRegister).toBeVisible({ timeout: 30_000 });
  const blockingRegisterBox = (await blockingRegister.boundingBox())!;
  const riskMetricsBox = (await riskMetrics.boundingBox())!;
  const controlledActionsBox = (await controlledActions.boundingBox())!;
  expect(blockingRegisterBox.x).toBeLessThan(riskMetricsBox.x);
  expect(Math.abs(blockingRegisterBox.y - riskMetricsBox.y)).toBeLessThan(8);
  expect(Math.abs(controlledActionsBox.x - riskMetricsBox.x)).toBeLessThan(8);
  expect(controlledActionsBox.y).toBeGreaterThan(riskMetricsBox.y);
  expect(controlledActionsBox.y).toBeLessThan(
    blockingRegisterBox.y + blockingRegisterBox.height,
  );
  await expect(page.getByTestId('order-approval-panel')).toHaveCount(0);
  expect((await thresholdTable.boundingBox())!.y).toBeGreaterThan(
    blockingRegisterBox.y + blockingRegisterBox.height,
  );
  await expect(analysisDisclosure).not.toHaveAttribute('open', '');
  await expect(page.getByTestId('risk-analysis-overview')).toBeHidden();
  await analysisDisclosure.locator('summary').click();
  await expect(analysisDisclosure).toHaveAttribute('open', '');
  await expect(page.getByTestId('risk-analysis-overview')).toBeVisible();
  await expect(riskHistory).not.toHaveAttribute('open', '');
  await expect(page.getByTestId('risk-recent-impact-list')).toBeHidden();
  const historySummary = riskHistory.locator('summary');
  await expect(historySummary).toBeVisible();
  await historySummary.click();
  await expect(riskHistory).toHaveAttribute('open', '');
  const recentImpactList = page.getByTestId('risk-recent-impact-list');
  const impactTimeline = page.getByTestId('risk-impact-timeline-scroll');
  await page.getByRole('tab', { name: /Recent impact events/ }).click();
  if ((await recentImpactList.count()) > 0) {
    await expect(recentImpactList).toBeVisible();
  }
  await expect(impactTimeline).toHaveCount(0);
  if ((await recentImpactList.count()) > 0) {
    expect(
      await recentImpactList.evaluate(
        (node) => getComputedStyle(node).overflowY,
      ),
    ).toBe('visible');
  }
  await page.getByRole('tab', { name: /Timeline attribution/ }).click();
  await expect(recentImpactList).toHaveCount(0);
  await expect(impactTimeline).toBeVisible({ timeout: 30_000 });
  expect(
    await impactTimeline.evaluate((node) => getComputedStyle(node).overflowY),
  ).toBe('visible');

  await page.goto('/backtest');
  const primaryResearch = page.getByTestId('backtest-primary-workbench');
  const parameterPanel = page.getByTestId('backtest-parameter-panel');
  const resultPanel = page.getByTestId('backtest-result-panel');
  const strategyDetail = page.getByTestId(
    'backtest-strategy-detail-disclosure',
  );
  await expect(primaryResearch).toBeVisible();
  await expect(strategyDetail).not.toHaveAttribute('open', '');
  expect((await parameterPanel.boundingBox())!.x).toBeLessThan(
    (await resultPanel.boundingBox())!.x,
  );
  await expect(page.getByTestId('backtest-mobile-workspace-tabs')).toBeHidden();
});

test('overview preserves the queue-to-holdings hierarchy across all acceptance viewports', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.route('**/api/portfolio/market-evidence-review', async (route) => {
    await route.fulfill({
      status: 503,
      body: 'persisted evidence unavailable',
    });
  });
  await page.setViewportSize(overviewAcceptanceViewports[0]);
  await page.goto('/overview');
  await expect(page.getByTestId('overview-holdings-section')).toBeVisible({
    timeout: 15_000,
  });

  for (const viewport of overviewAcceptanceViewports) {
    await page.setViewportSize(viewport);

    const queue = page.getByTestId('overview-today-queue');
    const holdings = page.getByTestId('overview-holdings-section');
    const queueBox = (await queue.boundingBox())!;
    const holdingsBox = (await holdings.boundingBox())!;
    const overflow = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      return {
        document:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        content: content.scrollWidth - content.clientWidth,
      };
    });

    expect(overflow.document, JSON.stringify(viewport)).toBe(0);
    expect(overflow.content, JSON.stringify(viewport)).toBe(0);
    expect(holdingsBox.y, JSON.stringify(viewport)).toBeLessThan(1100);
    if (viewport.width >= 1280) {
      expect(holdingsBox.x, JSON.stringify(viewport)).toBeLessThan(queueBox.x);
      expect(holdingsBox.width, JSON.stringify(viewport)).toBeGreaterThan(
        queueBox.width,
      );
    } else {
      expect(queueBox.y, JSON.stringify(viewport)).toBeLessThan(holdingsBox.y);
    }

    if (viewport.width === 390) {
      const content = page.locator('.app-shell-content');
      const supportMetrics = page.locator('.account-support-metric-strip');
      const safeNext = queue.getByRole('listitem').first().getByRole('link');
      await expect(safeNext).toBeVisible();

      const [contentBox, safeNextBox, supportMetricGeometry] =
        await Promise.all([
          content.boundingBox(),
          safeNext.boundingBox(),
          supportMetrics.evaluate((element) => ({
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth,
            itemTops: Array.from(element.children).map((item) =>
              Math.round(item.getBoundingClientRect().top),
            ),
          })),
        ]);

      expect(new Set(supportMetricGeometry.itemTops).size).toBe(1);
      expect(supportMetricGeometry.scrollWidth).toBeGreaterThan(
        supportMetricGeometry.clientWidth,
      );
      expect(safeNextBox!.y + safeNextBox!.height).toBeLessThanOrEqual(
        contentBox!.y + contentBox!.height,
      );
    }

    const additionalReviewItems = page.getByTestId('overview-today-queue-more');
    if ((await additionalReviewItems.count()) > 0) {
      await expect(additionalReviewItems).not.toHaveAttribute('open', '');
    }
  }
});

test('backtest preserves result-first evidence and complete metrics across all acceptance viewports', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(overviewAcceptanceViewports[0]);
  const resultsResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith('/api/backtest/results'),
  );
  await page.goto('/backtest');
  const response = await resultsResponse;
  expect(response.ok()).toBe(true);
  const savedResults = (await response.json()) as unknown;
  const hasSavedResults =
    Array.isArray(savedResults) && savedResults.length > 0;

  if (hasSavedResults) {
    await expect(
      page.locator('[data-backtest-report-section="metrics"]'),
    ).toBeVisible({ timeout: 15_000 });
  }

  for (const viewport of overviewAcceptanceViewports) {
    await page.setViewportSize(viewport);

    const geometry = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      const setup = document.querySelector(
        '[data-testid="backtest-parameter-panel"]',
      ) as HTMLElement;
      const results = document.querySelector(
        '[data-testid="backtest-result-panel"]',
      ) as HTMLElement;
      const tabs = document.querySelector(
        '[data-testid="backtest-mobile-workspace-tabs"]',
      ) as HTMLElement;
      const catalogHeader = document.querySelector(
        '[data-testid="backtest-strategy-catalog-header"]',
      ) as HTMLElement;
      const catalogControl = catalogHeader.querySelector(
        'label',
      ) as HTMLElement;
      const contextText = Array.from(
        document.querySelectorAll(
          '.app-backtest-context-strip .app-metric-strip-item > .truncate',
        ),
      );
      const reportEvidenceText = Array.from(
        document.querySelectorAll(
          '.app-backtest-evidence-strip:not(.app-backtest-context-strip) .app-metric-strip-item > .truncate',
        ),
      );
      const readinessEvidence = Array.from(
        document.querySelectorAll(
          '[data-testid="backtest-run-readiness-summary"] [title]',
        ),
      ) as HTMLElement[];
      return {
        contentOverflow: content.scrollWidth - content.clientWidth,
        catalogColumnCount:
          getComputedStyle(catalogHeader).gridTemplateColumns.split(' ').length,
        catalogControlWidth: catalogControl.getBoundingClientRect().width,
        catalogHeaderWidth: catalogHeader.getBoundingClientRect().width,
        contextTextResponsive:
          contextText.length > 0 &&
          contextText.every((element) => {
            const style = getComputedStyle(element);
            return (
              style.whiteSpace === 'normal' && style.overflow === 'visible'
            );
          }),
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        resultWidth: results.getBoundingClientRect().width,
        resultX: results.getBoundingClientRect().x,
        resultY: results.getBoundingClientRect().y,
        resultEvidenceUnclipped: reportEvidenceText.every((element) => {
          const style = getComputedStyle(element);
          return style.whiteSpace === 'normal' && style.overflow === 'visible';
        }),
        readinessEvidenceOverflow: readinessEvidence.reduce(
          (largest, element) =>
            Math.max(largest, element.scrollWidth - element.clientWidth),
          0,
        ),
        readinessEvidenceVerticalOverflow: readinessEvidence.reduce(
          (largest, element) =>
            Math.max(largest, element.scrollHeight - element.clientHeight),
          0,
        ),
        setupWidth: setup.getBoundingClientRect().width,
        setupX: setup.getBoundingClientRect().x,
        tabsVisible: getComputedStyle(tabs).display !== 'none',
        workspaceView: tabs.dataset.workspaceView,
      };
    });

    expect(geometry.documentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(geometry.contentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(geometry.contextTextResponsive, JSON.stringify(viewport)).toBe(true);
    expect(geometry.resultEvidenceUnclipped, JSON.stringify(viewport)).toBe(
      true,
    );
    expect(
      geometry.readinessEvidenceOverflow,
      JSON.stringify(viewport),
    ).toBeLessThanOrEqual(0);
    expect(
      geometry.readinessEvidenceVerticalOverflow,
      JSON.stringify(viewport),
    ).toBeLessThanOrEqual(0);

    if (viewport.width >= 1280) {
      expect(geometry.catalogColumnCount, JSON.stringify(viewport)).toBe(1);
      expect(
        Math.abs(geometry.catalogControlWidth - geometry.catalogHeaderWidth),
        JSON.stringify(viewport),
      ).toBeLessThanOrEqual(1);
      expect(geometry.tabsVisible, JSON.stringify(viewport)).toBe(false);
      expect(geometry.setupX, JSON.stringify(viewport)).toBeLessThan(
        geometry.resultX,
      );
      expect(geometry.resultWidth, JSON.stringify(viewport)).toBeGreaterThan(
        geometry.setupWidth,
      );
    } else {
      expect(geometry.tabsVisible, JSON.stringify(viewport)).toBe(true);
      expect(geometry.workspaceView, JSON.stringify(viewport)).toBe(
        hasSavedResults ? 'results' : 'setup',
      );
      if (hasSavedResults) {
        expect(geometry.resultY, JSON.stringify(viewport)).toBeLessThan(700);
      }
    }
  }
});

test('AI research keeps frozen evidence ahead of human capture across all acceptance viewports', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(overviewAcceptanceViewports[0]);
  await page.goto('/ai-research');
  const queue = page.locator(
    'section[aria-labelledby="ai-research-queue-title"]',
  );
  const composer = page.locator(
    'form[aria-labelledby="ai-research-composer-title"]',
  );
  const primaryCanvas = page.getByTestId('ai-research-primary-canvas');
  const contextMetrics = page.getByTestId('ai-research-context-metrics');
  const emptyState = page.getByRole('heading', {
    name: 'No frozen research task',
  });
  const collapseWorkspace = page.getByRole('button', {
    name: 'Collapse research workspace',
    exact: true,
  });
  const openStrategyLab = page.getByRole('link', {
    name: 'Open Strategy Lab',
    exact: true,
  });
  await expect(queue).toBeVisible({ timeout: 15_000 });
  await expect(composer).toHaveCount(0);

  for (const viewport of overviewAcceptanceViewports) {
    await page.setViewportSize(viewport);
    const primaryCanvasBox = (await primaryCanvas.boundingBox())!;
    const contextMetricsBox = (await contextMetrics.boundingBox())!;
    if (viewport.width >= 1280) {
      expect(
        Math.abs(contextMetricsBox.y - primaryCanvasBox.y),
        JSON.stringify(viewport),
      ).toBeLessThan(8);
      expect(primaryCanvasBox.x, JSON.stringify(viewport)).toBeLessThan(
        contextMetricsBox.x,
      );
      expect(primaryCanvasBox.width, JSON.stringify(viewport)).toBeGreaterThan(
        contextMetricsBox.width,
      );
    } else {
      expect(contextMetricsBox.y, JSON.stringify(viewport)).toBeLessThan(
        primaryCanvasBox.y,
      );
      const evidenceToCanvasGap =
        primaryCanvasBox.y - (contextMetricsBox.y + contextMetricsBox.height);
      expect(
        evidenceToCanvasGap,
        JSON.stringify(viewport),
      ).toBeGreaterThanOrEqual(16);
      expect(evidenceToCanvasGap, JSON.stringify(viewport)).toBeLessThanOrEqual(
        32,
      );
      if (viewport.width >= 1024) {
        expect(
          Math.abs(contextMetricsBox.x - primaryCanvasBox.x),
          JSON.stringify(viewport),
        ).toBeLessThanOrEqual(1);
        expect(
          Math.abs(contextMetricsBox.width - primaryCanvasBox.width),
          JSON.stringify(viewport),
        ).toBeLessThanOrEqual(1);
      }
    }
    expect(
      (await emptyState.boundingBox())!.y,
      JSON.stringify(viewport),
    ).toBeLessThan(viewport.height);
    const openComposer = page.getByRole('button', {
      name: 'Draft research task',
      exact: true,
    });
    await expect(openComposer).toHaveAttribute('aria-expanded', 'false');
    for (const [name, target] of Object.entries({
      openComposer,
      collapseWorkspace,
      openStrategyLab,
    })) {
      expect(
        Math.round((await target.boundingBox())!.height),
        `${name} ${JSON.stringify(viewport)}`,
      ).toBeGreaterThanOrEqual(44);
    }
    await openComposer.click();
    await expect(composer).toBeVisible();

    const queueBox = (await queue.boundingBox())!;
    const composerBox = (await composer.boundingBox())!;
    const geometry = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      return {
        contentOverflow: content.scrollWidth - content.clientWidth,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      };
    });

    expect(geometry.documentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(geometry.contentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(queueBox.y, JSON.stringify(viewport)).toBeLessThan(1100);
    if (viewport.width >= 1280) {
      expect(queueBox.x, JSON.stringify(viewport)).toBeLessThan(composerBox.x);
    } else {
      expect(queueBox.y, JSON.stringify(viewport)).toBeLessThan(composerBox.y);
    }

    await page
      .getByRole('button', { name: 'Close task draft', exact: true })
      .click();
    await expect(composer).toHaveCount(0);
  }
});

test('activity keeps immutable history in the first reading path across all acceptance viewports', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize(overviewAcceptanceViewports[0]);
  const entriesResponse = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname === '/api/ledger/entries',
  );
  await page.goto('/activity');
  const response = await entriesResponse;
  expect(response.ok()).toBe(true);
  const entries = (await response.json()) as unknown;
  const hasEntries = Array.isArray(entries) && entries.length > 0;
  const historySurface = page.locator(
    '[data-activity-surface="audit-history"]',
  );
  const historyRegion = page.locator(
    '[data-activity-surface="audit-history"] [role="region"]',
  );
  const emptyState = page.getByTestId('activity-history-empty');
  await expect(historySurface).toBeVisible({ timeout: 15_000 });
  if (hasEntries) {
    await expect(historyRegion).toBeVisible();
    await expect(emptyState).toHaveCount(0);
  } else {
    await expect(emptyState).toBeVisible();
    await expect(historyRegion).toHaveCount(0);
  }

  for (const viewport of overviewAcceptanceViewports) {
    await page.setViewportSize(viewport);
    const geometry = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      const categoryFilter = document.querySelector(
        '[aria-label="Ledger category filter"], [aria-label="流水分类筛选"]',
      ) as HTMLElement | null;
      const historySurface = document.querySelector(
        '[data-activity-surface="audit-history"]',
      ) as HTMLElement;
      const region = document.querySelector(
        '[data-activity-surface="audit-history"] [role="region"]',
      ) as HTMLElement | null;
      const table = region?.querySelector('table') ?? null;
      const emptyState = document.querySelector(
        '[data-testid="activity-history-empty"]',
      ) as HTMLElement | null;
      return {
        categoryFilterHeight:
          categoryFilter?.getBoundingClientRect().height ?? null,
        categoryFilterOverflow:
          categoryFilter === null
            ? null
            : categoryFilter.scrollWidth - categoryFilter.clientWidth,
        contentOverflow: content.scrollWidth - content.clientWidth,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        emptyStateTop: emptyState?.getBoundingClientRect().top ?? null,
        historyLocalOverflow:
          region === null ? null : region.scrollWidth - region.clientWidth,
        historyVerticalOverflow:
          region === null ? null : region.scrollHeight - region.clientHeight,
        historySurfaceTop: historySurface.getBoundingClientRect().top,
        tableTop: table?.getBoundingClientRect().top ?? null,
      };
    });

    expect(geometry.documentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(geometry.contentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(geometry.historySurfaceTop, JSON.stringify(viewport)).toBeLessThan(
      viewport.height,
    );
    if (hasEntries) {
      expect(
        Math.round(geometry.categoryFilterHeight ?? Number.POSITIVE_INFINITY),
        JSON.stringify(viewport),
      ).toBeLessThanOrEqual(48);
      expect(
        geometry.tableTop ?? Number.POSITIVE_INFINITY,
        JSON.stringify(viewport),
      ).toBeLessThan(viewport.width < 640 ? viewport.height * 0.9 : 700);
      if (viewport.width < 640) {
        expect(
          geometry.categoryFilterOverflow ?? 0,
          JSON.stringify(viewport),
        ).toBeGreaterThan(0);
        expect(
          geometry.historyLocalOverflow ?? 0,
          JSON.stringify(viewport),
        ).toBeGreaterThan(0);
      }
      if (Array.isArray(entries) && entries.length > 8) {
        expect(
          geometry.historyVerticalOverflow ?? 0,
          JSON.stringify(viewport),
        ).toBeGreaterThan(0);
      }
    } else {
      expect(geometry.emptyStateTop, JSON.stringify(viewport)).not.toBeNull();
      expect(
        geometry.emptyStateTop ?? Number.POSITIVE_INFINITY,
        JSON.stringify(viewport),
      ).toBeLessThan(viewport.height);
    }
  }
});

test('portfolio keeps filtering ordered above a compact holdings projection', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/portfolio');

  const filterBar = page.locator('[data-workbench-primitive="filter-bar"]');
  await expect(page.getByTestId('portfolio-summary-strip')).toBeVisible();
  await expect(filterBar).toBeVisible();
  await expect(filterBar.getByRole('textbox')).toBeVisible();
  await expect(filterBar.getByRole('combobox')).toHaveCount(5);

  const firstTableCell = page
    .locator('.app-positions-table .app-data-table th')
    .first();
  if ((await firstTableCell.count()) > 0) {
    expect(
      await firstTableCell.evaluate(
        (element) => getComputedStyle(element).position,
      ),
    ).toBe('sticky');
  }

  const geometry = await page.evaluate(() => {
    const content = document.querySelector('.app-shell-content') as HTMLElement;
    const tableShell = document.querySelector(
      '.app-positions-table [data-testid="positions-table-scroll"]',
    ) as HTMLElement | null;
    const liveHoldings = document.querySelector(
      '[data-testid="live-holdings-board"]',
    ) as HTMLElement | null;
    const tableHeaders = Array.from(
      document.querySelectorAll('[data-testid="positions-table-desktop"] th'),
    ).map((header) => header.textContent?.trim());
    return {
      contentOverflow: content.scrollWidth - content.clientWidth,
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      tableOverflow: tableShell
        ? tableShell.scrollWidth - tableShell.clientWidth
        : 0,
      liveHoldingsOverflow: liveHoldings
        ? liveHoldings.scrollWidth - liveHoldings.clientWidth
        : 0,
      tableHeaders,
    };
  });
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.contentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.tableOverflow).toBeGreaterThanOrEqual(0);
  expect(geometry.liveHoldingsOverflow).toBeLessThanOrEqual(0);
  if (geometry.tableHeaders.length > 0) {
    expect(geometry.tableHeaders.slice(0, 7)).toEqual([
      'Symbol',
      'Market Value',
      'Weight',
      'Today PnL',
      'Unrealized',
      'Realized PnL',
      'Quote State',
    ]);
  }
});

test('portfolio initial load preserves the holdings hierarchy without fabricated values', async ({
  page,
}) => {
  let releasePrimaryResponses = () => {};
  const primaryResponsesHeld = new Promise<void>((resolve) => {
    releasePrimaryResponses = resolve;
  });
  const holdPrimaryResponse = async (route: Route) => {
    const response = await route.fetch();
    await primaryResponsesHeld;
    await route.fulfill({ response });
  };

  await page.route('**/api/portfolio/positions', holdPrimaryResponse);
  await page.route('**/api/portfolio', holdPrimaryResponse);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/portfolio');

  const loadingSummary = page.getByTestId('portfolio-loading-summary');
  const loadingHoldings = page.getByTestId(
    'portfolio-loading-current-holdings',
  );
  const loadingFilters = page.getByTestId('portfolio-loading-filters');
  const loadingRows = page.getByTestId('portfolio-loading-rows');

  await expect(loadingSummary).toBeVisible();
  await expect(loadingSummary.locator(':scope > *')).toHaveCount(4);
  await expect(
    loadingHoldings.getByRole('heading', { level: 2 }),
  ).toBeVisible();
  await expect(loadingFilters).toBeVisible();
  await expect(loadingRows.locator(':scope > *')).toHaveCount(4);
  await expect(loadingSummary).not.toContainText(/[¥$€£]|\d+[,.]\d{2}/);
  await expect(loadingRows).toHaveText('');

  const loadingGeometry = await page.evaluate(() => {
    const summary = document.querySelector(
      '[data-testid="portfolio-loading-summary"]',
    )!;
    const holdings = document.querySelector(
      '[data-testid="portfolio-loading-current-holdings"]',
    )!;
    return {
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      summaryBottom: summary.getBoundingClientRect().bottom,
      holdingsTop: holdings.getBoundingClientRect().top,
    };
  });
  expect(loadingGeometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(loadingGeometry.holdingsTop).toBeGreaterThanOrEqual(
    loadingGeometry.summaryBottom,
  );

  releasePrimaryResponses();
  await expect(page.getByTestId('portfolio-summary-strip')).toBeVisible();
  await expect(page.getByTestId('portfolio-current-holdings')).toBeVisible();
});

test('portfolio mobile keeps holdings or an explicit empty state below disclosed filters', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/portfolio');

  const filterBar = page.locator('[data-workbench-primitive="filter-bar"]');
  const moreFilters = filterBar.locator(
    'button[aria-controls="portfolio-secondary-filters"]',
  );
  const currentHoldings = page.getByTestId('portfolio-current-holdings');
  const populatedSurface = currentHoldings.getByTestId('positions-mobile-list');
  const emptySurface = currentHoldings.getByText(
    'No holdings yet. Add trades from Activity first.',
    { exact: true },
  );
  const holdingsSurface = populatedSurface.or(emptySurface);
  const desktopTable = currentHoldings.getByTestId('positions-table-desktop');

  await expect(moreFilters).toBeVisible();
  await expect(filterBar.locator('select:visible')).toHaveCount(2);
  await expect(moreFilters).toHaveAttribute('aria-expanded', 'false');
  await expect(holdingsSurface).toBeVisible();
  await expect(desktopTable).toBeHidden();
  if ((await populatedSurface.count()) > 0) {
    const mobileRows = populatedSurface.locator(
      '[data-testid^="position-mobile-row-"]',
    );
    expect(await mobileRows.count()).toBeGreaterThan(0);
    await expect(mobileRows.first()).toBeVisible();
  } else {
    await expect(emptySurface).toBeVisible();
  }

  const compactControlHeights = await filterBar
    .locator('button:visible, input:visible, select:visible')
    .evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().height),
    );
  const minimumControlHeight =
    Math.round(Math.min(...compactControlHeights) * 100) / 100;
  expect(minimumControlHeight).toBeGreaterThanOrEqual(44);
  const collapsedFilterHeight = (await filterBar.boundingBox())!.height;

  await moreFilters.click();

  await expect(moreFilters).toHaveAttribute('aria-expanded', 'true');
  await expect(filterBar.locator('select:visible')).toHaveCount(5);
  const expandedFilterBox = (await filterBar.boundingBox())!;
  const expandedHoldingsTop = (await holdingsSurface.boundingBox())!.y;
  expect(expandedFilterBox.height).toBeGreaterThan(collapsedFilterHeight);
  expect(expandedHoldingsTop).toBeGreaterThanOrEqual(
    expandedFilterBox.y + expandedFilterBox.height,
  );

  const documentOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBeLessThanOrEqual(0);
});

test('holding detail keeps route identity during missing-state resolution', async ({
  page,
}) => {
  await page.route('**/api/portfolio/positions', async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 1_200));
    await route.fulfill({ response });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/portfolio/TEST-MISSING');

  const header = page.getByTestId('holding-detail-header');
  const returnLink = header.getByRole('link', {
    name: 'Return to holdings list',
  });
  await expect(
    header.getByRole('heading', {
      level: 1,
      name: 'TEST-MISSING Position',
    }),
  ).toBeVisible();
  await expect(returnLink).toBeVisible();
  await expect(page.getByText('Loading holding detail.')).toBeVisible();
  await expect(page.getByTestId('evidence-loading-workspace')).toBeVisible();
  await expect(page.getByTestId('evidence-loading-sidebar')).toBeHidden();

  const geometry = await returnLink.evaluate((link) => ({
    documentOverflow:
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
    height: link.getBoundingClientRect().height,
  }));
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(Math.round(geometry.height)).toBeGreaterThanOrEqual(44);
  await expect(
    page.getByText(
      'This symbol is not present in the current portfolio snapshot.',
    ),
  ).toBeVisible({ timeout: 15_000 });
});

test('holding detail keeps realized and unrealized PnL context readable on laptop', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.route('**/api/portfolio/positions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          symbol: '603659',
          display_name: '璞泰来',
          asset_class: 'stock',
          quantity: 400,
          available_qty: 400,
          frozen_qty: 0,
          avg_cost: 25.97,
          latest_price: 23.93,
          market_value: 9556,
          today_change: 36,
          unrealized_pnl: -815.6,
          realized_pnl: 192.9,
          commission_paid: 5,
          quote_timestamp: '2026-08-03T15:00:00+08:00',
          quote_status: 'stale',
          quote_source: 'market_bar_close',
          quote_age_seconds: 18000,
          stale_reason: 'market_closed',
          using_persistent_cache: true,
        },
      ]),
    });
  });

  await page.goto('/portfolio/603659');
  const summary = page.getByTestId('holding-summary-metrics');
  await expect(summary).toBeVisible({ timeout: 15_000 });
  const unrealizedDetail = summary
    .locator('.app-metric-strip-item')
    .filter({ hasText: 'Unrealized PnL' })
    .locator('div.app-type-label');
  await expect(unrealizedDetail).toContainText('Realized PnL ¥192.90');

  const geometry = await unrealizedDetail.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    whiteSpace: window.getComputedStyle(element).whiteSpace,
  }));
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.whiteSpace).toBe('pre-line');
});

test('portfolio mobile bounds long persisted holding rows in Latte and Mocha', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/portfolio/positions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          symbol: '012710',
          display_name: '华夏核心成长混合型证券投资基金超长持久化名称C',
          asset_class: 'fund',
          quantity: 898.3131,
          available_qty: 898.3131,
          frozen_qty: 0,
          avg_cost: 1.0018,
          latest_price: 0.6399,
          market_value: 574.83,
          today_change: 13.74,
          unrealized_pnl: -325.17,
          realized_pnl: 0,
          commission_paid: 0,
          quote_timestamp: '2026-07-27T15:00:00+08:00',
          quote_status: 'stale',
          quote_source: 'market_bar_close',
          quote_age_seconds: 162000,
          stale_reason: 'quote_older_than_expected_session',
          using_persistent_cache: true,
        },
      ]),
    });
  });

  await page.goto('/portfolio');
  const list = page.getByTestId('positions-mobile-list');
  const row = page.getByTestId('position-mobile-row-012710');
  await expect(row).toBeVisible();

  for (const theme of ['light', 'dark'] as const) {
    await selectMobileTheme(page, theme);
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);

    const geometry = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      const list = document.querySelector(
        '[data-testid="positions-mobile-list"]',
      ) as HTMLElement;
      const row = document.querySelector(
        '[data-testid="position-mobile-row-012710"]',
      ) as HTMLAnchorElement;
      const listBounds = list.getBoundingClientRect();
      const rowBounds = row.getBoundingClientRect();
      return {
        contentOverflow: content.scrollWidth - content.clientWidth,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        listOverflow: list.scrollWidth - list.clientWidth,
        rowLeft: rowBounds.left,
        rowRight: rowBounds.right,
        listLeft: listBounds.left,
        listRight: listBounds.right,
      };
    });

    expect(geometry.documentOverflow, `${theme} document`).toBeLessThanOrEqual(
      0,
    );
    expect(geometry.contentOverflow, `${theme} content`).toBeLessThanOrEqual(0);
    expect(geometry.listOverflow, `${theme} list`).toBeLessThanOrEqual(0);
    expect(geometry.rowLeft, `${theme} row left`).toBeGreaterThanOrEqual(
      geometry.listLeft,
    );
    expect(geometry.rowRight, `${theme} row right`).toBeLessThanOrEqual(
      geometry.listRight,
    );
  }
});

test('portfolio account and strategy evidence stay flat across themes and target widths', async ({
  page,
}) => {
  test.setTimeout(180_000);

  for (const theme of ['light', 'dark'] as const) {
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1280, height: 800 },
      { width: 834, height: 900 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto('/portfolio');
      await page.evaluate((nextTheme) => {
        window.localStorage.setItem('karkinos.theme', nextTheme);
      }, theme);
      await page.reload();

      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

      const accountGeometry = await page.evaluate(() => {
        const content = document.querySelector(
          '.app-shell-content',
        ) as HTMLElement;
        const liveHoldings = document.querySelector(
          '[data-testid="live-holdings-board"]',
        ) as HTMLElement | null;
        return {
          contentOverflow: content.scrollWidth - content.clientWidth,
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
          liveHoldingsOverflow: liveHoldings
            ? liveHoldings.scrollWidth - liveHoldings.clientWidth
            : 0,
        };
      });
      expect(
        accountGeometry.documentOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);
      expect(
        accountGeometry.contentOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);
      expect(
        accountGeometry.liveHoldingsOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);

      await page.getByRole('button', { name: /Strategy|策略/ }).click();
      const contribution = page.getByTestId('strategy-contribution-gate-card');
      await expect(contribution).toBeVisible();
      const contributionGeometry = await contribution.evaluate((element) => ({
        legacyTerminal: element.querySelectorAll(
          '.app-terminal-panel,.app-terminal-inner',
        ).length,
        oversizedRadii: element.querySelectorAll('.rounded-2xl,.rounded-3xl')
          .length,
        width: element.getBoundingClientRect().width,
      }));
      expect(
        contributionGeometry.legacyTerminal,
        `${theme} ${viewport.width}`,
      ).toBe(0);
      expect(
        contributionGeometry.oversizedRadii,
        `${theme} ${viewport.width}`,
      ).toBe(0);
      expect(
        contributionGeometry.width,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(viewport.width);
    }
  }
});

test('market keeps context, evidence review, and provider telemetry task-ordered across themes and target widths', async ({
  page,
}) => {
  test.setTimeout(120_000);

  for (const theme of ['light', 'dark'] as const) {
    for (const viewport of overviewAcceptanceViewports) {
      await page.setViewportSize(viewport);
      await page.goto('/market');
      await page.evaluate((nextTheme) => {
        window.localStorage.setItem('karkinos.theme', nextTheme);
      }, theme);
      await page.reload();

      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await expect(page.getByTestId('market-data-health-summary')).toBeVisible({
        timeout: 15_000,
      });
      await expect(
        page.getByTestId('market-provider-details'),
      ).not.toHaveAttribute('open', '');

      const geometry = await page.evaluate(() => {
        const route = document.querySelector(
          '[data-workbench-route="market"]',
        ) as HTMLElement;
        const workspace = document.querySelector(
          '[data-testid="market-instrument-workspace"]',
        ) as HTMLElement | null;
        const list = document.querySelector(
          '[data-testid="market-instrument-list"]',
        ) as HTMLElement | null;
        const detail = document.querySelector(
          '[data-testid="market-selected-instrument"]',
        ) as HTMLElement | null;
        const review = document.querySelector(
          '[data-testid="current-holding-market-evidence-review"]',
        ) as HTMLElement | null;
        const mobileNavigation = document.querySelector(
          '.app-mobile-primary-nav',
        ) as HTMLElement | null;
        const chartScroll = document.querySelector(
          '[data-testid="price-structure-chart-scroll"]',
        ) as HTMLElement | null;
        const instrumentStatuses = Array.from(
          document.querySelectorAll(
            '[data-testid^="market-instrument-status-"]',
          ),
        ) as HTMLElement[];
        return {
          routeOverflow: route.scrollWidth - route.clientWidth,
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
          oversizedRadii: route.querySelectorAll('.rounded-2xl,.rounded-3xl')
            .length,
          workspaceExists: workspace !== null,
          listExists: list !== null,
          listOverflow: list ? list.scrollHeight - list.clientHeight : 0,
          listHorizontalOverflow: list
            ? list.scrollWidth - list.clientWidth
            : 0,
          listWidth: list?.getBoundingClientRect().width ?? 0,
          listX: list?.getBoundingClientRect().x ?? 0,
          listY: list?.getBoundingClientRect().y ?? 0,
          listBottom: list?.getBoundingClientRect().bottom ?? 0,
          detailWidth: detail?.getBoundingClientRect().width ?? 0,
          detailX: detail?.getBoundingClientRect().x ?? 0,
          detailY: detail?.getBoundingClientRect().y ?? 0,
          chartExists: chartScroll !== null,
          chartScrollLeft: chartScroll?.scrollLeft ?? 0,
          chartScrollMax: chartScroll
            ? chartScroll.scrollWidth - chartScroll.clientWidth
            : 0,
          chartMask: chartScroll ? getComputedStyle(chartScroll).maskImage : '',
          mobileNavigationTop:
            mobileNavigation?.getBoundingClientRect().top ?? 0,
          instrumentStatusCount: instrumentStatuses.length,
          instrumentStatusOverflow: instrumentStatuses.reduce(
            (largest, element) =>
              Math.max(largest, element.scrollWidth - element.clientWidth),
            0,
          ),
          instrumentStatusVerticalOverflow: instrumentStatuses.reduce(
            (largest, element) =>
              Math.max(largest, element.scrollHeight - element.clientHeight),
            0,
          ),
          instrumentStatusesDescribed: instrumentStatuses.every(
            (element) =>
              element.id.length > 0 &&
              element.closest('button')?.getAttribute('aria-describedby') ===
                element.id,
          ),
          reviewAfterList:
            list !== null && review !== null
              ? review.getBoundingClientRect().top >
                list.getBoundingClientRect().top
              : true,
        };
      });

      expect(
        geometry.documentOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);
      expect(
        geometry.routeOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);
      expect(geometry.oversizedRadii, `${theme} ${viewport.width}`).toBe(0);
      expect(
        geometry.listOverflow,
        `${theme} ${viewport.width}`,
      ).toBeGreaterThanOrEqual(0);
      expect(geometry.reviewAfterList, `${theme} ${viewport.width}`).toBe(true);

      if (geometry.workspaceExists) {
        if (geometry.listExists) {
          expect(
            geometry.instrumentStatusCount,
            `${theme} ${viewport.width}`,
          ).toBeGreaterThan(0);
          expect(
            geometry.instrumentStatusOverflow,
            `${theme} ${viewport.width}`,
          ).toBeLessThanOrEqual(0);
          expect(
            geometry.instrumentStatusVerticalOverflow,
            `${theme} ${viewport.width}`,
          ).toBeLessThanOrEqual(0);
          expect(
            geometry.instrumentStatusesDescribed,
            `${theme} ${viewport.width}`,
          ).toBe(true);
        }
        await expect(
          page.getByTestId('market-instrument-workspace'),
        ).toBeVisible();
        const detail = page.getByTestId('market-selected-instrument');
        await expect(detail).toBeVisible();
        expect(
          geometry.detailWidth,
          `${theme} ${viewport.width}`,
        ).toBeGreaterThan(0);
        if (geometry.chartExists && viewport.width < 768) {
          expect(
            geometry.chartScrollMax,
            `${theme} ${viewport.width}`,
          ).toBeGreaterThan(0);
          expect(
            Math.abs(geometry.chartScrollMax - geometry.chartScrollLeft),
            `${theme} ${viewport.width}`,
          ).toBeLessThanOrEqual(2);
          expect(geometry.chartMask, `${theme} ${viewport.width}`).toContain(
            'linear-gradient',
          );
        }
      }

      if (geometry.listExists) {
        const list = page.getByTestId('market-instrument-list');
        await expect(list).toBeVisible();
        await expect(list.getByRole('button', { pressed: true })).toBeVisible();
        expect(
          geometry.listWidth,
          `${theme} ${viewport.width}`,
        ).toBeGreaterThan(0);
        if (viewport.width >= 768) {
          expect(
            geometry.detailX,
            `${theme} ${viewport.width}`,
          ).toBeGreaterThan(geometry.listX);
          if (viewport.width < 1024) {
            expect(
              geometry.listBottom,
              `${theme} ${viewport.width}`,
            ).toBeLessThanOrEqual(geometry.mobileNavigationTop);
          }
        } else {
          expect(
            geometry.listHorizontalOverflow,
            `${theme} ${viewport.width}`,
          ).toBeGreaterThan(0);
          expect(
            geometry.detailY,
            `${theme} ${viewport.width}`,
          ).toBeGreaterThan(geometry.listY);
          expect(
            geometry.detailY - geometry.listY,
            `${theme} ${viewport.width}`,
          ).toBeLessThan(260);
        }
      }
    }
  }
});

test('exemplar routes remain task-reordered and overflow safe on mobile themes', async ({
  page,
}) => {
  test.setTimeout(90_000);

  for (const theme of ['light', 'dark']) {
    for (const path of ['/overview', '/portfolio', '/risk', '/backtest']) {
      await page.setViewportSize({ width: 390, height: 844 });
      const backtestResultsResponse =
        path === '/backtest'
          ? page.waitForResponse(
              (response) =>
                response.request().method() === 'GET' &&
                response.url().endsWith('/api/backtest/results'),
            )
          : null;
      await page.goto(path);
      let hasSavedResults = false;
      if (backtestResultsResponse) {
        const response = await backtestResultsResponse;
        expect(response.ok()).toBe(true);
        const savedResults = (await response.json()) as unknown;
        hasSavedResults =
          Array.isArray(savedResults) && savedResults.length > 0;
      }
      await selectMobileTheme(page, theme as 'light' | 'dark');

      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.getByTestId('mobile-navigation-toggle')).toBeVisible();

      const geometry = await page.evaluate(() => {
        const content = document.querySelector(
          '.app-shell-content',
        ) as HTMLElement;
        return {
          contentOverflow: content.scrollWidth - content.clientWidth,
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        };
      });
      expect(geometry.documentOverflow, `${path} ${theme}`).toBeLessThanOrEqual(
        0,
      );
      if (path === '/overview') {
        const queueBox = await page
          .getByTestId('overview-today-queue')
          .boundingBox();
        expect(
          queueBox?.y ?? Number.POSITIVE_INFINITY,
          `${path} ${theme} queue first-screen priority`,
        ).toBeLessThan(680);
        const holdingsBox = await page
          .getByTestId('overview-holdings-section')
          .boundingBox();
        expect(holdingsBox?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(1100);
        const additionalReviewItems = page.getByTestId(
          'overview-today-queue-more',
        );
        if ((await additionalReviewItems.count()) > 0) {
          await expect(additionalReviewItems).toBeVisible();
          await expect(additionalReviewItems).not.toHaveAttribute('open', '');
        }
      }
      expect(geometry.contentOverflow, `${path} ${theme}`).toBeLessThanOrEqual(
        0,
      );

      if (path === '/backtest') {
        const contextStrip = page.locator('.app-backtest-context-strip');
        await expect(contextStrip).toBeVisible();
        const contextGeometry = await contextStrip.evaluate((element) => ({
          height: element.getBoundingClientRect().height,
          horizontalOverflow: element.scrollWidth - element.clientWidth,
          textUnclipped: Array.from(
            element.querySelectorAll('.truncate'),
          ).every((item) => {
            const style = getComputedStyle(item);
            return (
              style.whiteSpace === 'normal' && style.overflow === 'visible'
            );
          }),
        }));
        expect(contextGeometry.height, theme).toBeLessThanOrEqual(144);
        expect(contextGeometry.horizontalOverflow, theme).toBeGreaterThan(0);
        expect(contextGeometry.textUnclipped, theme).toBe(true);

        const tabs = page.getByTestId('backtest-mobile-workspace-tabs');
        const resultTab = tabs.getByRole('tab', {
          name: /Results and evidence|结果与证据/,
        });
        await expect(tabs).toBeVisible();
        await expect(tabs).toHaveAttribute(
          'data-workspace-view',
          hasSavedResults ? 'results' : 'setup',
        );
        await expect(resultTab).toHaveAttribute(
          'aria-selected',
          hasSavedResults ? 'true' : 'false',
        );
        if (!hasSavedResults) {
          await resultTab.click();
        }
        await expect(resultTab).toHaveAttribute('aria-selected', 'true');
        await expect(page.getByTestId('backtest-result-panel')).toBeVisible();
        if (hasSavedResults) {
          const evidenceText = page.locator(
            '.app-backtest-evidence-strip:not(.app-backtest-context-strip) .app-metric-strip-item > .truncate',
          );
          await expect(evidenceText.first()).toBeVisible({ timeout: 15_000 });
          expect(await evidenceText.count()).toBeGreaterThan(0);
          expect(
            await evidenceText.evaluateAll((elements) =>
              elements.every((element) => {
                const style = getComputedStyle(element);
                return (
                  style.whiteSpace === 'normal' && style.overflow === 'visible'
                );
              }),
            ),
            theme,
          ).toBe(true);
        }
      }
    }
  }
});

test('core review routes keep audit drill-downs closed and mobile reading paths bounded', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/decision');
  await expect(
    page.getByRole('heading', { name: /Decision platform|决策平台/ }),
  ).toBeVisible();
  await expect(
    page.getByTestId('decision-quality-disclosure'),
  ).not.toHaveAttribute('open', '');
  await expect(
    page.getByTestId('decision-automation-disclosure'),
  ).not.toHaveAttribute('open', '');
  const gateDisclosure = page.getByTestId('decision-gate-disclosure');
  const gateToggle = gateDisclosure.getByRole('button');
  const gateMatrix = page.getByTestId('gate-matrix-responsive-table');
  const gateExpanded = await gateToggle.getAttribute('aria-expanded');
  expect(['false', 'true']).toContain(gateExpanded);
  if (gateExpanded === 'false') {
    await expect(gateMatrix).toBeHidden();
    await gateToggle.click();
    await expect(gateToggle).toHaveAttribute('aria-expanded', 'true');
  }
  await expect(gateMatrix).toBeVisible();
  await expect(
    page.locator('[data-testid^="decision-candidate-card-"]'),
  ).toHaveCount(0);
  const idlePlanDisclosure = page.getByTestId(
    'decision-daily-trading-plan-disclosure',
  );
  if ((await idlePlanDisclosure.count()) > 0) {
    await expect(idlePlanDisclosure).not.toHaveAttribute('open', '');
    const idlePlanSummary = idlePlanDisclosure.locator('summary');
    await idlePlanSummary.press('Enter');
    await expect(idlePlanDisclosure).toHaveAttribute('open', '');
    await expect(
      idlePlanDisclosure.getByTestId('decision-daily-trading-plan'),
    ).toBeVisible();
    await idlePlanSummary.press('Enter');
    await expect(idlePlanDisclosure).not.toHaveAttribute('open', '');
  }

  await page.goto('/trading');
  await expect(
    page.getByRole('heading', { name: /Trading review|交易复核/ }),
  ).toBeVisible();
  const killSwitch = page.getByTestId('kill-switch-panel');
  await expect(killSwitch).toBeVisible();
  await expect(killSwitch).toHaveAttribute(
    'data-kill-switch-state',
    'inactive',
  );
  await expect(killSwitch).not.toHaveAttribute('open', '');
  await expect(
    page.getByTestId('trading-broker-boundary-disclosure'),
  ).not.toHaveAttribute('open', '');
  await expect(
    page.getByTestId('trading-execution-audit-disclosure'),
  ).not.toHaveAttribute('open', '');
  await expect(
    page.getByTestId('trading-history-disclosure'),
  ).not.toHaveAttribute('open', '');

  await page.goto('/settings');
  await expect(
    page.getByRole('heading', { name: /Control center|控制中心/ }),
  ).toBeVisible();
  await expect(
    page.getByTestId('settings-persisted-configuration'),
  ).toBeVisible();
  const metadataDisclosure = page.getByTestId('settings-metadata-disclosure');
  await expect(metadataDisclosure).not.toHaveAttribute('open', '');
  await metadataDisclosure.locator('summary').click();
  await expect(metadataDisclosure).toHaveAttribute('open', '');
  const metadataSource = page.getByText('Saved register and watchlist', {
    exact: true,
  });
  await expect(metadataSource).toBeVisible();
  const metadataSourceGeometry = await metadataSource.evaluate((element) => ({
    horizontalOverflow: element.scrollWidth - element.clientWidth,
    verticalOverflow: element.scrollHeight - element.clientHeight,
    whiteSpace: getComputedStyle(element).whiteSpace,
  }));
  expect(metadataSourceGeometry.horizontalOverflow).toBeLessThanOrEqual(0);
  expect(metadataSourceGeometry.verticalOverflow).toBeLessThanOrEqual(0);
  expect(metadataSourceGeometry.whiteSpace).toBe('normal');
  await metadataDisclosure.locator('summary').click();
  await expect(metadataDisclosure).not.toHaveAttribute('open', '');
  for (const testId of [
    'settings-configuration-editor',
    'settings-data-source-disclosure',
    'settings-notifications-disclosure',
  ]) {
    await expect(page.getByTestId(testId)).not.toHaveAttribute('open', '');
  }
  await expect(
    page.getByRole('heading', { name: /Refresh quotes|刷新行情/ }),
  ).not.toBeVisible();
  const persistedSettingsBox = (await page
    .getByTestId('settings-persisted-configuration')
    .boundingBox())!;
  const notificationsBox = (await page
    .getByTestId('settings-notifications-disclosure')
    .boundingBox())!;
  const dataOperationsBox = (await page
    .getByTestId('settings-data-source-disclosure')
    .boundingBox())!;
  expect(notificationsBox.y).toBeGreaterThan(persistedSettingsBox.y);
  expect(dataOperationsBox.y).toBeGreaterThan(notificationsBox.y);

  await page.goto('/backtest');
  await expect(
    page.getByRole('heading', { name: /Strategy replay|策略回放/ }),
  ).toBeVisible();
  await expect(
    page.getByTestId('backtest-strategy-detail-disclosure'),
  ).not.toHaveAttribute('open', '');
  for (const testId of [
    'backtest-advanced-tools-disclosure',
    'backtest-research-governance-disclosure',
    'backtest-promotion-evidence-disclosure',
    'backtest-research-archive-disclosure',
  ]) {
    await expect(page.getByTestId(testId)).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  }

  for (const path of ['/decision', '/trading', '/settings', '/backtest']) {
    await page.goto(path);
    const geometry = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      return {
        contentOverflow: content.scrollWidth - content.clientWidth,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      };
    });
    expect(geometry.documentOverflow, path).toBeLessThanOrEqual(0);
    expect(geometry.contentOverflow, path).toBeLessThanOrEqual(0);
  }

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/trading');
  const reviewQueueBox = (await page
    .getByTestId('trading-review-queue')
    .boundingBox())!;
  const safetyRailBox = (await page
    .getByTestId('trading-safety-rail')
    .boundingBox())!;
  expect(Math.abs(reviewQueueBox.x - safetyRailBox.x)).toBeLessThan(8);
  expect(Math.abs(reviewQueueBox.width - safetyRailBox.width)).toBeLessThan(8);
  expect(safetyRailBox.y).toBeGreaterThan(reviewQueueBox.y);
});

test('mobile trading review keeps one persisted order and its controlled actions in one bounded row', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/trading/orders**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 1,
          order_id: 'ORD-RESPONSIVE-AUDIT',
          timestamp: '2026-07-29T09:00:00+08:00',
          symbol: '600519',
          side: 'buy',
          order_type: 'limit',
          quantity: 100,
          price: 1720.25,
          intent_id: 'INT-RESPONSIVE-AUDIT',
          risk_decision_id: 'RISK-RESPONSIVE-AUDIT',
          execution_mode: 'manual',
          status: 'pending_confirm',
          payload_json:
            '{"intent_id":"INT-RESPONSIVE-AUDIT","risk_decision_id":"RISK-RESPONSIVE-AUDIT"}',
          note: null,
          created_at: '2026-07-29T09:00:00+08:00',
          updated_at: '2026-07-29T09:00:00+08:00',
        },
      ]),
    });
  });

  await page.goto('/trading');
  const row = page.getByTestId('trading-order-row-ORD-RESPONSIVE-AUDIT');
  await expect(row).toBeVisible();

  for (const theme of ['light', 'dark'] as const) {
    await selectMobileTheme(page, theme);
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await expect(
      page.getByRole('button', {
        name: /Confirm:.*600519|确认:.*600519/,
      }),
    ).toBeVisible();

    const geometry = await page.evaluate(() => {
      const content = document.querySelector(
        '.app-shell-content',
      ) as HTMLElement;
      const table = document.querySelector(
        '[data-testid="trading-review-queue"] table',
      ) as HTMLTableElement;
      const row = document.querySelector(
        '[data-testid="trading-order-row-ORD-RESPONSIVE-AUDIT"]',
      ) as HTMLTableRowElement;
      const bounds = row.getBoundingClientRect();
      return {
        contentOverflow: content.scrollWidth - content.clientWidth,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        undersizedTargets: Array.from(
          row.querySelectorAll<HTMLElement>('button,input'),
        )
          .map((target) => {
            const targetBounds = target.getBoundingClientRect();
            return {
              height: targetBounds.height,
              label:
                target.getAttribute('aria-label') ??
                target.textContent?.trim() ??
                target.tagName,
              width: targetBounds.width,
            };
          })
          .filter((target) => target.height < 44 || target.width < 44),
        tableOverflow: table.scrollWidth - table.clientWidth,
        rowLeft: bounds.left,
        rowRight: bounds.right,
      };
    });
    expect(geometry.documentOverflow, `${theme} document`).toBeLessThanOrEqual(
      0,
    );
    expect(geometry.contentOverflow, `${theme} content`).toBeLessThanOrEqual(0);
    expect(geometry.tableOverflow, `${theme} table`).toBeLessThanOrEqual(0);
    expect(geometry.undersizedTargets, `${theme} touch targets`).toEqual([]);
    expect(geometry.rowLeft, `${theme} row left`).toBeGreaterThanOrEqual(0);
    expect(geometry.rowRight, `${theme} row right`).toBeLessThanOrEqual(390);
  }
});

test('remaining phase-four routes stay overflow safe in Latte and Mocha', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });

  for (const theme of ['light', 'dark']) {
    for (const path of [
      '/activity',
      '/market',
      '/account-truth',
      '/trading',
      '/settings',
      '/backtest',
      '/ai-research',
    ]) {
      const backtestResultsResponse =
        path === '/backtest'
          ? page.waitForResponse(
              (response) =>
                response.request().method() === 'GET' &&
                response.url().endsWith('/api/backtest/results'),
            )
          : null;
      const activityEntriesResponse =
        path === '/activity'
          ? page.waitForResponse(
              (response) =>
                response.request().method() === 'GET' &&
                new URL(response.url()).pathname === '/api/ledger/entries',
            )
          : null;
      await page.goto(path);
      let hasSavedResults = false;
      let hasActivityEntries = false;
      if (backtestResultsResponse) {
        const response = await backtestResultsResponse;
        expect(response.ok()).toBe(true);
        const savedResults = (await response.json()) as unknown;
        hasSavedResults =
          Array.isArray(savedResults) && savedResults.length > 0;
      }
      if (activityEntriesResponse) {
        const response = await activityEntriesResponse;
        expect(response.ok()).toBe(true);
        const entries = (await response.json()) as unknown;
        hasActivityEntries = Array.isArray(entries) && entries.length > 0;
      }
      await selectMobileTheme(page, theme as 'light' | 'dark');

      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.locator('h1')).toHaveCount(1);

      const geometry = await page.evaluate(() => {
        const content = document.querySelector(
          '.app-shell-content',
        ) as HTMLElement;
        return {
          contentOverflow: content.scrollWidth - content.clientWidth,
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        };
      });
      expect(geometry.documentOverflow, `${path} ${theme}`).toBeLessThanOrEqual(
        0,
      );
      expect(geometry.contentOverflow, `${path} ${theme}`).toBeLessThanOrEqual(
        0,
      );

      if (path === '/ai-research') {
        await expect(
          page.getByTestId('ai-research-primary-canvas'),
        ).toBeVisible();
        await expect(page.getByTestId('ai-research-task-panel')).toBeVisible();
        const taskComposer = page.locator(
          'form[aria-labelledby="ai-research-composer-title"]',
        );
        await expect(taskComposer).toHaveCount(0);
        await page
          .getByRole('button', {
            name: /Draft research task|起草研究任务/,
          })
          .click();
        await expect(taskComposer).toBeVisible();
        const researchGeometry = await page.evaluate(() => {
          const panel = document.querySelector(
            '[data-testid="ai-research-task-panel"]',
          ) as HTMLElement;
          const form = panel.querySelector(
            'form[aria-labelledby="ai-research-composer-title"]',
          ) as HTMLFormElement;
          const reviewQueue = panel.querySelector(
            'section[aria-labelledby="ai-research-queue-title"]',
          ) as HTMLElement;
          const panelStyle = getComputedStyle(panel);
          return {
            formTop: form.getBoundingClientRect().top,
            panelBackground: panelStyle.backgroundColor,
            panelRadius: panelStyle.borderRadius,
            reviewQueueTop: reviewQueue.getBoundingClientRect().top,
          };
        });
        expect(researchGeometry.reviewQueueTop).toBeLessThan(
          researchGeometry.formTop,
        );
        expect(researchGeometry.panelBackground).toBe('rgba(0, 0, 0, 0)');
        expect(researchGeometry.panelRadius).toBe('0px');
      }

      if (path === '/activity') {
        const historySurface = page.locator(
          '[data-activity-surface="audit-history"]',
        );
        const legacyEntrySurface = page.locator(
          '[data-activity-surface="priority-and-entry"]',
        );
        const entryTrigger = page
          .getByRole('button', { name: /New entry|新增流水/ })
          .first();
        await expect(historySurface).toBeVisible();
        await expect(legacyEntrySurface).toHaveCount(0);
        await expect(entryTrigger).toBeVisible();
        if (hasActivityEntries) {
          await expect(historySurface.locator('[role="region"]')).toBeVisible();
          await expect(page.getByTestId('activity-history-empty')).toHaveCount(
            0,
          );
        } else {
          await expect(
            page.getByTestId('activity-history-empty'),
          ).toBeVisible();
          await expect(historySurface.locator('[role="region"]')).toHaveCount(
            0,
          );
        }
        const activityGeometry = await page.evaluate(() => {
          const historyRegion = document.querySelector(
            '[data-activity-surface="audit-history"] [role="region"]',
          ) as HTMLElement | null;
          const categoryFilter = document.querySelector(
            '[aria-label="Ledger category filter"], [aria-label="流水分类筛选"]',
          ) as HTMLElement | null;
          const historyTable = historyRegion?.querySelector('table');
          const entryButton = Array.from(
            document.querySelectorAll('button'),
          ).find((button) =>
            /^(New entry|新增流水)$/.test(button.textContent?.trim() ?? ''),
          );
          return {
            historyRegionHeight:
              historyRegion?.getBoundingClientRect().height ?? null,
            categoryFilterHeight:
              categoryFilter?.getBoundingClientRect().height ?? null,
            categoryFilterLocalOverflow:
              categoryFilter === null
                ? null
                : categoryFilter.scrollWidth - categoryFilter.clientWidth,
            historyTableTop: historyTable?.getBoundingClientRect().top ?? null,
            triggerHeight: entryButton?.getBoundingClientRect().height ?? null,
            viewportHeight: window.innerHeight,
          };
        });
        if (hasActivityEntries) {
          expect(
            activityGeometry.historyRegionHeight ?? Number.POSITIVE_INFINITY,
            theme,
          ).toBeLessThanOrEqual(activityGeometry.viewportHeight * 0.8);
          expect(activityGeometry.categoryFilterHeight, theme).not.toBeNull();
          expect(
            activityGeometry.categoryFilterHeight ?? Number.POSITIVE_INFINITY,
            theme,
          ).toBeLessThanOrEqual(48);
          expect(
            activityGeometry.categoryFilterLocalOverflow ?? -1,
            theme,
          ).toBeGreaterThanOrEqual(0);
          expect(activityGeometry.historyTableTop, theme).not.toBeNull();
          expect(
            activityGeometry.historyTableTop ?? Number.POSITIVE_INFINITY,
          ).toBeLessThan(activityGeometry.viewportHeight * 0.9);
        } else {
          expect(activityGeometry.historyRegionHeight, theme).toBeNull();
          expect(activityGeometry.categoryFilterHeight, theme).toBeNull();
          expect(activityGeometry.historyTableTop, theme).toBeNull();
        }
        expect(activityGeometry.triggerHeight, theme).not.toBeNull();
        expect(
          activityGeometry.triggerHeight ?? 0,
          theme,
        ).toBeGreaterThanOrEqual(44);

        await entryTrigger.click();
        const entryDialog = page.getByRole('dialog', {
          name: /New entry|新增流水/,
        });
        await expect(entryDialog).toBeVisible();
        const drawerGeometry = await entryDialog.evaluate((dialog) => {
          const controls = Array.from(
            dialog.querySelectorAll(
              '[aria-label="Ledger entry tool selector"] button, [aria-label="流水录入工具选择"] button',
            ),
          ) as HTMLElement[];
          const bounds = dialog.getBoundingClientRect();
          return {
            bottom: bounds.bottom,
            left: bounds.left,
            minControlHeight: Math.min(
              ...controls.map(
                (control) => control.getBoundingClientRect().height,
              ),
            ),
            right: bounds.right,
            top: bounds.top,
            viewportHeight: window.innerHeight,
            viewportWidth: window.innerWidth,
          };
        });
        expect(drawerGeometry.left, theme).toBeGreaterThanOrEqual(0);
        expect(drawerGeometry.top, theme).toBeGreaterThanOrEqual(0);
        expect(drawerGeometry.right, theme).toBeLessThanOrEqual(
          drawerGeometry.viewportWidth,
        );
        expect(drawerGeometry.bottom, theme).toBeLessThanOrEqual(
          drawerGeometry.viewportHeight,
        );
        expect(drawerGeometry.minControlHeight, theme).toBeGreaterThanOrEqual(
          44,
        );
        await entryDialog
          .getByRole('button', {
            name: /Close entry tools|关闭流水录入/,
          })
          .click();
        await expect(entryDialog).toHaveCount(0);
      }

      if (path === '/backtest') {
        const resultTab = page
          .getByTestId('backtest-mobile-workspace-tabs')
          .getByRole('tab', {
            name: /Results and evidence|结果与证据/,
          });
        await expect(resultTab).toHaveAttribute(
          'aria-selected',
          hasSavedResults ? 'true' : 'false',
        );
        if (!hasSavedResults) {
          await resultTab.click();
        }
        await expect(resultTab).toHaveAttribute('aria-selected', 'true');
        const resultPanel = page.getByTestId('backtest-result-panel');
        await expect(resultPanel).toBeVisible();
        const reportWorkspace = resultPanel.locator(
          '[data-backtest-report-workspace="saved-evidence"]',
        );
        await expect
          .poll(
            () =>
              resultPanel.evaluate((element) => {
                const workspace = element.querySelector(
                  '[data-backtest-report-workspace="saved-evidence"]',
                );
                const visibleEmpty = Array.from(
                  element.querySelectorAll('[data-evidence-kind="empty"]'),
                ).some(
                  (state) =>
                    (state as HTMLElement).getBoundingClientRect().height > 0,
                );
                return Boolean(workspace) || visibleEmpty;
              }),
            { timeout: 15_000 },
          )
          .toBe(true);
        if ((await reportWorkspace.count()) > 0) {
          await expect(
            reportWorkspace.locator('[data-workbench-primitive="filter-bar"]'),
          ).toHaveCount(1);
          await expect(
            reportWorkspace.locator(
              '[data-workbench-primitive="metric-strip"]',
            ),
          ).toHaveCount(2, { timeout: 15_000 });
          for (const testId of [
            'backtest-validation-disclosure',
            'backtest-dataset-disclosure',
            'backtest-strategy-evidence-disclosure',
            'backtest-fills-disclosure',
          ]) {
            await expect(
              reportWorkspace.getByTestId(testId),
            ).not.toHaveAttribute('open', '');
          }
          const validationDisclosure = reportWorkspace.getByTestId(
            'backtest-validation-disclosure',
          );
          const validationSummary = validationDisclosure.locator('summary');
          await validationSummary.press('Enter');
          await expect(validationDisclosure).toHaveAttribute('open', '');
          await expect(
            validationDisclosure.getByText(
              /After-cost evidence|扣除成本后证据/,
              { exact: true },
            ),
          ).toBeVisible();
          await validationSummary.press('Enter');
          await expect(validationDisclosure).not.toHaveAttribute('open', '');
          const reportGeometry = await reportWorkspace.evaluate((element) => ({
            chartTop:
              element
                .querySelector('[data-testid="backtest-equity-chart-frame"]')
                ?.getBoundingClientRect().top ?? null,
            legacyPanels: element.querySelectorAll(
              '.app-panel,.app-panel-strong',
            ).length,
            oversizedRadii: element.querySelectorAll('.rounded-2xl').length,
            viewportHeight: window.innerHeight,
            width: element.getBoundingClientRect().width,
            workspaceTop: element.getBoundingClientRect().top,
          }));
          expect(reportGeometry.legacyPanels, theme).toBe(0);
          expect(reportGeometry.oversizedRadii, theme).toBe(0);
          expect(reportGeometry.width, theme).toBeLessThanOrEqual(390);
          if (reportGeometry.chartTop !== null) {
            expect(
              reportGeometry.chartTop - reportGeometry.workspaceTop,
              theme,
            ).toBeLessThanOrEqual(reportGeometry.viewportHeight * 0.75);
          }
        }

        const archiveDisclosure = page.getByTestId(
          'backtest-research-archive-disclosure',
        );
        await archiveDisclosure.click();
        await expect(archiveDisclosure).toHaveAttribute(
          'aria-expanded',
          'true',
        );

        await expect(
          page.locator('#backtest-research-archive').getByRole('region'),
        ).toBeVisible();
      }
    }
  }
});

test('brand motion keeps route and mobile drawer timing coherent', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/overview');

  const route = page.locator('.app-route-stage');
  await expect(route).toBeVisible();
  const routeMotion = await route.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      duration: style.animationDuration,
      easing: style.animationTimingFunction,
      name: style.animationName,
    };
  });
  expect(routeMotion).toEqual({
    duration: '0.32s',
    easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    name: 'app-route-enter',
  });
  const nestedRouteReveals = await route.evaluate((element) =>
    element.getAnimations({ subtree: true }).flatMap((animation) => {
      const effect = animation.effect;
      if (!(effect instanceof KeyframeEffect) || effect.target === element) {
        return [];
      }
      const name =
        animation instanceof CSSAnimation ? animation.animationName : '';
      return name === 'app-content-enter' || name === 'app-chart-enter'
        ? [name]
        : [];
    }),
  );
  expect(nestedRouteReveals).toEqual([]);

  await page.getByTestId('workspace-command-trigger').click();
  const commandBackdrop = page.locator('.app-command-backdrop');
  const commandPanel = page.locator('.app-command-panel');
  await expect(commandBackdrop).toHaveAttribute('data-motion-state', 'open');
  await expect(commandPanel).toBeVisible();
  const commandEnter = await commandPanel.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      duration: style.animationDuration,
      easing: style.animationTimingFunction,
      name: style.animationName,
    };
  });
  expect(commandEnter).toEqual({
    duration: '0.24s',
    easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
    name: 'app-overlay-enter',
  });
  await page.getByRole('button', { name: /Close command menu/ }).click();
  await expect(commandBackdrop).toHaveAttribute('data-motion-state', 'closing');
  const commandExit = await commandPanel.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      duration: style.animationDuration,
      easing: style.animationTimingFunction,
      name: style.animationName,
    };
  });
  expect(commandExit).toEqual({
    duration: '0.18s',
    easing: 'cubic-bezier(0.4, 0, 1, 1)',
    name: 'app-overlay-exit',
  });
  await expect(commandBackdrop).toHaveCount(0);

  await page.goto('/');
  const publicEvidenceFrame = page.locator('.app-public-evidence-frame');
  await expect(publicEvidenceFrame).toBeVisible();
  const nestedPublicReveals = await publicEvidenceFrame.evaluate((element) =>
    element.getAnimations({ subtree: true }).flatMap((animation) => {
      const effect = animation.effect;
      if (!(effect instanceof KeyframeEffect) || effect.target === element) {
        return [];
      }
      return animation instanceof CSSAnimation ? [animation.animationName] : [];
    }),
  );
  expect(nestedPublicReveals).toEqual([]);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/overview');
  await page.getByTestId('mobile-navigation-toggle').click();

  const sidebar = page.locator('.app-shell-sidebar');
  await expect(sidebar).toHaveAttribute('data-mobile-open', 'true');
  const drawerMotion = await sidebar.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      delay: style.transitionDelay,
      duration: style.transitionDuration,
      easing: style.transitionTimingFunction,
      property: style.transitionProperty,
    };
  });
  expect(drawerMotion.property).toBe('transform, visibility');
  expect(drawerMotion.duration).toBe('0.24s, 0s');
  expect(drawerMotion.delay).toBe('0s, 0s');
  expect(drawerMotion.easing).toBe('cubic-bezier(0.16, 1, 0.3, 1), linear');

  await sidebar
    .getByRole('button', { name: 'Close navigation', exact: true })
    .click();
  await expect(sidebar).toHaveAttribute('data-mobile-open', 'false');
  await expect(sidebar).toHaveCSS('visibility', 'hidden');
  const drawerExit = await sidebar.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      delay: style.transitionDelay,
      duration: style.transitionDuration,
      easing: style.transitionTimingFunction,
      property: style.transitionProperty,
      visibility: style.visibility,
    };
  });
  expect(drawerExit).toEqual({
    delay: '0s, 0.24s',
    duration: '0.24s, 0s',
    easing: 'cubic-bezier(0.4, 0, 1, 1), linear',
    property: 'transform, visibility',
    visibility: 'hidden',
  });
});

test('dense return evidence stays spatially stable through hover and selection', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.route('**/api/portfolio/explainability**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        equity_bridge: [],
        recent_drivers: [],
        positions: [],
        timeline: [
          {
            date: '2026-02-10',
            equity: 101_000,
            delta: 800,
            external_flow: 200,
            market_pnl: 600,
            events: [],
          },
        ],
      }),
    });
  });
  await page.goto('/overview');

  const calendarTab = page.getByRole('tab', {
    name: /Return calendar|收益日历/,
  });
  await expect(calendarTab).toBeVisible({ timeout: 30_000 });
  await calendarTab.click();

  const cell = page
    .getByTestId('return-calendar-month-grid')
    .getByRole('button')
    .first();
  await expect(cell).toBeVisible();
  const grid = page.getByTestId('return-calendar-month-grid');
  const localGeometry = async () => {
    const [cellBox, gridBox] = await Promise.all([
      cell.boundingBox(),
      grid.boundingBox(),
    ]);
    if (!cellBox || !gridBox) {
      throw new Error('Return calendar geometry is unavailable');
    }
    return {
      height: cellBox.height,
      localY: cellBox.y - gridBox.y,
      width: cellBox.width,
    };
  };
  const initialGeometry = await localGeometry();
  const transitionProperties = await cell.evaluate(
    (element) => getComputedStyle(element).transitionProperty,
  );
  expect(transitionProperties).not.toMatch(/transform|translate/);

  await cell.hover();
  await page.waitForTimeout(150);
  const hoverGeometry = await localGeometry();
  expect(hoverGeometry).toEqual(initialGeometry);

  await cell.click();
  await expect(cell).toHaveAttribute('aria-pressed', 'true');
  const selectedGeometry = await localGeometry();
  expect(selectedGeometry).toEqual(initialGeometry);
});

test('reduced-motion preference removes branded and routine transition timing', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/backtest');

  const tab = page
    .getByTestId('backtest-mobile-workspace-tabs')
    .getByRole('tab')
    .first();
  await expect(tab).toBeVisible();
  const transitionDuration = await tab.evaluate(
    (element) => getComputedStyle(element).transitionDuration,
  );
  expect(Number.parseFloat(transitionDuration)).toBeLessThanOrEqual(0.001);

  await page.goto('/overview');
  const route = page.locator('.app-route-stage');
  await expect(route).toBeVisible();
  const routeDuration = await route.evaluate(
    (element) => getComputedStyle(element).animationDuration,
  );
  expect(Number.parseFloat(routeDuration)).toBeLessThanOrEqual(0.001);

  await page.getByTestId('mobile-navigation-toggle').click();
  const sidebar = page.locator('.app-shell-sidebar');
  await expect(sidebar).toHaveAttribute('data-mobile-open', 'true');
  const sidebarDurations = await sidebar.evaluate((element) =>
    getComputedStyle(element)
      .transitionDuration.split(',')
      .map((duration) => Number.parseFloat(duration)),
  );
  expect(Math.max(...sidebarDurations)).toBeLessThanOrEqual(0.001);
});
