import { expect, test } from '@playwright/test';

test('trading mobile keeps the review task ahead of secondary filters', async ({
  page,
}) => {
  test.setTimeout(60_000);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/trading');

  const secondaryFilters = page.getByTestId('trading-secondary-filters');
  const symbolFilter = page.locator('[name="trading-symbol-filter"]');
  const reviewQueue = page.getByTestId('trading-review-queue');
  const metrics = page.locator('[data-workbench-primitive="metric-strip"]');
  const killSwitch = page.getByTestId('kill-switch-panel');

  await expect(secondaryFilters).not.toHaveAttribute('open', '');
  await expect(symbolFilter).toBeHidden();
  await expect(reviewQueue).toBeVisible();
  await expect(killSwitch).toHaveAttribute(
    'data-kill-switch-state',
    'inactive',
  );
  await expect(killSwitch).not.toHaveAttribute('open', '');

  const taskSurface = reviewQueue
    .locator('[data-evidence-kind], table')
    .first();
  await expect(taskSurface).toBeInViewport();

  await secondaryFilters.locator('summary').click();
  await expect(secondaryFilters).toHaveAttribute('open', '');
  await expect(symbolFilter).toBeVisible();

  const geometry = await page.evaluate(() => {
    const queue = document.querySelector(
      '[data-testid="trading-review-queue"]',
    ) as HTMLElement;
    const control = document.querySelector(
      '[data-testid="kill-switch-panel"]',
    ) as HTMLElement;
    return {
      viewportWidth: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      queueTop: queue.getBoundingClientRect().top,
      metricsTop: (
        document.querySelector(
          '[data-workbench-primitive="metric-strip"]',
        ) as HTMLElement
      ).getBoundingClientRect().top,
      controlTop: control.getBoundingClientRect().top,
      controlHeight: control.getBoundingClientRect().height,
    };
  });
  expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);
  await expect(metrics).toBeVisible();
  expect(geometry.queueTop).toBeLessThan(geometry.metricsTop);
  expect(geometry.queueTop).toBeLessThan(geometry.controlTop);
  expect(geometry.controlHeight).toBeLessThan(120);
});
