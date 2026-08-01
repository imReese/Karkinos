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
    await readiness.locator(':scope > summary').click();
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
    await readiness.locator(':scope > summary').click();
    await expect(readiness).not.toHaveAttribute('open', '');

    for (const viewport of acceptanceViewports) {
      await page.setViewportSize(viewport);
      const geometry = await metrics.evaluate((element) => {
        const before = getComputedStyle(element, '::before');
        const commandGrid = document.querySelector(
          '[data-testid="operations-command-grid"]',
        ) as HTMLElement;
        const attentionQueue = document.querySelector(
          '[data-testid="operations-attention-queue"]',
        ) as HTMLElement;
        const readiness = document.querySelector(
          '[data-testid="controlled-pilot-readiness"]',
        ) as HTMLElement;
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
          metricOverflow: element.scrollWidth - element.clientWidth,
          labelContent: before.content.replace(/^['"]|['"]$/g, ''),
          columnCount:
            getComputedStyle(element).gridTemplateColumns.split(' ').length,
          pilotBelowAttention:
            readiness.getBoundingClientRect().top >=
            attentionQueue.getBoundingClientRect().bottom,
          readinessBeforeMetrics:
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
      expect(
        geometry.commandColumnCount,
        `${theme} ${viewport.width} command grid`,
      ).toBe(1);
      expect(
        Math.abs(geometry.attentionWidthDelta),
        `${theme} ${viewport.width} attention width`,
      ).toBeLessThanOrEqual(headlessSubpixelTolerance);
      expect(
        geometry.pilotBelowAttention,
        `${theme} ${viewport.width} pilot order`,
      ).toBe(true);
      expect(geometry.columnCount, `${theme} ${viewport.width}`).toBe(
        viewport.width < 640 ? 2 : 4,
      );
      expect(
        geometry.readinessBeforeMetrics,
        `${theme} ${viewport.width}`,
      ).toBe(true);
      if (viewport.width < 640) {
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
