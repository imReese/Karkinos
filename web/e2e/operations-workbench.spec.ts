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

    const healthOverview = page.getByTestId('operations-health-overview');
    const metrics = healthOverview.locator('.app-metric-strip');
    await expect(metrics).toBeVisible({ timeout: 15_000 });
    await expect(
      healthOverview.getByRole('heading', { name: 'Health overview' }),
    ).toBeVisible();
    const readiness = page.getByTestId('controlled-pilot-readiness');
    await expect(readiness).toBeVisible();
    await expect(readiness).not.toHaveAttribute('open', '');
    await expect(readiness).toContainText('Prerequisites unmet');

    const commandGrid = page.getByTestId('operations-command-grid');
    const attentionQueue = page.getByTestId('operations-attention-queue');
    await readiness.locator(':scope > summary').click();
    await expect(readiness).toHaveAttribute('open', '');
    const desktopExpandedGeometry = await commandGrid.evaluate((element) => {
      const attentionQueue = element.querySelector(
        '[data-testid="operations-attention-queue"]',
      ) as HTMLElement;
      const readiness = element.querySelector(
        '[data-testid="controlled-pilot-readiness"]',
      ) as HTMLElement;
      const healthOverview = element.querySelector(
        '[data-testid="operations-health-overview"]',
      ) as HTMLElement;
      return {
        attentionWidth: attentionQueue.getBoundingClientRect().width,
        columnCount:
          getComputedStyle(element).gridTemplateColumns.split(' ').length,
        gridWidth: element.getBoundingClientRect().width,
        healthAlignedWithAttention:
          Math.abs(
            healthOverview.getBoundingClientRect().top -
              attentionQueue.getBoundingClientRect().top,
          ) < 8,
        pilotBelowPrimary:
          readiness.getBoundingClientRect().top >=
          Math.max(
            attentionQueue.getBoundingClientRect().bottom,
            healthOverview.getBoundingClientRect().bottom,
          ),
        pilotWidth: readiness.getBoundingClientRect().width,
      };
    });
    expect(
      desktopExpandedGeometry.columnCount,
      `${theme} expanded desktop`,
    ).toBe(2);
    expect(
      desktopExpandedGeometry.attentionWidth,
      `${theme} expanded desktop attention width`,
    ).toBeLessThan(desktopExpandedGeometry.gridWidth);
    expect(
      Math.abs(
        desktopExpandedGeometry.pilotWidth - desktopExpandedGeometry.gridWidth,
      ),
      `${theme} expanded desktop pilot width`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      desktopExpandedGeometry.healthAlignedWithAttention,
      `${theme} expanded desktop health alignment`,
    ).toBe(true);
    expect(
      desktopExpandedGeometry.pilotBelowPrimary,
      `${theme} expanded desktop order`,
    ).toBe(true);
    await expect(attentionQueue).toBeVisible();
    await readiness.locator(':scope > summary').click();
    await expect(readiness).not.toHaveAttribute('open', '');

    for (const viewport of acceptanceViewports) {
      await page.setViewportSize(viewport);
      const geometry = await metrics.evaluate((element) => {
        const commandGrid = document.querySelector(
          '[data-testid="operations-command-grid"]',
        ) as HTMLElement;
        const attentionQueue = document.querySelector(
          '[data-testid="operations-attention-queue"]',
        ) as HTMLElement;
        const readiness = document.querySelector(
          '[data-testid="controlled-pilot-readiness"]',
        ) as HTMLElement;
        const healthOverview = document.querySelector(
          '[data-testid="operations-health-overview"]',
        ) as HTMLElement;
        const healthHeading = healthOverview.querySelector('h2') as HTMLElement;
        const firstAttention = attentionQueue.querySelector('li');
        const fieldTops = firstAttention
          ? Object.fromEntries(
              Array.from(
                firstAttention.querySelectorAll<HTMLElement>(
                  '[data-evidence-field]',
                ),
              ).map((field) => [
                field.dataset.evidenceField,
                field.getBoundingClientRect().top,
              ]),
            )
          : {};
        return {
          ariaLabel: element.getAttribute('aria-label'),
          attentionWidthDelta:
            commandGrid.getBoundingClientRect().width -
            attentionQueue.getBoundingClientRect().width,
          commandColumnCount:
            getComputedStyle(commandGrid).gridTemplateColumns.split(' ').length,
          documentOverflow:
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
          fieldTops,
          firstAttentionExists: firstAttention !== null,
          healthAfterAttention:
            healthOverview.getBoundingClientRect().top >=
            attentionQueue.getBoundingClientRect().bottom,
          healthAlignedWithAttention:
            Math.abs(
              healthOverview.getBoundingClientRect().top -
                attentionQueue.getBoundingClientRect().top,
            ) < 8,
          healthHeading: healthHeading.textContent?.trim(),
          metricOverflow: element.scrollWidth - element.clientWidth,
          columnCount:
            getComputedStyle(element).gridTemplateColumns.split(' ').length,
          metricsBeforeReadiness:
            element.getBoundingClientRect().bottom <=
            readiness.getBoundingClientRect().top,
          pilotBelowPrimary:
            readiness.getBoundingClientRect().top >=
            Math.max(
              attentionQueue.getBoundingClientRect().bottom,
              healthOverview.getBoundingClientRect().bottom,
            ),
        };
      });

      expect(geometry.healthHeading, `${theme} ${viewport.width}`).toBe(
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
      expect(
        geometry.commandColumnCount,
        `${theme} ${viewport.width} command grid`,
      ).toBe(viewport.width >= 1280 ? 2 : 1);
      if (viewport.width < 1280) {
        expect(
          Math.abs(geometry.attentionWidthDelta),
          `${theme} ${viewport.width} attention width`,
        ).toBeLessThanOrEqual(headlessSubpixelTolerance);
        expect(
          geometry.healthAfterAttention,
          `${theme} ${viewport.width} health order`,
        ).toBe(true);
      } else {
        expect(
          geometry.healthAlignedWithAttention,
          `${theme} ${viewport.width} health alignment`,
        ).toBe(true);
      }
      expect(
        geometry.pilotBelowPrimary,
        `${theme} ${viewport.width} pilot order`,
      ).toBe(true);
      expect(geometry.columnCount, `${theme} ${viewport.width}`).toBe(2);
      expect(
        geometry.metricsBeforeReadiness,
        `${theme} ${viewport.width}`,
      ).toBe(true);
      if (viewport.width < 640 && geometry.firstAttentionExists) {
        expect(
          geometry.fieldTops['reason'],
          `${theme} ${viewport.width} evidence status row`,
        ).toBe(geometry.fieldTops['evidence']);
        expect(
          geometry.fieldTops['next-action'],
          `${theme} ${viewport.width} safe action order`,
        ).toBeLessThan(geometry.fieldTops['unblock-condition']);
      }
    }

    await page.setViewportSize(acceptanceViewports.at(-1)!);
    await readiness.locator(':scope > summary').click();
    await expect(readiness).toHaveAttribute('open', '');
    await expect(readiness).not.toContainText('Status needs review');
    const expandedGeometry = await readiness.evaluate((element) => {
      const content = element.querySelector(':scope > div') as HTMLElement;
      const gateMatrix = element.querySelector(
        '[data-workbench-primitive="gate-matrix"]',
      ) as HTMLElement;
      const summary = element.querySelector(':scope > summary') as HTMLElement;
      const summaryStyle = getComputedStyle(summary);
      const summaryRect = summary.getBoundingClientRect();
      const summaryChildRects = Array.from(summary.children).map((child) =>
        child.getBoundingClientRect(),
      );
      return {
        contentOverflow: content.scrollWidth - content.clientWidth,
        documentOverflow:
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
        gateMatrixOverflow: gateMatrix.scrollWidth - gateMatrix.clientWidth,
        summaryContentOverflow: Math.max(
          0,
          ...summaryChildRects.map((rect) => rect.right - summaryRect.right),
          ...summaryChildRects.map((rect) => summaryRect.left - rect.left),
        ),
        summaryGeometry: {
          childWidths: summaryChildRects.map(
            (rect) => Math.round(rect.width * 100) / 100,
          ),
          clientWidth: summary.clientWidth,
          display: summaryStyle.display,
          gap: summaryStyle.gap,
          listStyle: summaryStyle.listStyleType,
          rectWidth:
            Math.round(summary.getBoundingClientRect().width * 100) / 100,
          scrollWidth: summary.scrollWidth,
        },
      };
    });
    expect(
      expandedGeometry.contentOverflow,
      `${theme} expanded content`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      expandedGeometry.gateMatrixOverflow,
      `${theme} expanded gate matrix`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      expandedGeometry.summaryContentOverflow,
      `${theme} expanded summary content ${JSON.stringify(expandedGeometry.summaryGeometry)}`,
    ).toBeLessThanOrEqual(headlessSubpixelTolerance);
    expect(
      expandedGeometry.documentOverflow,
      `${theme} expanded`,
    ).toBeLessThanOrEqual(0);
  }
});
