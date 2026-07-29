import { expect, test } from '@playwright/test';

const acceptanceViewports = [
  { width: 1440, height: 900 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 834, height: 1112 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];

const headlessSubpixelTolerance = 1;

test('Operations keeps pilot readiness and subsystem metrics visibly scoped', async ({
  page,
}) => {
  test.setTimeout(60_000);

  for (const theme of ['light', 'dark'] as const) {
    await page.setViewportSize(acceptanceViewports[0]);
    await page.goto('/operations');
    await page.evaluate((nextTheme) => {
      window.localStorage.setItem('karkinos.theme', nextTheme);
    }, theme);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);

    const metrics = page.locator(
      '[data-testid="operations-page"] > .app-metric-strip',
    );
    await expect(metrics).toBeVisible({ timeout: 15_000 });
    const readiness = page.getByTestId('controlled-pilot-readiness');
    await expect(readiness).toBeVisible();
    await expect(readiness).not.toHaveAttribute('open', '');
    await expect(readiness).toContainText('Prerequisites unmet');

    for (const viewport of acceptanceViewports) {
      await page.setViewportSize(viewport);
      const geometry = await metrics.evaluate((element) => {
        const before = getComputedStyle(element, '::before');
        const readiness = document.querySelector(
          '[data-testid="controlled-pilot-readiness"]',
        );
        return {
          ariaLabel: element.getAttribute('aria-label'),
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
          metricOverflow: element.scrollWidth - element.clientWidth,
          labelContent: before.content.replace(/^['"]|['"]$/g, ''),
          columnCount:
            getComputedStyle(element).gridTemplateColumns.split(' ').length,
          readinessBeforeMetrics:
            readiness === null ||
            readiness.getBoundingClientRect().bottom <=
              element.getBoundingClientRect().top,
        };
      });

      expect(geometry.labelContent, `${theme} ${viewport.width}`).toBe(
        geometry.ariaLabel,
      );
      expect(
        geometry.documentOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);
      expect(
        geometry.metricOverflow,
        `${theme} ${viewport.width}`,
      ).toBeLessThanOrEqual(0);
      expect(geometry.columnCount, `${theme} ${viewport.width}`).toBe(
        viewport.width < 640 ? 2 : 4,
      );
      expect(
        geometry.readinessBeforeMetrics,
        `${theme} ${viewport.width}`,
      ).toBe(true);
    }

    await page.setViewportSize(acceptanceViewports.at(-1)!);
    await readiness.locator('summary').click();
    await expect(readiness).toHaveAttribute('open', '');
    await expect(readiness).not.toContainText('Status needs review');
    const expandedGeometry = await readiness.evaluate((element) => ({
      localOverflow: element.scrollWidth - element.clientWidth,
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    }));
    expect(
      expandedGeometry.localOverflow,
      `${theme} expanded`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      expandedGeometry.documentOverflow,
      `${theme} expanded`,
    ).toBeLessThanOrEqual(0);
  }
});
