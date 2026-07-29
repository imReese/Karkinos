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

    const commandGrid = page.getByTestId('operations-command-grid');
    const attentionQueue = page.getByTestId('operations-attention-queue');
    await readiness.locator('summary').click();
    await expect(readiness).toHaveAttribute('open', '');
    const desktopExpandedGeometry = await commandGrid.evaluate((element) => {
      const attentionQueue = element.querySelector(
        '[data-testid="operations-attention-queue"]',
      ) as HTMLElement;
      const readiness = element.querySelector(
        '[data-testid="controlled-pilot-readiness"]',
      ) as HTMLElement;
      return {
        attentionWidth: attentionQueue.getBoundingClientRect().width,
        columnCount:
          getComputedStyle(element).gridTemplateColumns.split(' ').length,
        gridWidth: element.getBoundingClientRect().width,
        pilotBelowAttention:
          readiness.getBoundingClientRect().top >=
          attentionQueue.getBoundingClientRect().bottom,
        pilotWidth: readiness.getBoundingClientRect().width,
      };
    });
    expect(
      desktopExpandedGeometry.columnCount,
      `${theme} expanded desktop`,
    ).toBe(1);
    expect(
      Math.abs(
        desktopExpandedGeometry.attentionWidth -
          desktopExpandedGeometry.gridWidth,
      ),
      `${theme} expanded desktop attention width`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      Math.abs(
        desktopExpandedGeometry.pilotWidth - desktopExpandedGeometry.gridWidth,
      ),
      `${theme} expanded desktop pilot width`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      desktopExpandedGeometry.pilotBelowAttention,
      `${theme} expanded desktop order`,
    ).toBe(true);
    await expect(attentionQueue).toBeVisible();
    await readiness.locator('summary').click();
    await expect(readiness).not.toHaveAttribute('open', '');

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
