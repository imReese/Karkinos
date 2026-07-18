import { expect, test } from '@playwright/test';

test('exemplar pages keep one evidence-first desktop reading path', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.goto('/');
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
  expect((await overviewPerformance.boundingBox())!.y).toBeGreaterThan(
    Math.min(
      (await overviewQueue.boundingBox())!.y,
      (await overviewHoldings.boundingBox())!.y,
    ),
  );

  await page.goto('/risk');
  const blockingRegister = page.getByTestId('risk-blocking-register');
  const riskMetrics = page.locator('[data-workbench-primitive="metric-strip"]');
  const thresholdTable = page.getByTestId('risk-threshold-table');
  const controlledActions = page.getByTestId('risk-trading-control-grid');
  await expect(blockingRegister).toBeVisible();
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

test('exemplar routes remain task-reordered and overflow safe on mobile themes', async ({
  page,
}) => {
  test.setTimeout(90_000);

  for (const theme of ['light', 'dark']) {
    for (const path of ['/', '/portfolio', '/risk', '/backtest']) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(path);
      await page
        .getByRole('button', {
          name:
            theme === 'light' ? /Light theme|浅色主题/ : /Dark theme|深色主题/,
        })
        .click();

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
