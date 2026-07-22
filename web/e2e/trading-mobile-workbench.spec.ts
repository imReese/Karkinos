import { expect, test } from '@playwright/test';

test('trading mobile keeps the review task ahead of secondary filters', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/trading');

  const secondaryFilters = page.getByTestId('trading-secondary-filters');
  const symbolFilter = page.locator('[name="trading-symbol-filter"]');
  const reviewQueue = page.getByTestId('trading-review-queue');

  await expect(secondaryFilters).not.toHaveAttribute('open', '');
  await expect(symbolFilter).toBeHidden();
  await expect(reviewQueue).toBeVisible();

  const taskSurface = reviewQueue
    .locator('[data-evidence-kind], table')
    .first();
  await expect(taskSurface).toBeInViewport();

  await secondaryFilters.locator('summary').click();
  await expect(secondaryFilters).toHaveAttribute('open', '');
  await expect(symbolFilter).toBeVisible();

  const geometry = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);
});
