import { expect, test, type Page } from '@playwright/test';

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

test('exemplar pages keep one evidence-first desktop reading path', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto('/overview');
  const overviewPrimary = page.getByTestId('overview-daily-workbench');
  const overviewQueue = page.getByTestId('overview-today-queue');
  const overviewHoldings = page.getByTestId('overview-holdings-section');
  const overviewPerformance = page.getByTestId('overview-performance-card');
  await expect(overviewPrimary).toBeVisible();
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
  const riskMetrics = page.locator('[data-workbench-primitive="metric-strip"]');
  const thresholdTable = page.getByTestId('risk-threshold-table');
  const controlledActions = page.getByTestId('risk-trading-control-grid');
  await expect(blockingRegister).toBeVisible({ timeout: 15_000 });
  expect((await blockingRegister.boundingBox())!.y).toBeLessThan(
    (await riskMetrics.boundingBox())!.y,
  );
  expect((await thresholdTable.boundingBox())!.y).toBeLessThan(
    (await controlledActions.boundingBox())!.y,
  );

  await page.goto('/backtest');
  const primaryResearch = page.getByTestId('backtest-primary-workbench');
  const parameterPanel = page.getByTestId('backtest-parameter-panel');
  const resultPanel = page.getByTestId('backtest-result-panel');
  await expect(primaryResearch).toBeVisible();
  expect((await parameterPanel.boundingBox())!.x).toBeLessThan(
    (await resultPanel.boundingBox())!.x,
  );
  await expect(page.getByTestId('backtest-mobile-workspace-tabs')).toBeHidden();
});

test('portfolio keeps filtering ordered and wide holdings locally scrollable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/portfolio');

  const filterBar = page.locator('[data-workbench-primitive="filter-bar"]');
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
    return {
      contentOverflow: content.scrollWidth - content.clientWidth,
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      tableOverflow: tableShell
        ? tableShell.scrollWidth - tableShell.clientWidth
        : 0,
    };
  });
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.contentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.tableOverflow).toBeGreaterThanOrEqual(0);
});

test('portfolio mobile keeps secondary filters disclosed on demand', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/portfolio');

  const filterBar = page.locator('[data-workbench-primitive="filter-bar"]');
  const moreFilters = filterBar.locator(
    'button[aria-controls="portfolio-secondary-filters"]',
  );
  const holdingsSurface = page
    .getByTestId('portfolio-current-holdings-count')
    .locator('xpath=following-sibling::*[1]');

  await expect(moreFilters).toBeVisible();
  await expect(filterBar.locator('select:visible')).toHaveCount(2);
  await expect(moreFilters).toHaveAttribute('aria-expanded', 'false');
  await expect(holdingsSurface).toBeVisible();

  const compactControlHeights = await filterBar
    .locator('button:visible, input:visible, select:visible')
    .evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().height),
    );
  expect(Math.min(...compactControlHeights)).toBeGreaterThanOrEqual(40);
  const collapsedHoldingsTop = (await holdingsSurface.boundingBox())!.y;

  await moreFilters.click();

  await expect(moreFilters).toHaveAttribute('aria-expanded', 'true');
  await expect(filterBar.locator('select:visible')).toHaveCount(5);
  const expandedHoldingsTop = (await holdingsSurface.boundingBox())!.y;
  expect(collapsedHoldingsTop).toBeLessThan(expandedHoldingsTop);

  const documentOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBeLessThanOrEqual(0);
});

test('exemplar routes remain task-reordered and overflow safe on mobile themes', async ({
  page,
}) => {
  test.setTimeout(90_000);

  for (const theme of ['light', 'dark']) {
    for (const path of ['/overview', '/portfolio', '/risk', '/backtest']) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(path);
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
      expect(geometry.contentOverflow, `${path} ${theme}`).toBeLessThanOrEqual(
        0,
      );

      if (path === '/backtest') {
        const tabs = page.getByTestId('backtest-mobile-workspace-tabs');
        await expect(tabs).toBeVisible();
        await tabs.getByRole('tab', { name: /Current run|当前运行/ }).click();
        await expect(page.getByTestId('backtest-result-panel')).toBeVisible();
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
  await expect(
    page.locator('[data-testid^="decision-candidate-card-"]'),
  ).toHaveCount(0);

  await page.goto('/trading');
  await expect(
    page.getByRole('heading', { name: /Trading review|交易复核/ }),
  ).toBeVisible();
  await expect(page.getByTestId('kill-switch-panel')).toBeVisible();
  await expect(
    page.getByTestId('trading-broker-boundary-disclosure'),
  ).not.toHaveAttribute('open', '');

  await page.goto('/settings');
  await expect(
    page.getByRole('heading', { name: /Control center|控制中心/ }),
  ).toBeVisible();
  for (const testId of [
    'settings-data-source-disclosure',
    'settings-backend-disclosure',
    'settings-notifications-disclosure',
  ]) {
    await expect(page.getByTestId(testId)).not.toHaveAttribute('open', '');
  }

  await page.goto('/backtest');
  await expect(
    page.getByRole('heading', { name: /Strategy replay|策略回放/ }),
  ).toBeVisible();
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
    ]) {
      await page.goto(path);
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

      if (path === '/activity') {
        const activityGeometry = await page.evaluate(() => {
          const entrySurface = document.querySelector(
            '[data-activity-surface="priority-and-entry"]',
          ) as HTMLElement;
          const historySurface = document.querySelector(
            '[data-activity-surface="audit-history"]',
          ) as HTMLElement;
          const historyRegion = historySurface.querySelector(
            '[role="region"]',
          ) as HTMLElement | null;
          const controls = Array.from(
            document.querySelectorAll(
              '[aria-label="Ledger entry tool selector"] button, [aria-label="流水录入工具选择"] button',
            ),
          ) as HTMLElement[];
          return {
            entryTop: entrySurface.getBoundingClientRect().top,
            historyTop: historySurface.getBoundingClientRect().top,
            historyRegionHeight:
              historyRegion?.getBoundingClientRect().height ?? null,
            viewportHeight: window.innerHeight,
            minControlHeight: Math.min(
              ...controls.map(
                (control) => control.getBoundingClientRect().height,
              ),
            ),
          };
        });
        expect(activityGeometry.historyTop, theme).toBeLessThan(
          activityGeometry.entryTop,
        );
        expect(
          activityGeometry.entryTop - activityGeometry.historyTop,
        ).toBeLessThanOrEqual(activityGeometry.viewportHeight * 1.2);
        if (activityGeometry.historyRegionHeight !== null) {
          expect(
            activityGeometry.historyRegionHeight,
            theme,
          ).toBeLessThanOrEqual(activityGeometry.viewportHeight * 0.8);
        }
        expect(activityGeometry.minControlHeight, theme).toBeGreaterThanOrEqual(
          40,
        );
      }

      if (path === '/backtest') {
        const archiveDisclosure = page.getByTestId(
          'backtest-research-archive-disclosure',
        );
        await archiveDisclosure.click();
        await expect(archiveDisclosure).toHaveAttribute(
          'aria-expanded',
          'true',
        );

        const archiveContent = page.locator('#backtest-research-archive');
        await expect
          .poll(
            () =>
              archiveContent.evaluate((element) => {
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
        const reportWorkspace = archiveContent.locator(
          '[data-backtest-report-workspace="saved-evidence"]',
        );
        if ((await reportWorkspace.count()) > 0) {
          await expect(
            reportWorkspace.locator('[data-workbench-primitive="filter-bar"]'),
          ).toHaveCount(1);
          await expect(
            reportWorkspace.locator(
              '[data-workbench-primitive="metric-strip"]',
            ),
          ).toHaveCount(3);
          const reportGeometry = await reportWorkspace.evaluate((element) => ({
            legacyPanels: element.querySelectorAll(
              '.app-panel,.app-panel-strong',
            ).length,
            oversizedRadii: element.querySelectorAll('.rounded-2xl').length,
            width: element.getBoundingClientRect().width,
          }));
          expect(reportGeometry.legacyPanels, theme).toBe(0);
          expect(reportGeometry.oversizedRadii, theme).toBe(0);
          expect(reportGeometry.width, theme).toBeLessThanOrEqual(390);
        } else {
          const visibleEmptyStateCount = await archiveContent
            .locator('[data-evidence-kind="empty"]')
            .evaluateAll(
              (elements) =>
                elements.filter(
                  (element) =>
                    (element as HTMLElement).getBoundingClientRect().height > 0,
                ).length,
            );
          expect(visibleEmptyStateCount, theme).toBeGreaterThan(0);
        }
      }
    }
  }
});

test('reduced-motion preference removes routine transition timing', async ({
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
});
